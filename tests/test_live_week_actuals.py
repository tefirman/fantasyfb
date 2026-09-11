"""Tests for League's live-week real-score blending (issue #18).

During the current week of the active season, starters whose NFL game
has already finished should contribute their *actual* fantasy points
(with zero variance) to the team-level projection, while starters whose
game hasn't happened yet keep their projection. In-progress games are
treated as not-yet-done.

These bypass League.__init__ via __new__ and seed only the attributes
the three methods under test read, plus a fake nfl_provider whose
get_player_stats returns a canned box score.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from fantasyfb import League
from fantasyfb.configs import apply_default_scoring_categories


SCORING = apply_default_scoring_categories({
    "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
    "Rush Yds": 0.1, "Rush TD": 6,
    "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
    "Fum Lost": -2,
})


class _FakeProvider:
    """Stand-in for NflreadpyProvider.get_player_stats returning one
    canned week of box scores."""

    def __init__(self, box: pd.DataFrame):
        self._box = box
        self.calls: list[tuple[int, int]] = []

    def get_player_stats(self, start: int, finish: int) -> pd.DataFrame:
        self.calls.append((start, finish))
        return self._box.copy()


def _box_score() -> pd.DataFrame:
    """Two players on DONE_TEAM with real yardage, one on LATE_TEAM.

    Only offense columns FantasyScorer needs; the scorer tolerates the
    rest being absent.
    """
    return pd.DataFrame({
        "player_id_sr": ["p_done_1", "p_done_2", "p_late"],
        "name": ["Done One", "Done Two", "Late Guy"],
        "position": ["RB", "WR", "QB"],
        "team": ["DONE_TEAM", "DONE_TEAM", "LATE_TEAM"],
        "season": [2026, 2026, 2026],
        "week": [3, 3, 3],
        "rush_yds": [100, 0, 0],
        "rush_td": [1, 0, 0],
        "rec": [0, 8, 0],
        "rec_yds": [0, 80, 0],
        "rec_td": [0, 1, 0],
        "pass_yds": [0, 0, 300],
        "pass_td": [0, 0, 3],
        "pass_int": [0, 0, 1],
        "fumbles_lost": [0, 0, 0],
    })


def _make_league(*, current_week=3, season=2026, latest_season=2026,
                 provider=None, nfl_schedule=None) -> League:
    lg = League.__new__(League)
    lg.current_week = current_week
    lg.season = season
    lg.latest_season = latest_season
    lg.scoring = SCORING
    lg.nfl_provider = provider
    lg.nfl_schedule = nfl_schedule
    return lg


# A fixed "wall clock now" all fixtures and the frozen datetime agree on.
_NOW = datetime.datetime(2026, 10, 7, 22, 0, 0)  # a Wed evening, week 3-ish


def _schedule_done_and_late() -> pd.DataFrame:
    """DONE_TEAM played two days ago; LATE_TEAM plays tomorrow -- both
    relative to _NOW, not the real clock."""
    return pd.DataFrame({
        "season": [2026, 2026],
        "week": [3, 3],
        "team": ["DONE_TEAM", "LATE_TEAM"],
        "date": [_NOW - datetime.timedelta(days=2),
                 _NOW + datetime.timedelta(days=1)],
    })


def _players() -> pd.DataFrame:
    """Four rostered players: two starters on the finished game, one
    starter on the late game, one benched player on the finished game."""
    return pd.DataFrame({
        "player_id_sr": ["p_done_1", "p_done_2", "p_late", "p_bench"],
        "name": ["Done One", "Done Two", "Late Guy", "Bench Guy"],
        "position": ["RB", "WR", "QB", "RB"],
        "current_team": ["DONE_TEAM", "DONE_TEAM", "LATE_TEAM", "DONE_TEAM"],
        "fantasy_team": ["A", "A", "B", "A"],
        "points_avg": [11.0, 9.0, 18.0, 5.0],
        "points_stdev": [6.0, 5.0, 7.0, 4.0],
        "starter": [True, True, True, False],
    })


class TestCompletedNflTeams:
    def test_only_past_games_counted(self):
        lg = _make_league(nfl_schedule=_schedule_done_and_late())
        done = _run_at(lg, _NOW, lambda: lg._completed_nfl_teams(3))
        assert "DONE_TEAM" in done
        assert "LATE_TEAM" not in done

    def test_other_week_excluded(self):
        sched = _schedule_done_and_late()
        sched.loc[sched.team == "DONE_TEAM", "week"] = 2
        lg = _make_league(nfl_schedule=sched)
        assert _run_at(lg, _NOW, lambda: lg._completed_nfl_teams(3)) == []


class TestLiveWeekActuals:
    def test_offseason_returns_empty(self):
        lg = _make_league(provider=_FakeProvider(_box_score()),
                          nfl_schedule=_schedule_done_and_late())
        # July -> not in season regardless of week match
        july = _NOW.replace(month=7)
        real = _run_at(lg, july, lambda: lg._live_week_actuals(3))
        assert real.empty

    def test_non_current_week_returns_empty(self):
        lg = _make_league(provider=_FakeProvider(_box_score()),
                          nfl_schedule=_schedule_done_and_late())
        real = _run_at(lg, _NOW, lambda: lg._live_week_actuals(4))
        assert real.empty

    def test_returns_real_points_for_finished_game_only(self):
        provider = _FakeProvider(_box_score())
        lg = _make_league(provider=provider, nfl_schedule=_schedule_done_and_late())
        real = _run_at(lg, _NOW, lambda: lg._live_week_actuals(3))

        assert set(real.index) == {"p_done_1", "p_done_2"}
        # p_done_1: 100 rush yds (10) + 1 rush TD (6) = 16.0
        assert real["p_done_1"] == pytest.approx(16.0)
        # p_done_2: 8 rec (4) + 80 rec yds (8) + 1 rec TD (6) = 18.0
        assert real["p_done_2"] == pytest.approx(18.0)
        assert provider.calls == [(202603, 202603)]

    def test_empty_when_no_game_finished(self):
        sched = _schedule_done_and_late()
        sched["date"] = _NOW + datetime.timedelta(days=1)
        lg = _make_league(provider=_FakeProvider(_box_score()), nfl_schedule=sched)
        real = _run_at(lg, _NOW, lambda: lg._live_week_actuals(3))
        assert real.empty


class TestApplyLiveWeekActuals:
    def test_locks_finished_starters_leaves_others(self):
        provider = _FakeProvider(_box_score())
        lg = _make_league(provider=provider, nfl_schedule=_schedule_done_and_late())
        players = _players()

        out = _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))

        done1 = out.set_index("player_id_sr").loc["p_done_1"]
        done2 = out.set_index("player_id_sr").loc["p_done_2"]
        late = out.set_index("player_id_sr").loc["p_late"]
        bench = out.set_index("player_id_sr").loc["p_bench"]

        # Finished starters: real points, zero variance.
        assert done1["points_avg"] == pytest.approx(16.0)
        assert done1["points_stdev"] == 0.0
        assert done2["points_avg"] == pytest.approx(18.0)
        assert done2["points_stdev"] == 0.0
        # Late starter: untouched projection.
        assert late["points_avg"] == 18.0
        assert late["points_stdev"] == 7.0
        # Benched player on the finished game: untouched (not a starter).
        assert bench["points_avg"] == 5.0
        assert bench["points_stdev"] == 4.0

    def test_does_not_mutate_input(self):
        provider = _FakeProvider(_box_score())
        lg = _make_league(provider=provider, nfl_schedule=_schedule_done_and_late())
        players = _players()
        before = players.copy()

        _run_at(lg, _NOW, lambda: lg._apply_live_week_actuals(players, 3))

        pd.testing.assert_frame_equal(players, before)

    def test_noop_returns_unchanged_copy_offseason(self):
        provider = _FakeProvider(_box_score())
        lg = _make_league(provider=provider, nfl_schedule=_schedule_done_and_late())
        players = _players()
        june = _NOW.replace(month=6)
        out = _run_at(lg, june, lambda: lg._apply_live_week_actuals(players, 3))
        # Fresh object, identical content -- callers append scratch columns
        # to the result, so it must never alias self.players.
        assert out is not players
        pd.testing.assert_frame_equal(out, players)


def _run_at(lg, when: datetime.datetime, fn):
    """Call fn() with datetime.datetime.now() pinned to `when`, so both
    the in-season month check and the nfl_schedule date comparisons are
    deterministic against the fixture dates (which are built off _NOW).
    """
    import fantasyfb.league as mod

    real_dt = mod.datetime.datetime

    class _FrozenDateTime(real_dt):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.replace(tzinfo=tz)

    mod.datetime.datetime = _FrozenDateTime
    try:
        return fn()
    finally:
        mod.datetime.datetime = real_dt
