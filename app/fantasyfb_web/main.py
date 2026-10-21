"""
FastAPI app: pick a Sleeper league (or sign in with Yahoo) and a team, queue a
simulation, view the report.

Run locally with::

    uvicorn fantasyfb_web.main:app --app-dir app --reload
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fantasyfb.data.yahoo_auth import YahooAuthError
from fantasyfb.io import html_exporter

from . import sleeper, yahoo
from .jobs import DONE, FAILED, JobManager, QueueFull, TooManyRuns
from .pipeline import RunOptions, build_report
from .sessions import COOKIE_NAME, Session, SessionStore

log = logging.getLogger("uvicorn.error")

_HERE = os.path.dirname(__file__)
# Share the report's design system rather than copying it, so the app and
# the reports it produces can't drift apart.
_CSS_PATH = os.path.join(html_exporter._TEMPLATE_DIR, "industry-styles.css")
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "fantasyfb_logo.png")

SIM_CHOICES = (1000, 5000, 10000)


class RunRequest(BaseModel):
    platform: str = "sleeper"
    league_id: str = ""
    team: str = Field(min_length=1, max_length=200)
    sims: int = 1000
    payouts: List[float] = Field(default=[60.0, 30.0, 10.0], min_length=3, max_length=3)
    adds: bool = False
    drops: bool = False
    deltas: bool = False


def create_app(
    runner: Callable = build_report,
    lookup: Callable[[str], Dict] = sleeper.league_summary,
    max_workers: int = 1,
    yahoo_config: Optional[yahoo.YahooConfig] = None,
    yahoo_exchange: Callable = yahoo.exchange_code,
    yahoo_teams: Callable = yahoo.list_teams,
    sessions: Optional[SessionStore] = None,
    cookie_secure: Optional[bool] = None,
    enable_moves: Optional[bool] = None,
    enable_rooting: Optional[bool] = None,
    isolate: bool = False,
    run_timeout: Optional[float] = None,
    max_queued: Optional[int] = None,
) -> FastAPI:
    """
    Build the app. ``runner``, ``lookup``, and the ``yahoo_*`` hooks are
    injectable for tests. ``yahoo_config`` of None means Yahoo sign-in is off.
    """
    app = FastAPI(title="fantasyfb", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
    if run_timeout is None:
        run_timeout = float(os.environ.get("FANTASYFB_RUN_TIMEOUT", 20 * 60))
    if max_queued is None:
        max_queued = int(os.environ.get("FANTASYFB_MAX_QUEUED", 10))
    jobs = JobManager(
        runner, max_workers=max_workers, max_jobs=max_queued, isolate=isolate, timeout_seconds=run_timeout
    )
    sessions = sessions or SessionStore()
    if enable_moves is None:
        # Adds and drops are slow (a full season sim per candidate) and give
        # an edge over other managers, so the hosted app leaves them off.
        enable_moves = os.environ.get("FANTASYFB_ENABLE_MOVES", "0") == "1"
    if enable_rooting is None:
        # The rooting guide computes a delta for every game in the league,
        # which is too slow for the hosted app until it is sped up.
        enable_rooting = os.environ.get("FANTASYFB_ENABLE_ROOTING", "0") == "1"
    if cookie_secure is None:
        # Secure cookies need https, which Yahoo requires of the redirect
        # anyway. Only turn this off deliberately.
        cookie_secure = os.environ.get("FANTASYFB_COOKIE_SECURE", "1") != "0"

    def _session(request: Request) -> Optional[Session]:
        return sessions.get(request.cookies.get(COOKIE_NAME))

    def _set_cookie(response: Response, session: Session) -> None:
        response.set_cookie(
            COOKIE_NAME,
            session.id,
            httponly=True,  # not readable by page scripts
            secure=cookie_secure,
            samesite="lax",  # sent on the redirect back from Yahoo, not on cross-site POSTs
            path="/",
        )

    def allowed_hosts(request: Request) -> set:
        # The Host header, plus the public host from the configured redirect
        # URI: behind a hosting proxy the two can differ, and the latter is
        # ours by construction.
        hosts = {request.headers.get("host")}
        if yahoo_config is not None:
            hosts.add(urlparse(yahoo_config.redirect_uri).netloc)
        return hosts

    @app.get("/healthz")
    def healthz() -> Dict:
        return {"ok": True}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Cross-site POSTs already lack the SameSite=Lax cookie; this also
        # refuses any browser-declared foreign origin outright.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc not in allowed_hosts(request):
                return Response("Cross-origin request refused.", status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith(("/auth/", "/api/yahoo", "/api/runs", "/runs/")):
            response.headers["Cache-Control"] = "no-store"
        return response
    with open(_CSS_PATH, encoding="utf-8") as f:
        css = f.read()

    def _lookup(raw_id: str) -> Dict:
        league_id = sleeper.parse_league_id(raw_id)
        if not league_id:
            raise HTTPException(400, "That doesn't look like a Sleeper league ID or league URL.")
        try:
            return lookup(league_id)
        except sleeper.LeagueNotFound:
            raise HTTPException(404, "Sleeper has no league with that ID.")
        except requests.RequestException:
            raise HTTPException(502, "Couldn't reach Sleeper. Try again in a minute.")

    with open(_LOGO_PATH, "rb") as f:
        logo = f.read()

    @app.get("/static/fantasyfb_logo.png")
    def logo_png() -> Response:
        return Response(logo, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/static/industry-styles.css")
    def styles() -> Response:
        return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})

    def _client_keys(request: Request, session: Optional[Session]) -> List[str]:
        """Who is asking, for the one-run-at-a-time limit: the signed-in session and/or the address."""
        keys = []
        if session and session.yahoo:
            keys.append("session:" + session.id)
        keys.append("ip:" + (request.client.host if request.client else "unknown"))
        return keys

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        session = _session(request)
        active = jobs.active_for(*_client_keys(request, session))
        return templates.TemplateResponse(
            request,
            "index.html.j2",
            {
                "sim_choices": SIM_CHOICES,
                "yahoo_enabled": yahoo_config is not None,
                "yahoo_signed_in": bool(session and session.yahoo),
                "moves_enabled": enable_moves,
                "rooting_enabled": enable_rooting,
                "active_run": {"url": f"/runs/{active.id}", "team": active.opts.team} if active else None,
            },
        )

    # ---- Yahoo sign-in ----

    @app.get("/auth/yahoo/login")
    def yahoo_login(request: Request):
        if yahoo_config is None:
            raise HTTPException(404, "Yahoo sign-in isn't set up on this server.")
        session = _session(request) or sessions.create()
        session.oauth_state = secrets.token_urlsafe(24)
        response = RedirectResponse(yahoo.authorize_url(yahoo_config, session.oauth_state), status_code=303)
        _set_cookie(response, session)
        return response

    @app.get("/auth/yahoo/callback")
    def yahoo_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if yahoo_config is None:
            raise HTTPException(404, "Yahoo sign-in isn't set up on this server.")
        session = _session(request)
        # The state is single-use: take it before checking so a replay fails.
        expected = session.oauth_state if session else None
        if session:
            session.oauth_state = None
        if not expected or not hmac.compare_digest(expected, state):
            # Say why, without logging the state itself, so a failed sign-in is debuggable.
            if COOKIE_NAME not in request.cookies:
                reason = "the browser sent no session cookie"
            elif session is None:
                reason = "the session cookie is unknown or expired (server restarted?)"
            elif not expected:
                reason = "no sign-in was in progress for this session (state already used)"
            elif not state:
                reason = "Yahoo's redirect carried no state"
            else:
                reason = "state did not match"
            log.warning("Yahoo callback refused: %s (host=%s)", reason, request.headers.get("host"))
            raise HTTPException(400, "That sign-in link is invalid or expired. Start again from the home page.")
        if error or not code:
            return RedirectResponse("/?yahoo=denied", status_code=303)
        try:
            session.yahoo = yahoo_exchange(yahoo_config, code)
        except YahooAuthError as exc:
            log.warning("Yahoo sign-in failed at the token exchange: %s", exc)
            return RedirectResponse("/?yahoo=failed", status_code=303)
        except requests.RequestException as exc:
            log.warning("Yahoo sign-in failed, couldn't reach Yahoo: %s", type(exc).__name__)
            return RedirectResponse("/?yahoo=failed", status_code=303)
        except (KeyError, ValueError):
            log.warning("Yahoo sign-in failed, the token response was missing expected fields")
            return RedirectResponse("/?yahoo=failed", status_code=303)
        sessions.rotate(session)
        response = RedirectResponse("/?platform=yahoo", status_code=303)
        _set_cookie(response, session)
        return response

    @app.post("/auth/logout")
    def logout(request: Request) -> Response:
        sessions.destroy(request.cookies.get(COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    def _yahoo_teams(request: Request) -> Dict:
        session = _session(request)
        if not (session and session.yahoo):
            raise HTTPException(401, "Sign in with Yahoo first.")
        season = yahoo.current_season()
        try:
            names = yahoo_teams(session.yahoo, season)
        except YahooAuthError:
            session.yahoo.clear()
            session.yahoo = None
            raise HTTPException(401, "Your Yahoo sign-in expired. Sign in again.")
        except Exception:
            raise HTTPException(502, "Couldn't load your teams from Yahoo. Try again in a minute.")
        if not names:
            raise HTTPException(404, f"Yahoo shows no NFL fantasy teams for the {season} season on this account.")
        return {
            "platform": "yahoo",
            "league_id": "",
            "name": "Your Yahoo teams",
            "season": season,
            "status": "in_season",
            "teams": [{"name": n, "manager": n} for n in names],
        }

    @app.get("/api/yahoo/teams")
    def yahoo_team_list(request: Request) -> Dict:
        return _yahoo_teams(request)

    @app.get("/api/leagues")
    def league(q: str = "") -> Dict:
        # A query param, not a path segment: pasted league URLs contain slashes.
        return _lookup(q)

    @app.post("/api/runs", status_code=202)
    def create_run(request: Request, body: RunRequest) -> Dict:
        if body.sims not in SIM_CHOICES:
            raise HTTPException(422, f"sims must be one of {list(SIM_CHOICES)}")
        if any(p < 0 for p in body.payouts):
            raise HTTPException(422, "Payouts can't be negative.")
        if (body.adds or body.drops) and not enable_moves:
            raise HTTPException(422, "Adds and drops analysis isn't available on this server.")
        if body.deltas and not enable_rooting:
            raise HTTPException(422, "The rooting guide isn't available on this server.")
        if body.platform not in ("sleeper", "yahoo"):
            raise HTTPException(422, "platform must be 'sleeper' or 'yahoo'.")
        owner = auth = session = None
        if body.platform == "yahoo":
            session = _session(request)
            summary = _yahoo_teams(request)  # 401s when not signed in
            owner, auth = session.id, session.yahoo
        else:
            summary = _lookup(body.league_id)
        if body.team not in {t["name"] for t in summary["teams"]}:
            raise HTTPException(422, "That team isn't in this league.")
        if summary["status"] in ("pre_draft", "drafting"):
            raise HTTPException(409, "This league hasn't finished its draft yet, so there are no rosters to simulate.")
        opts = RunOptions(
            platform=body.platform,
            league_id=summary["league_id"],
            team=body.team,
            season=summary["season"],
            sims=body.sims,
            payouts=tuple(body.payouts),
            adds=body.adds,
            drops=body.drops,
            deltas=body.deltas,
        )
        try:
            # One run at a time per person: the signed-in session for Yahoo,
            # the address for Sleeper (which has no sign-in).
            client_key = _client_keys(request, session)[0]
            job = jobs.submit(opts, owner=owner, auth=auth, client_key=client_key)
        except QueueFull:
            raise HTTPException(503, "Too many simulations are queued right now. Try again shortly.")
        except TooManyRuns as busy:
            return JSONResponse(
                {
                    "detail": "You already have a simulation in progress. Wait for it to finish first.",
                    "url": f"/runs/{busy.job.id}",
                },
                status_code=429,
            )
        return {"id": job.id, "url": f"/runs/{job.id}"}

    def _get_job(request: Request, job_id: str):
        job = jobs.get(job_id)
        # A private run answers exactly like a missing one to anyone but the
        # session that started it, so its existence isn't revealed either.
        if job is not None and job.owner is not None:
            session = _session(request)
            if not (session and hmac.compare_digest(session.id, job.owner)):
                job = None
        if job is None:
            raise HTTPException(404, "No such run. Finished runs are kept for a few hours.")
        return job

    @app.get("/api/runs/{job_id}")
    def run_status(request: Request, job_id: str) -> Dict:
        job = _get_job(request, job_id)
        now = job.finished or time.time()
        return {
            "id": job.id,
            "status": job.status,
            "stage": job.stage,
            "stages": job.stages,
            "queue_position": jobs.queue_position(job),
            "elapsed": round(now - (job.started or now), 1),
            "error": job.error,
        }

    @app.get("/runs/{job_id}", response_class=HTMLResponse)
    def run_page(request: Request, job_id: str):
        job = _get_job(request, job_id)
        if job.status == DONE:
            return HTMLResponse(_with_app_bar(job.html, job.id))
        return templates.TemplateResponse(
            request, "run.html.j2", {"job": job, "failed": job.status == FAILED}
        )

    @app.get("/runs/{job_id}/download")
    def download(request: Request, job_id: str) -> Response:
        job = _get_job(request, job_id)
        if job.status != DONE:
            raise HTTPException(409, "This run hasn't finished yet.")
        filename = f"fantasyfb_{job.opts.league_id or job.opts.platform}.html"
        return Response(
            job.html,
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


# Slim bar added above a report when the app serves it, so a viewer can get
# back to the picker. The downloaded file stays exactly what the CLI writes.
_APP_BAR = (
    '<div class="no-print" style="display:flex;justify-content:space-between;align-items:center;gap:12px;'
    'padding:8px 20px;font:13px Barlow,system-ui,sans-serif;background:#1d2d3d;color:#eef6ff">'
    '<span style="display:inline-flex;align-items:center;gap:14px">'
    '<a href="/" style="display:inline-flex;background:#eef6ff;border-radius:4px;padding:2px 5px" title="fantasyfb">'
    '<img src="/static/fantasyfb_logo.png" alt="fantasyfb" width="15" height="23" style="display:block"></a>'
    '<a href="/" style="color:inherit">&larr; Run another league</a></span>'
    '<span style="display:inline-flex;align-items:center;gap:18px">'
    '<a href="https://github.com/tefirman/fantasyfb" target="_blank" rel="noopener" '
    'style="color:inherit;display:inline-flex;align-items:center;gap:6px;text-decoration:none">'
    '<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true" style="flex:none"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>Source on GitHub</a>'
    '<a href="/runs/{id}/download" style="color:inherit">Download report</a></span></div>'
)


def _with_app_bar(html: str, job_id: str) -> str:
    return html.replace("<body>", "<body>" + _APP_BAR.replace("{id}", job_id), 1)


app = create_app(yahoo_config=yahoo.YahooConfig.from_env(), isolate=True)
