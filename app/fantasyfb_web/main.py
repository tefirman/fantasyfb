"""
FastAPI app: pick a Sleeper league and team, queue a simulation, view the report.

Run locally with::

    uvicorn fantasyfb_web.main:app --app-dir app --reload
"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, List

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fantasyfb.io import html_exporter

from . import sleeper
from .jobs import DONE, FAILED, JobManager, QueueFull
from .pipeline import RunOptions, build_report

_HERE = os.path.dirname(__file__)
# Share the report's design system rather than copying it, so the app and
# the reports it produces can't drift apart.
_CSS_PATH = os.path.join(html_exporter._TEMPLATE_DIR, "industry-styles.css")

SIM_CHOICES = (1000, 5000, 10000)


class RunRequest(BaseModel):
    league_id: str
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
) -> FastAPI:
    """Build the app. ``runner`` and ``lookup`` are injectable for tests."""
    app = FastAPI(title="fantasyfb", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
    jobs = JobManager(runner, max_workers=max_workers)
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

    @app.get("/static/industry-styles.css")
    def styles() -> Response:
        return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html.j2", {"sim_choices": SIM_CHOICES})

    @app.get("/api/leagues")
    def league(q: str = "") -> Dict:
        # A query param, not a path segment: pasted league URLs contain slashes.
        return _lookup(q)

    @app.post("/api/runs", status_code=202)
    def create_run(body: RunRequest) -> Dict:
        if body.sims not in SIM_CHOICES:
            raise HTTPException(422, f"sims must be one of {list(SIM_CHOICES)}")
        if any(p < 0 for p in body.payouts):
            raise HTTPException(422, "Payouts can't be negative.")
        summary = _lookup(body.league_id)
        if body.team not in {t["name"] for t in summary["teams"]}:
            raise HTTPException(422, "That team isn't in this league.")
        if summary["status"] in ("pre_draft", "drafting"):
            raise HTTPException(409, "This league hasn't finished its draft yet, so there are no rosters to simulate.")
        opts = RunOptions(
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
            job = jobs.submit(opts)
        except QueueFull:
            raise HTTPException(503, "Too many simulations are queued right now. Try again shortly.")
        return {"id": job.id, "url": f"/runs/{job.id}"}

    def _get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "No such run. Finished runs are kept for a few hours.")
        return job

    @app.get("/api/runs/{job_id}")
    def run_status(job_id: str) -> Dict:
        job = _get_job(job_id)
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
        job = _get_job(job_id)
        if job.status == DONE:
            return HTMLResponse(_with_app_bar(job.html, job.id))
        return templates.TemplateResponse(
            request, "run.html.j2", {"job": job, "failed": job.status == FAILED}
        )

    @app.get("/runs/{job_id}/download")
    def download(job_id: str) -> Response:
        job = _get_job(job_id)
        if job.status != DONE:
            raise HTTPException(409, "This run hasn't finished yet.")
        filename = f"fantasyfb_{job.opts.league_id}.html"
        return Response(
            job.html,
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


# Slim bar added above a report when the app serves it, so a viewer can get
# back to the picker. The downloaded file stays exactly what the CLI writes.
_APP_BAR = (
    '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;'
    'padding:8px 20px;font:13px Barlow,system-ui,sans-serif;background:#1d2d3d;color:#eef6ff">'
    '<a href="/" style="color:inherit">&larr; Run another league</a>'
    '<a href="/runs/{id}/download" style="color:inherit">Download report</a></div>'
)


def _with_app_bar(html: str, job_id: str) -> str:
    return html.replace("<body>", "<body>" + _APP_BAR.replace("{id}", job_id), 1)


app = create_app()
