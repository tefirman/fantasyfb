"""
Tests for the Sleeper web app. Hermetic: Sleeper lookups and the simulation
pipeline are stubbed, so no network or nflverse download is needed.
"""

import time

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fantasyfb_web import sleeper  # noqa: E402
from fantasyfb_web.main import create_app  # noqa: E402
from fantasyfb_web.pipeline import RunOptions, build_report, top_free_agents  # noqa: E402

LEAGUE_ID = "1367870433398915072"
SUMMARY = {
    "league_id": LEAGUE_ID,
    "name": "Test League",
    "season": 2026,
    "status": "in_season",
    "teams": [
        {"name": "Alpha", "manager": "alice"},
        {"name": "Bravo", "manager": "bob"},
    ],
}


def fake_lookup(league_id):
    if league_id != LEAGUE_ID:
        raise sleeper.LeagueNotFound(league_id)
    return SUMMARY


def wait_for(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/runs/{job_id}").json()
        if status["status"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError("run never finished")


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(seen):
    def runner(opts, progress):
        seen.append(opts)
        progress("Simulating the season")
        if opts.team == "Bravo":
            raise ValueError("No Sleeper team found matching name 'Bravo'")
        return "<html><body><h1>report for {}</h1></body></html>".format(opts.team)

    return TestClient(create_app(runner=runner, lookup=fake_lookup, enable_moves=True, enable_rooting=True))


@pytest.mark.parametrize("text,expected", [
    (LEAGUE_ID, LEAGUE_ID),
    (f"  {LEAGUE_ID} ", LEAGUE_ID),
    (f"https://sleeper.com/leagues/{LEAGUE_ID}/matchup", LEAGUE_ID),
    (f"sleeper.app/leagues/{LEAGUE_ID}", LEAGUE_ID),
    ("not a league", None),
    ("", None),
    ("12345; rm -rf /", None),
])
def test_parse_league_id(text, expected):
    assert sleeper.parse_league_id(text) == expected


def test_index_and_styles(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Find your league" in page.text
    css = client.get("/static/industry-styles.css")
    assert css.status_code == 200 and "--color-accent" in css.text
    logo = client.get("/static/fantasyfb_logo.png")
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    assert "github.com/tefirman/fantasyfb" in page.text
    assert "poweredby.yahoo.com" not in page.text  # Sleeper-only: no Yahoo data shown


def test_home_screen_support(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["display"] == "standalone"
    for icon in manifest.json()["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"
    assert client.get("/static/icon-180.png").status_code == 200
    assert 'href="/static/icon-32.png"' in client.get("/").text  # tab favicon
    assert client.get("/static/icon-999.png").status_code == 404
    assert 'rel="manifest"' in client.get("/").text


def test_sims_is_a_free_number_within_bounds(client, seen):
    page = client.get("/").text
    assert 'name="sims"' in page and 'type="number"' in page and 'value="1000"' in page
    for sims in (100, 2500, 10000):
        resp = client.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", "sims": sims})
        assert resp.status_code == 202
        wait_for(client, resp.json()["id"])  # one run per visitor at a time
    assert client.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", "sims": 99}).status_code == 422


def test_yahoo_attribution_only_on_yahoo_app():
    from fantasyfb_web import yahoo

    cfg = yahoo.YahooConfig("k", "s", "https://localhost:8000/auth/yahoo/callback")
    page = TestClient(create_app(yahoo_config=cfg)).get("/").text
    assert "poweredby.yahoo.com/poweredby_yahoo_h_purple.png" in page
    assert "https://www.yahoo.com/?ilc=401" in page



def test_league_lookup(client):
    assert client.get("/api/leagues", params={"q": LEAGUE_ID}).json()["name"] == "Test League"
    url = f"https://sleeper.com/leagues/{LEAGUE_ID}/matchup"
    assert client.get("/api/leagues", params={"q": url}).json()["name"] == "Test League"
    assert client.get("/api/leagues", params={"q": "nope"}).status_code == 400
    assert client.get("/api/leagues", params={"q": "999999999"}).status_code == 404


def test_run_end_to_end(client, seen):
    resp = client.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", "sims": 5000, "adds": True})
    assert resp.status_code == 202
    job_id = resp.json()["id"]
    assert wait_for(client, job_id)["status"] == "done"
    assert seen[0] == RunOptions(
        league_id=LEAGUE_ID, team="Alpha", season=2026, sims=5000,
        payouts=(60.0, 30.0, 10.0), adds=True,
    )

    page = client.get(f"/runs/{job_id}")
    assert "report for Alpha" in page.text
    assert "Run another league" in page.text  # app bar injected
    assert "github.com/tefirman/fantasyfb" in page.text and "/static/fantasyfb_logo.png" in page.text
    download = client.get(f"/runs/{job_id}/download")
    assert "attachment" in download.headers["content-disposition"]
    assert "Run another league" not in download.text  # file is the plain report


def test_run_failure_shows_message(client):
    job_id = client.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Bravo"}).json()["id"]
    status = wait_for(client, job_id)
    assert status["status"] == "failed"
    assert "No Sleeper team found" in status["error"]
    assert "No Sleeper team found" in client.get(f"/runs/{job_id}").text


@pytest.mark.parametrize("body,code", [
    ({"league_id": LEAGUE_ID, "team": "Nobody"}, 422),
    ({"league_id": LEAGUE_ID, "team": "Alpha", "sims": 7}, 422),
    ({"league_id": LEAGUE_ID, "team": "Alpha", "sims": 10001}, 422),
    ({"league_id": LEAGUE_ID, "team": "Alpha", "payouts": [1, 2]}, 422),
    ({"league_id": LEAGUE_ID, "team": "Alpha", "payouts": [-1, 2, 3]}, 422),
    ({"league_id": "garbage", "team": "Alpha"}, 400),
])
def test_run_validation(client, body, code):
    assert client.post("/api/runs", json=body).status_code == code


def test_pre_draft_league_rejected(seen):
    def lookup(league_id):
        return dict(SUMMARY, status="pre_draft")

    app_client = TestClient(create_app(runner=lambda o, p: "", lookup=lookup))
    resp = app_client.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha"})
    assert resp.status_code == 409


def test_unknown_run_is_404(client):
    assert client.get("/runs/deadbeef").status_code == 404
    assert client.get("/api/runs/deadbeef").status_code == 404


# --- pipeline, against a stub League --------------------------------------

def _players():
    return pd.DataFrame({
        "name": ["QB Mine", "WR Mine", "QB Free", "WR Free 1", "WR Free 2", "Average_WR", "WR Hurt"],
        "position": ["QB", "WR", "QB", "WR", "WR", "WR", "WR"],
        "current_team": ["KC", "MIA", "BUF", "DAL", "SF", None, "NYJ"],
        "fantasy_team": ["Alpha", "Alpha", None, None, None, None, None],
        "WAR": [3.0, 2.0, 1.0, 0.2, 0.9, 5.0, 4.0],
        "until": [None, None, None, None, None, None, 18],
        "points_avg": [20.0, 15.0, 14.0, 6.0, 9.0, 8.0, 12.0],
    })


def test_top_free_agents_ranks_by_war_and_skips_placeholders():
    names = top_free_agents(_players(), per_position=1)
    assert sorted(names) == ["QB Free", "WR Free 2"]


class StubLeague:
    week = 6
    num_sims = 1000

    def __init__(self):
        self.players = _players()
        self.calls = []

    def season_sims(self, postseason, payouts):
        self.calls.append(("season_sims", payouts))
        schedule = pd.DataFrame({
            "week": [6], "team_1": ["Alpha"], "team_2": ["Bravo"], "win_1": [0.6],
            "win_2": [0.4], "points_avg_1": [110.0], "points_stdev_1": [20.0],
            "points_avg_2": [100.0], "points_stdev_2": [20.0], "me": [True],
        })
        standings = pd.DataFrame({"team": ["Alpha", "Bravo"], "playoffs": [0.7, 0.3], "earnings": [30.0, 12.0]})
        return schedule, standings

    def possible_adds(self, **kwargs):
        self.calls.append(("possible_adds", kwargs))
        return pd.DataFrame({"player_to_add": ["WR Free 2"], "earnings": [1.5]})


def test_build_report_with_stub_league():
    stub = StubLeague()
    stages = []
    opts = RunOptions(league_id=LEAGUE_ID, team="Alpha", season=2026, adds=True, payouts=(100.0, 50.0, 0.0))
    html = build_report(opts, progress=stages.append, league_factory=lambda o: stub)

    assert "<!DOCTYPE html>" in html and "Sleeper" in html
    assert "WR Free 2" in html
    assert stages[0].startswith("Loading") and stages[-1] == "Rendering report"
    adds_call = dict(stub.calls)["possible_adds"]
    # Sleeper has no roster %, so the filter must be off and the pool pre-ranked.
    assert adds_call["min_rostership"] == 0.0
    assert "WR Hurt" not in adds_call["focus_on"]
    assert adds_call["payouts"] == [100.0, 50.0, 0.0]


def test_build_report_shows_unsupported_scoring_notice():
    import warnings
    from fantasyfb.data.sleeper_client import UnsupportedScoringWarning

    def factory(opts):
        warnings.warn("Scores 40+ yard rushes (10 pts)", UnsupportedScoringWarning)
        return StubLeague()

    opts = RunOptions(league_id=LEAGUE_ID, team="Alpha", season=2026)
    html = build_report(opts, league_factory=factory)
    assert 'id="notices"' in html and "Scores 40+ yard rushes (10 pts)" in html
    # an ordinary run has no banner
    assert 'id="notices"' not in build_report(opts, league_factory=lambda o: StubLeague())


def test_adds_and_drops_are_refused_unless_enabled():
    off = TestClient(create_app(runner=lambda o, p: "<html></html>", lookup=fake_lookup, enable_moves=False))
    for flag in ("adds", "drops"):
        resp = off.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", flag: True})
        assert resp.status_code == 422
    assert 'name="adds"' not in off.get("/").text and 'name="drops"' not in off.get("/").text


def test_rooting_guide_is_refused_unless_enabled():
    off = TestClient(create_app(runner=lambda o, p: "<html></html>", lookup=fake_lookup, enable_rooting=False))
    resp = off.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", "deltas": True})
    assert resp.status_code == 422
    assert 'name="deltas"' not in off.get("/").text
    on = TestClient(create_app(runner=lambda o, p: "<html></html>", lookup=fake_lookup, enable_rooting=True))
    assert 'name="deltas"' in on.get("/").text
    assert on.post("/api/runs", json={"league_id": LEAGUE_ID, "team": "Alpha", "deltas": True}).status_code == 202
