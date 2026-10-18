"""
Hermetic tests for in-memory Yahoo credentials and the client's injected-auth
mode (no Yahoo access, no files, no prompts).
"""

import os

import pytest

from fantasyfb.data import yahoo_auth
from fantasyfb.data.yahoo_auth import YahooAuthError, YahooTokenAuth
from fantasyfb.data.yahoo_client import YahooFantasyClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "SECRET-BODY"

    def json(self):
        return self._payload


def make_auth(**kwargs):
    return YahooTokenAuth("key", "secret", "access-1", "refresh-1", "https://x.test/cb", **kwargs)


def test_repr_never_shows_tokens():
    auth = make_auth()
    assert "access-1" not in repr(auth) and "refresh-1" not in repr(auth) and "secret" not in repr(auth)


def test_refresh_updates_tokens_and_session_in_place(monkeypatch):
    calls = []

    def fake_post(url, headers, data, timeout):
        calls.append((url, headers, data))
        return FakeResponse(200, {"access_token": "access-2"})

    monkeypatch.setattr(yahoo_auth.requests, "post", fake_post)
    auth = make_auth(token_time=0)
    assert auth.refresh_access_token() == {"access_token": "access-2"}
    assert auth.access_token == "access-2"
    assert auth.refresh_token == "refresh-1"  # Yahoo didn't rotate it, so it's kept
    assert auth.session.headers["Authorization"] == "Bearer access-2"
    assert auth.token_is_valid()
    url, headers, data = calls[0]
    assert url == yahoo_auth.TOKEN_URL and headers["Authorization"].startswith("Basic ")
    assert data["grant_type"] == "refresh_token" and data["refresh_token"] == "refresh-1"


def test_refresh_failure_raises_without_leaking_the_body(monkeypatch):
    monkeypatch.setattr(yahoo_auth.requests, "post", lambda *a, **k: FakeResponse(400))
    with pytest.raises(YahooAuthError) as exc:
        make_auth().refresh_access_token()
    assert "SECRET-BODY" not in str(exc.value)


def test_clear_drops_everything():
    auth = make_auth()
    auth.clear()
    assert auth.access_token == "" and auth.refresh_token == ""


def test_injected_client_reads_no_files_and_never_prompts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("prompted on stdin"))
    client = YahooFantasyClient(oauth=make_auth())
    assert client.oauth is not None
    assert os.listdir(tmp_path) == []  # no .env or oauth2.json written


def test_injected_client_refreshes_in_place_without_sleeping(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("slept"))
    auth = make_auth(token_time=0)  # issued long ago
    refreshed = []
    monkeypatch.setattr(auth, "refresh_access_token", lambda: refreshed.append(True))
    YahooFantasyClient(oauth=auth).refresh_oauth()
    assert refreshed == [True]

    fresh = make_auth()
    monkeypatch.setattr(fresh, "refresh_access_token", lambda: pytest.fail("refreshed a fresh token"))
    YahooFantasyClient(oauth=fresh).refresh_oauth()


def test_bounded_retries_raise_instead_of_hanging(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    client = YahooFantasyClient(oauth=make_auth(), max_query_tries=3, retry_wait=7)
    client._retry_wait("Query failed", 1)
    client._retry_wait("Query failed", 2)
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        client._retry_wait("Query failed", 3)
    assert sleeps == [7, 7]


def test_connect_requires_a_known_team_when_injected(monkeypatch):
    client = YahooFantasyClient(oauth=make_auth())
    monkeypatch.setattr(client, "_find_nfl_league_teams", lambda season: {"A": "423.l.1", "B": "423.l.2"})
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("prompted on stdin"))
    with pytest.raises(ValueError, match="No Yahoo team named"):
        client.connect_to_league(2026, "C")
