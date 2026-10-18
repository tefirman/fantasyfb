"""
Tests for running each simulation in a child process: a real timeout, crash
containment, and handing a Yahoo login across the process boundary.

The runners are module-level functions because a spawned child imports them
by name; a closure could not be sent to it.
"""

import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fantasyfb.data.yahoo_auth import YahooTokenAuth  # noqa: E402
from fantasyfb_web import sleeper  # noqa: E402
from fantasyfb_web.jobs import DONE, FAILED, JobManager, QueueFull, TooManyRuns  # noqa: E402
from fantasyfb_web.main import create_app  # noqa: E402
from fantasyfb_web.pipeline import RunOptions  # noqa: E402

OPTS = RunOptions(league_id="1", team="Alpha", season=2026)


def ok_runner(opts, progress):
    progress("Simulating the season")
    return "<html>ok for {}</html>".format(opts.team)


def user_error_runner(opts, progress):
    raise ValueError("No Sleeper team found matching name 'Alpha'")


def hang_runner(opts, progress):
    progress("Simulating the season")
    time.sleep(60)


def crash_runner(opts, progress):
    os._exit(137)  # what the kernel's out-of-memory killer looks like to the parent


def refreshing_runner(opts, progress, auth):
    # Pretend Yahoo expired the token mid-run and the child refreshed it.
    auth.access_token, auth.refresh_token, auth.token_time = "new-access", "new-refresh", time.time() + 1
    return "<html>refreshed</html>"


def slow_runner(opts, progress):
    time.sleep(0.5)
    return "<html>x</html>"


def finish(manager, job, timeout=30.0):
    deadline = time.time() + timeout
    while job.active and time.time() < deadline:
        time.sleep(0.05)
    assert not job.active, "job never finished"
    return job


def isolated(runner, **kwargs):
    return JobManager(runner, isolate=True, **kwargs)


def test_isolated_run_returns_html_and_relays_progress():
    manager = isolated(ok_runner)
    job = finish(manager, manager.submit(OPTS))
    assert job.status == DONE and job.html == "<html>ok for Alpha</html>"
    assert job.stages == ["Simulating the season"]


def test_user_facing_errors_survive_the_process_boundary():
    manager = isolated(user_error_runner)
    job = finish(manager, manager.submit(OPTS))
    assert job.status == FAILED and "No Sleeper team found" in job.error


def test_timeout_kills_the_run_and_frees_the_worker():
    manager = isolated(hang_runner, timeout_seconds=1)
    started = time.time()
    job = finish(manager, manager.submit(OPTS))
    assert job.status == FAILED and "longer than" in job.error
    assert time.time() - started < 20  # nowhere near the runner's 60 second sleep


def test_a_crashed_child_fails_only_that_run():
    manager = isolated(crash_runner)
    job = finish(manager, manager.submit(OPTS))
    assert job.status == FAILED and "crashed" in job.error
    # The manager is still healthy afterwards.
    manager._runner = ok_runner
    assert finish(manager, manager.submit(RunOptions("2", "Bravo", 2026))).status == DONE


def test_yahoo_tokens_cross_the_boundary_and_refreshed_ones_come_back():
    auth = YahooTokenAuth("key", "secret", "old-access", "old-refresh", "https://x.test/cb", token_time=time.time())
    manager = isolated(refreshing_runner)
    job = finish(manager, manager.submit(OPTS, owner="s1", auth=auth))
    assert job.status == DONE
    assert (auth.access_token, auth.refresh_token) == ("new-access", "new-refresh")
    assert job.auth is None  # dropped when the run ended


def test_signing_out_mid_run_is_not_undone_by_the_child():
    auth = YahooTokenAuth("key", "secret", "old-access", "old-refresh", "https://x.test/cb", token_time=time.time())
    auth.clear()
    auth.adopt({"access_token": "a", "refresh_token": "r", "token_time": time.time() + 5})
    assert auth.access_token == "" and auth.refresh_token == ""


def test_one_active_run_per_client_and_a_small_queue():
    manager = JobManager(slow_runner, max_jobs=2)
    first = manager.submit(OPTS, client_key="ip:1")
    with pytest.raises(TooManyRuns):
        manager.submit(RunOptions("2", "Bravo", 2026), client_key="ip:1")
    manager.submit(RunOptions("3", "Carol", 2026), client_key="ip:2")
    with pytest.raises(QueueFull):
        manager.submit(RunOptions("4", "Dana", 2026), client_key="ip:3")
    finish(manager, first)
    # Once the first run ends, that client can run again.
    manager.submit(RunOptions("5", "Eve", 2026), client_key="ip:1")


def test_api_answers_429_when_a_client_already_has_a_run():
    summary = {"league_id": "123456", "name": "L", "season": 2026, "status": "in_season",
               "teams": [{"name": "Alpha", "manager": "a"}, {"name": "Bravo", "manager": "b"}]}
    app = create_app(runner=slow_runner, lookup=lambda i: summary)
    client = TestClient(app)
    assert client.post("/api/runs", json={"league_id": "123456", "team": "Alpha"}).status_code == 202
    assert client.post("/api/runs", json={"league_id": "123456", "team": "Bravo"}).status_code == 429


def test_healthz_and_proxy_host_origin():
    from fantasyfb_web import yahoo
    config = yahoo.YahooConfig("k", "s", "https://my-space.hf.space/auth/yahoo/callback")
    client = TestClient(create_app(yahoo_config=config), base_url="http://internal:7860")
    assert client.get("/healthz").json() == {"ok": True}
    # Behind a proxy the Host header can be internal; the public origin is still ours.
    assert client.post("/auth/logout", headers={"Origin": "https://my-space.hf.space"}).status_code == 204
    assert client.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_busy_response_links_to_the_run_in_progress_and_home_page_shows_it():
    summary = {"league_id": "123456", "name": "L", "season": 2026, "status": "in_season",
               "teams": [{"name": "Alpha", "manager": "a"}, {"name": "Bravo", "manager": "b"}]}
    client = TestClient(create_app(runner=slow_runner, lookup=lambda i: summary))
    assert 'id="active-run"' not in client.get("/").text
    first = client.post("/api/runs", json={"league_id": "123456", "team": "Alpha"})
    busy = client.post("/api/runs", json={"league_id": "123456", "team": "Bravo"})
    assert busy.status_code == 429
    assert busy.json()["url"] == first.json()["url"]
    home = client.get("/").text
    assert first.json()["url"] in home and 'id="active-run"' in home
    deadline = time.time() + 5
    while 'id="active-run"' in client.get("/").text and time.time() < deadline:
        time.sleep(0.05)
    assert 'id="active-run"' not in client.get("/").text  # finished runs aren't "in progress"
