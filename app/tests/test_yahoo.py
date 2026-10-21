"""
Tests for Yahoo sign-in in the web app. Hermetic: Yahoo's token endpoint, team
lookup, and the simulation are stubbed. The focus is the security properties:
OAuth ``state`` handling, session handling, run isolation between users, and
tokens never appearing anywhere a user or log could see them.
"""

import time
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fantasyfb.data.yahoo_auth import YahooAuthError, YahooTokenAuth  # noqa: E402
from fantasyfb_web import yahoo  # noqa: E402
from fantasyfb_web.main import create_app  # noqa: E402
from fantasyfb_web.sessions import COOKIE_NAME, SessionStore  # noqa: E402

CONFIG = yahoo.YahooConfig("test-key", "test-secret", "https://localhost:8000/auth/yahoo/callback")
ACCESS, REFRESH = "ACCESS-TOKEN-VALUE", "REFRESH-TOKEN-VALUE"


def fake_exchange(config, code):
    if code != "good-code":
        raise YahooAuthError("rejected")
    return YahooTokenAuth(config.consumer_key, config.consumer_secret, ACCESS, REFRESH, config.redirect_uri)


def fake_teams(auth, season):
    return ["Gridiron Gang", "Second Team"]


def make_app(seen=None, teams=fake_teams, **kwargs):
    def runner(opts, progress, auth=None):
        if seen is not None:
            seen.append((opts, auth))
        progress("Simulating the season")
        return "<html><body><h1>private report for {}</h1></body></html>".format(opts.team)

    return create_app(
        runner=runner,
        yahoo_config=CONFIG,
        yahoo_exchange=fake_exchange,
        yahoo_teams=teams,
        cookie_secure=True,
        **kwargs,
    )


