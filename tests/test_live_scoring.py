"""Tests for in-game live scoring: ESPN game-state parsing and the League blend.

A starter whose game has ``r`` of regulation left gets
``points_so_far + projection * r`` with stdev scaled by ``sqrt(r)``. Both live
feeds (game clock, platform points) are faked; nothing here touches the network.
"""

from __future__ import annotations

import pandas as pd
import pytest
import requests

from fantasyfb.data import game_state as gs
from fantasyfb.data.platform_client import FantasyPlatformClient
from fantasyfb.data.sleeper_client import SleeperClient

from test_live_week_actuals import (
    _NOW, _FakeProvider, _box_score, _make_league, _players,
    _run_at, _schedule_done_and_late,
)


def _event(short, state, period, clock, home, away):
    return {
        "shortName": short,
        "status": {"period": period, "displayClock": clock, "type": {"state": state}},
        "competitions": [{"competitors": [
            {"team": {"abbreviation": home}}, {"team": {"abbreviation": away}},
        ]}],
    }


class TestFractionRemaining:
    @pytest.mark.parametrize("state,period,clock,expected", [
        ("pre", 0, "0:00", 1.0),
        ("post", 4, "0:00", 0.0),
        ("in", 1, "15:00", 1.0),
        ("in", 2, "0:00", 0.5),       # halftime
        ("in", 3, "7:30", 0.375),
        ("in", 4, "0:41.0", 41 / 60 / 60),
        ("in", 5, "9:00", 0.0),       # overtime
    ])
    def test_values(self, state, period, clock, expected):
        assert gs.fraction_remaining(state, period, clock) == pytest.approx(expected)


class TestParseScoreboard:
    def test_maps_both_teams_and_nflverse_codes(self):
        payload = {"events": [
            _event("LAR @ WSH", "in", 4, "15:00", "WSH", "LAR"),
            _event("IND @ HOU", "post", 4, "0:00", "HOU", "IND"),
            {"shortName": "junk", "status": {"type": {"state": "weird"}}},
        ]}
        out = gs.parse_scoreboard(payload)
        assert set(out) == {"LA", "WAS", "IND", "HOU"}
        assert out["LA"]["remaining"] == pytest.approx(0.25)
        assert out["WAS"]["state"] == "in"
        assert out["HOU"]["remaining"] == 0.0

    def test_fetch_failure_degrades_to_empty_with_warning(self, monkeypatch):
        def boom(*a, **k):
            raise requests.ConnectionError("offline")
        monkeypatch.setattr(gs.requests, "get", boom)
        with pytest.warns(UserWarning, match="ESPN"):
            assert gs.EspnGameStateProvider().get_game_state(3) == {}


class _FakeGameState:
    def __init__(self, state):
        self._state = state

    def get_game_state(self, week=None):
        return self._state


class _FakeClient:
    def __init__(self, points=None, raises=False):
        self._points = points if points is not None else pd.Series(dtype=float)
        self._raises = raises

    def get_live_player_points(self, week):
        if self._raises:
            raise RuntimeError("feed down")
        return self._points


def _live_league(state, client):
    lg = _make_league(provider=_FakeProvider(_box_score()),
                      nfl_schedule=_schedule_done_and_late())
    lg.game_state_provider = _FakeGameState(state)
    lg.client = client
    return lg


def _live_players():
    p = _players()
    p["player_id"] = ["y1", "y2", "y3", "y4"]
    # Distinct from the finished-game box score's ids so only the live path applies.
    p["player_id_sr"] = ["l1", "l2", "l3", "l4"]
    p["current_team"] = ["LIVE_TEAM", "LIVE_TEAM", "LATE_TEAM", "LIVE_TEAM"]
    return p


_LIVE = {"LIVE_TEAM": {"state": "in", "remaining": 0.25, "game": "x"},
         "LATE_TEAM": {"state": "pre", "remaining": 1.0, "game": "y"}}


class TestInProgressBlend:
    def test_blends_points_so_far_with_prorated_projection(self):
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"y1": 8.0, "y2": 2.0})))
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(_live_players(), 3)) \
            .set_index("player_id")
        # 8 + 11 * 0.25 ; stdev 6 * sqrt(0.25)
        assert out.loc["y1", "points_avg"] == pytest.approx(10.75)
        assert out.loc["y1", "points_stdev"] == pytest.approx(3.0)
        assert out.loc["y2", "points_avg"] == pytest.approx(2.0 + 9.0 * 0.25)
        # Not started: untouched. Bench on the live game: untouched.
        assert out.loc["y3", "points_avg"] == 18.0
        assert out.loc["y3", "points_stdev"] == 7.0
        assert out.loc["y4", "points_avg"] == 5.0

    def test_player_missing_from_feed_counts_zero_so_far(self):
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"y2": 2.0})))
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(_live_players(), 3)) \
            .set_index("player_id")
        assert out.loc["y1", "points_avg"] == pytest.approx(11.0 * 0.25)

    def test_integer_platform_ids_match(self):
        players = _live_players()
        players["player_id"] = [1, 2, 3, 4]
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"1": 8.0})))
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3)).set_index("player_id")
        assert out.loc[1, "points_avg"] == pytest.approx(10.75)

    @pytest.mark.parametrize("client", [_FakeClient(), _FakeClient(raises=True), None])
    def test_missing_or_failing_feed_keeps_projections(self, client):
        lg = _live_league(_LIVE, client)
        players = _live_players()
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))
        pd.testing.assert_frame_equal(out, players)

    def test_no_game_in_progress_keeps_projections(self):
        state = {"LIVE_TEAM": {"state": "pre", "remaining": 1.0, "game": "x"}}
        lg = _live_league(state, _FakeClient(pd.Series({"y1": 8.0})))
        players = _live_players()
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))
        pd.testing.assert_frame_equal(out, players)

    def test_offseason_is_a_noop(self):
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"y1": 8.0})))
        players = _live_players()
        out = _run_at(lg, _NOW.replace(month=6), lambda: lg._apply_live_week_actuals(players, 3))
        pd.testing.assert_frame_equal(out, players)

    def test_disabled_provider_is_a_noop(self):
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"y1": 8.0})))
        lg.game_state_provider = None
        players = _live_players()
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))
        pd.testing.assert_frame_equal(out, players)

    def test_does_not_mutate_input(self):
        lg = _live_league(_LIVE, _FakeClient(pd.Series({"y1": 8.0})))
        players = _live_players()
        before = players.copy()
        _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))
        pd.testing.assert_frame_equal(players, before)


class TestPlatformPoints:
    def test_default_is_empty(self):
        assert FantasyPlatformClient.get_live_player_points(object(), 3).empty

    def test_sleeper_aggregates_players_points(self, monkeypatch):
        import fantasyfb.data.sleeper_client as sc
        monkeypatch.setattr(sc, "fetch_matchups", lambda lid, wk: [
            {"roster_id": 1, "players_points": {"111": 12.5, "222": 0.0}},
            {"roster_id": 2, "players_points": {"333": 3.0, "444": None}},
            {"roster_id": 3},
        ])
        pts = SleeperClient("1").get_live_player_points(3)
        assert pts.to_dict() == {"111": 12.5, "222": 0.0, "333": 3.0}
        assert pts.dtype == float

    def test_sleeper_no_matchups_is_empty(self, monkeypatch):
        import fantasyfb.data.sleeper_client as sc
        monkeypatch.setattr(sc, "fetch_matchups", lambda lid, wk: [])
        assert SleeperClient("1").get_live_player_points(3).empty

