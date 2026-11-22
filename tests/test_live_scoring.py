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
            assert gs.EspnGameStateProvider(retry_wait=0).get_game_state(3) == {}

    def test_one_blip_is_retried(self, monkeypatch):
        calls = []

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"events": [_event("A @ B", "in", 4, "15:00", "B", "A")]}

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise requests.Timeout("slow")
            return _Resp()

        monkeypatch.setattr(gs.requests, "get", flaky)
        out = gs.EspnGameStateProvider(retry_wait=0).get_game_state(3)
        assert len(calls) == 2 and set(out) == {"A", "B"}


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

    def test_finished_game_uses_points_so_far_with_no_variance(self):
        # Before the kickoff-date heuristic and the box score catch up, a game
        # ESPN calls final is already settled on the platform.
        state = {"LIVE_TEAM": {"state": "post", "remaining": 0.0, "game": "x"}}
        lg = _live_league(state, _FakeClient(pd.Series({"y1": 8.0})))
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(_live_players(), 3)) \
            .set_index("player_id")
        assert out.loc["y1", "points_avg"] == pytest.approx(8.0)
        assert out.loc["y1", "points_stdev"] == 0.0

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



def _yahoo_roster_response(players):
    """A trimmed team roster-with-stats response in Yahoo's real shape: each
    player is [[single-key dicts], {selected_position}, {player_stats, player_points}],
    with the empty-list padding Yahoo scatters around."""
    plist = {"count": len(players)}
    for i, (pid, total) in enumerate(players):
        plist[str(i)] = {"player": [
            [{"player_key": f"470.p.{pid}"}, {"player_id": pid}, [], {"name": {"full": "X"}}],
            {"selected_position": [{"coverage_type": "week"}, {"position": "RB"}]},
            {"player_stats": {"stats": []},
             "player_points": {"0": {"coverage_type": "week", "week": "11"}, "total": total}},
        ]}
    return {"fantasy_content": {"team": [[{"team_key": "t"}], {"roster": {"0": {"players": plist}}}]}}


class TestYahooLivePoints:
    def test_parse_roster_points(self):
        from fantasyfb.data.yahoo_client import parse_roster_points
        resp = _yahoo_roster_response([("30977", "21.46"), ("34019", "0.00"), ("100024", "")])
        assert parse_roster_points(resp) == {"30977": 21.46, "34019": 0.0}

    def test_client_collects_every_team(self):
        from fantasyfb.data.yahoo_client import YahooFantasyClient

        class _Handler:
            def get(self, path):
                key = path.split("/")[1]
                assert "week=11" in path
                return _yahoo_roster_response([({"t1": "1", "t2": "2"}[key], "5.50")])

        client = YahooFantasyClient.__new__(YahooFantasyClient)
        client.lg = type("L", (), {"yhandler": _Handler()})()
        client.refresh_oauth = lambda *a, **k: None
        client.get_fantasy_teams = lambda: [{"team_key": "t1"}, {"team_key": "t2"}]
        pts = client.get_live_player_points(11)
        assert pts.to_dict() == {"1": 5.5, "2": 5.5} and pts.dtype == float


class TestStartedNflTeams:
    def test_in_progress_and_final_count_but_not_pregame(self):
        state = {"A": {"state": "in", "remaining": 0.5, "game": "x"},
                 "B": {"state": "post", "remaining": 0.0, "game": "x"},
                 "C": {"state": "pre", "remaining": 1.0, "game": "y"}}
        lg = _live_league(state, _FakeClient())
        assert sorted(_run_at(lg, _NOW, lambda: lg._started_nfl_teams(3))) == ["A", "B"]

    def test_empty_offseason_or_disabled(self):
        lg = _live_league(_LIVE, _FakeClient())
        assert _run_at(lg, _NOW.replace(month=6), lambda: lg._started_nfl_teams(3)) == []
        lg.game_state_provider = None
        assert _run_at(lg, _NOW, lambda: lg._started_nfl_teams(3)) == []

    def test_game_state_is_cached_briefly(self):
        calls = []

        class _Counting(_FakeGameState):
            def get_game_state(self, week=None):
                calls.append(week)
                return super().get_game_state(week)

        lg = _live_league(_LIVE, _FakeClient())
        lg.game_state_provider = _Counting(_LIVE)
        _run_at(lg, _NOW, lambda: (lg._started_nfl_teams(3), lg._started_nfl_teams(3)))
        assert calls == [3]


def test_live_points_are_cached_briefly():
    calls = []

    class _CountingClient(_FakeClient):
        def get_live_player_points(self, week):
            calls.append(week)
            return super().get_live_player_points(week)

    lg = _live_league(_LIVE, _CountingClient(pd.Series({"y1": 8.0})))
    _run_at(lg, _NOW, lambda: [lg._apply_live_week_actuals(_live_players(), 3) for _ in range(3)])
    assert calls == [3]


class TestFinishedGamesPreferPlatformPoints:
    """For a finished game both the platform and nflverse's box score have the
    points. The platform's match the league app, so they win; the box score
    only fills in players the platform's feed doesn't have."""

    _FINAL = {"DONE_TEAM": {"state": "post", "remaining": 0.0, "game": "x"}}

    def _run(self, feed):
        lg = _live_league(self._FINAL, _FakeClient(pd.Series(feed, dtype=float)))
        players = _players()  # p_done_1/p_done_2 start on DONE_TEAM, finished by date
        players["player_id"] = ["d1", "d2", "d3", "d4"]
        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))
        return out.set_index("player_id_sr")

    def test_platform_points_win_over_box_score(self):
        out = self._run({"d1": 15.5, "d2": 17.0})
        # The box score would give 16.0 and 18.0.
        assert out.loc["p_done_1", "points_avg"] == pytest.approx(15.5)
        assert out.loc["p_done_2", "points_avg"] == pytest.approx(17.0)
        assert out.loc["p_done_1", "points_stdev"] == 0.0

    def test_player_missing_from_feed_falls_back_to_box_score(self):
        out = self._run({"d1": 15.5})
        assert out.loc["p_done_1", "points_avg"] == pytest.approx(15.5)
        assert out.loc["p_done_2", "points_avg"] == pytest.approx(18.0)
        assert out.loc["p_done_2", "points_stdev"] == 0.0

    def test_empty_feed_uses_box_score_as_before(self):
        out = self._run({})
        assert out.loc["p_done_1", "points_avg"] == pytest.approx(16.0)
        assert out.loc["p_done_2", "points_avg"] == pytest.approx(18.0)