def new_browser(app):
    # https base URL so the Secure cookie is sent back, like a real browser would.
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def sign_in(browser):
    """Run the whole login dance and return the browser, now signed in."""
    login = browser.get("/auth/yahoo/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = browser.get("/auth/yahoo/callback", params={"code": "good-code", "state": state})
    assert callback.status_code == 303 and callback.headers["location"] == "/?platform=yahoo"
    return browser


def wait_for(browser, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = browser.get(f"/api/runs/{job_id}").json()
        if status["status"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError("run never finished")


# ---- login flow ----

def test_yahoo_option_hidden_when_not_configured():
    browser = new_browser(create_app(yahoo_config=None))
    assert "Sign in with Yahoo" not in browser.get("/").text
    assert browser.get("/auth/yahoo/login").status_code == 404


def test_login_redirects_to_yahoo_with_state_and_secure_cookie():
    browser = new_browser(make_app())
    resp = browser.get("/auth/yahoo/login")
    assert resp.status_code == 303
    target = urlparse(resp.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "api.login.yahoo.com"
    assert query["client_id"] == ["test-key"]
    assert query["redirect_uri"] == [CONFIG.redirect_uri]
    assert query["response_type"] == ["code"] and len(query["state"][0]) >= 20
    assert "test-secret" not in resp.headers["location"]
    cookie = resp.headers["set-cookie"].lower()
    assert COOKIE_NAME in cookie and "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie


def test_callback_rejects_missing_wrong_and_replayed_state():
    browser = new_browser(make_app())
    # No session at all (e.g. a forged link opened in a fresh browser).
    assert browser.get("/auth/yahoo/callback", params={"code": "good-code", "state": "x"}).status_code == 400

    login = browser.get("/auth/yahoo/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    assert browser.get("/auth/yahoo/callback", params={"code": "good-code", "state": "wrong"}).status_code == 400
    # The failed attempt consumed the state, so even the right value is now dead.
    assert browser.get("/auth/yahoo/callback", params={"code": "good-code", "state": state}).status_code == 400


def test_callback_handles_denied_and_rejected_codes():
    browser = new_browser(make_app())
    state = parse_qs(urlparse(browser.get("/auth/yahoo/login").headers["location"]).query)["state"][0]
    denied = browser.get("/auth/yahoo/callback", params={"error": "access_denied", "state": state})
    assert denied.headers["location"] == "/?yahoo=denied"

    state = parse_qs(urlparse(browser.get("/auth/yahoo/login").headers["location"]).query)["state"][0]
    bad = browser.get("/auth/yahoo/callback", params={"code": "bad-code", "state": state})
    assert bad.headers["location"] == "/?yahoo=failed"
    assert browser.get("/api/yahoo/teams").status_code == 401


def test_login_rotates_the_session_id():
    browser = new_browser(make_app())
    before = browser.get("/auth/yahoo/login").cookies.get(COOKIE_NAME)
    state = parse_qs(urlparse(browser.get("/auth/yahoo/login").headers["location"]).query)["state"][0]
    resp = browser.get("/auth/yahoo/callback", params={"code": "good-code", "state": state})
    assert resp.cookies.get(COOKIE_NAME) not in (None, before)


def test_teams_requires_sign_in_then_lists_teams():
    browser = new_browser(make_app())
    assert browser.get("/api/yahoo/teams").status_code == 401
    sign_in(browser)
    body = browser.get("/api/yahoo/teams").json()
    assert [t["name"] for t in body["teams"]] == ["Gridiron Gang", "Second Team"]
    assert body["platform"] == "yahoo"
    assert ACCESS not in str(body) and REFRESH not in str(body)


def test_expired_yahoo_login_asks_to_sign_in_again():
    def revoked(auth, season):
        raise YahooAuthError("revoked")

    browser = sign_in(new_browser(make_app(teams=revoked)))
    assert browser.get("/api/yahoo/teams").status_code == 401
    assert browser.get("/api/yahoo/teams").status_code == 401  # tokens were dropped, not retried


def test_logout_destroys_the_session():
    app = make_app()
    browser = sign_in(new_browser(app))
    assert browser.get("/api/yahoo/teams").status_code == 200
    assert browser.post("/auth/logout").status_code == 204
    assert browser.get("/api/yahoo/teams").status_code == 401


# ---- runs ----

def test_yahoo_run_requires_sign_in():
    browser = new_browser(make_app())
    resp = browser.post("/api/runs", json={"platform": "yahoo", "team": "Gridiron Gang"})
    assert resp.status_code == 401


def test_yahoo_run_end_to_end_and_tokens_dropped_from_job():
    seen = []
    app = make_app(seen, enable_rooting=True)
    browser = sign_in(new_browser(app))
    resp = browser.post("/api/runs", json={"platform": "yahoo", "team": "Gridiron Gang", "deltas": True})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    status = wait_for(browser, job_id)
    assert status["status"] == "done"
    opts, auth = seen[0]
    assert opts.platform == "yahoo" and opts.team == "Gridiron Gang" and opts.league_id == ""
    assert isinstance(auth, YahooTokenAuth)
    assert ACCESS not in repr(opts) and ACCESS not in str(status) and ACCESS not in repr(auth)

    page = browser.get(f"/runs/{job_id}")
    assert "private report for Gridiron Gang" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "attachment" in browser.get(f"/runs/{job_id}/download").headers["content-disposition"]


def test_yahoo_run_rejects_a_team_that_isnt_the_users():
    browser = sign_in(new_browser(make_app()))
    resp = browser.post("/api/runs", json={"platform": "yahoo", "team": "Someone Else's Team"})
    assert resp.status_code == 422


def test_other_sessions_cannot_see_a_private_run():
    app = make_app()
    owner = sign_in(new_browser(app))
    job_id = owner.post("/api/runs", json={"platform": "yahoo", "team": "Gridiron Gang"}).json()["id"]
    wait_for(owner, job_id)

    stranger = new_browser(app)
    for path in (f"/runs/{job_id}", f"/api/runs/{job_id}", f"/runs/{job_id}/download"):
        assert stranger.get(path).status_code == 404, path
    # A different signed-in user is a stranger too.
    other_user = sign_in(new_browser(app))
    assert other_user.get(f"/runs/{job_id}").status_code == 404
    assert owner.get(f"/runs/{job_id}").status_code == 200


def test_identical_yahoo_requests_from_two_users_are_not_merged():
    release = []

    def slow_runner(opts, progress, auth=None):
        while not release:
            time.sleep(0.01)
        return "<html><body>x</body></html>"

    app = create_app(
        runner=slow_runner, yahoo_config=CONFIG, yahoo_exchange=fake_exchange,
        yahoo_teams=fake_teams, cookie_secure=True,
    )
    a, b = sign_in(new_browser(app)), sign_in(new_browser(app))
    body = {"platform": "yahoo", "team": "Gridiron Gang"}
    id_a = a.post("/api/runs", json=body).json()["id"]
    id_b = b.post("/api/runs", json=body).json()["id"]
    release.append(True)
    assert id_a != id_b


# ---- cross-site protection and headers ----

def test_cross_origin_posts_are_refused():
    browser = sign_in(new_browser(make_app()))
    resp = browser.post(
        "/api/runs",
        json={"platform": "yahoo", "team": "Gridiron Gang"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert browser.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_security_headers_present():
    resp = new_browser(make_app()).get("/")
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


# ---- sessions ----

def test_sessions_expire_and_clear_tokens():
    store = SessionStore(idle_seconds=0.05)
    session = store.create()
    session.yahoo = fake_exchange(CONFIG, "good-code")
    auth = session.yahoo
    assert store.get(session.id) is session
    time.sleep(0.1)
    assert store.get(session.id) is None
    assert auth.access_token == "" and auth.refresh_token == ""


def test_session_store_evicts_least_recently_used_when_full():
    store = SessionStore(max_sessions=2)
    first, second = store.create(), store.create()
    store.get(second.id)
    third = store.create()
    assert store.get(first.id) is None
    assert store.get(second.id) is second and store.get(third.id) is third


def test_config_from_env_ignores_placeholders(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("CONSUMER_KEY", "updatekey")
    monkeypatch.setenv("CONSUMER_SECRET", "updatesecret")
    assert yahoo.YahooConfig.from_env() is None
    monkeypatch.setenv("CONSUMER_KEY", "real-key")
    monkeypatch.setenv("CONSUMER_SECRET", "real-secret")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "https://example.test/cb")
    config = yahoo.YahooConfig.from_env()
    assert config.redirect_uri == "https://example.test/cb"
    assert "real-secret" not in repr(config)


def test_yahoo_is_the_default_platform_when_configured():
    html = new_browser(make_app()).get("/").text
    assert 'value="yahoo" checked' in html and 'value="sleeper" checked' not in html
    assert '<form id="find" class="blueprint panel" hidden>' in html
    # Without Yahoo configured the page is Sleeper-only, as before.
    plain = new_browser(create_app(yahoo_config=None)).get("/").text
    assert 'name="platform"' not in plain and 'id="find" class="blueprint panel">' in plain
