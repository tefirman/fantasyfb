"""Tests for LineupOptimizer, focused on the live-week path.

_handle_live_week_lineup is responsible for locking in players whose NFL
game has already finished (using the real Yahoo/platform selected_position
at fetch time, since a completed game can't be re-optimized) while still
filling any remaining roster slots from players whose games haven't
started yet.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from fantasyfb.scoring.lineup_optimizer import LineupOptimizer
from fantasyfb.scoring.matchup_model import MatchupModel


class _StubClient:
    """Minimal FantasyPlatformClient stand-in -- refresh_oauth is a no-op
    on the base class, but LineupOptimizer calls it directly."""

    def refresh_oauth(self) -> None:
        pass


_ROSTER_SPOTS = pd.DataFrame({
    "position": ["QB", "RB", "WR", "W/R/T", "K", "DEF", "BN", "IR"],
    "count": [1, 2, 2, 1, 1, 1, 5, 1],
})

_TEAMS = [{"name": "A", "team_key": "a"}, {"name": "B", "team_key": "b"}]


def _schedule(week: int = 1) -> pd.DataFrame:
    """DONE_TEAM's game already happened; LATE_TEAM's hasn't."""
    return pd.DataFrame({
        "season": [2026, 2026],
        "week": [week, week],
        "team": ["DONE_TEAM", "LATE_TEAM"],
        "opp_team": ["LATE_TEAM", "DONE_TEAM"],
        "date": [
            datetime.datetime.now() - datetime.timedelta(days=3),
            datetime.datetime.now() + datetime.timedelta(days=1),
        ],
        "implied_total": [22.0, 22.0],
        "opp_implied_total": [22.0, 22.0],
    })


def _neutral_matchup_model() -> MatchupModel:
    m = MatchupModel()
    m._implied_total_mean = 22.0
    m._implied_total_std = 5.0
    return m


def _optimizer() -> LineupOptimizer:
    return LineupOptimizer(_ROSTER_SPOTS, _TEAMS, _StubClient())


class TestHandleLiveWeekLineupStarterFlag:
    """Regression: a player whose game already finished and who was
    genuinely active (selected_position != BN) in the real platform
    lineup at fetch time must end up with starter=True. Before this fix,
    `started` players were only used to compute *remaining* roster
    capacity -- the starter flag itself was never set for them, so they
    silently fell back to the starter=False default despite being
    legitimately active. That broke every downstream consumer of the
    starter flag: live-week actual-score blending (League.
    _apply_live_week_actuals) and season_sims scoring both skip anyone
    with starter=False.
    """

    def _players(self) -> pd.DataFrame:
        # Two RB slots on team A: one already started in a finished game
        # (the bug -- this must end up starter=True), one still to be
        # decided from a not-yet-played game.
        return pd.DataFrame({
            "player_id_sr": ["rb_done_starter", "rb_bench_done", "rb_late"],
            "player_id": ["1", "2", "3"],
            "name": ["Done Starter", "Done Bench", "Late Guy"],
            "position": ["RB", "RB", "RB"],
            "current_team": ["DONE_TEAM", "DONE_TEAM", "LATE_TEAM"],
            "fantasy_team": ["A", "A", "A"],
            "selected_position": ["RB", "BN", "RB"],
            "points_rate": [15.0, 20.0, 10.0],
            "string": [1.0, 1.0, 1.0],
            "until": [None, None, None],
            "bye_week": [99, 99, 99],
        })

    def test_already_started_finished_game_player_is_marked_starter(self) -> None:
        players = self._players()
        out = _optimizer().set_optimal_lineup(
            players, week=1, season=2026, current_week=1, latest_season=2026,
            nfl_schedule=_schedule(), matchup_model=_neutral_matchup_model(),
        )
        row = out.set_index("player_id_sr").loc["rb_done_starter"]
        assert row["starter"] == True  # noqa: E712

    def test_benched_finished_game_player_stays_benched_even_if_higher_projected(
        self,
    ) -> None:
        # rb_bench_done projects higher (20.0) than the already-started
        # rb_done_starter (15.0), but their game is over and they were
        # not active -- a completed game can't be retroactively
        # re-optimized, so they must stay benched.
        players = self._players()
        out = _optimizer().set_optimal_lineup(
            players, week=1, season=2026, current_week=1, latest_season=2026,
            nfl_schedule=_schedule(), matchup_model=_neutral_matchup_model(),
        )
        row = out.set_index("player_id_sr").loc["rb_bench_done"]
        assert row["starter"] == False  # noqa: E712

    def test_remaining_slot_filled_from_not_yet_played_pool(self) -> None:
        # Only 1 of 2 RB slots is spoken for by the finished game (the
        # started player); the second RB slot should still be filled by
        # the not-yet-played player.
        players = self._players()
        out = _optimizer().set_optimal_lineup(
            players, week=1, season=2026, current_week=1, latest_season=2026,
            nfl_schedule=_schedule(), matchup_model=_neutral_matchup_model(),
        )
        row = out.set_index("player_id_sr").loc["rb_late"]
        assert row["starter"] == True  # noqa: E712

    def test_started_and_remaining_slot_both_counted_toward_position_quota(
        self,
    ) -> None:
        # Exactly 2 RBs should be starters total (the roster_spots RB
        # count), not 1 (missing the locked-in started player) or 3
        # (double-filling the slot the started player already occupies).
        players = self._players()
        out = _optimizer().set_optimal_lineup(
            players, week=1, season=2026, current_week=1, latest_season=2026,
            nfl_schedule=_schedule(), matchup_model=_neutral_matchup_model(),
        )
        assert out[out.position == "RB"].starter.sum() == 2
