"""Tests for League.get_rates() de-duplication.

Regression coverage for issue #7: a duplicate (player_id_sr, position)
in self.players survived the inner drop_duplicates() (which had no
subset=) and the right-merge then emitted two output rows for the same
logical player. The downstream effects ranged from off-by-one
replacement levels to a player being drafted twice in a single
MockDraft. The fix narrows drop_duplicates() to the merge key so the
output is one row per (player_id_sr, position).

These tests bypass __init__ via __new__ so they don't need Yahoo
credentials -- get_rates() with reload=False only reads the attributes
seeded below.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb import League
from fantasyfb.scoring.fantasy_scoring import FantasyScorer
from fantasyfb.configs import apply_default_scoring_categories


SCORING = apply_default_scoring_categories({
    "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
    "Rush Yds": 0.1, "Rush TD": 6,
    "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
    "Fum Lost": -2,
    "Sack": 1, "Int": 2, "Fum Rec": 2, "Ret TD": 6,
    "Pts Allow 0": 10, "Pts Allow 1-6": 7, "Pts Allow 7-13": 4,
    "Pts Allow 14-20": 1, "Pts Allow 21-27": 0,
    "Pts Allow 28-34": -1, "Pts Allow 35+": -4,
    "PAT Made": 1, "FG 0-19": 3, "FG 20-29": 3, "FG 30-39": 3,
    "FG 40-49": 4, "FG 50+": 5,
})


_id_counter = 0


def _build_players_row(player_id_sr: str, position: str, **overrides) -> dict:
    global _id_counter
    _id_counter += 1
    base = {
        "player_id_sr": player_id_sr,
        "player_id": _id_counter,
        "name": player_id_sr,
        "status": "",
        "fantasy_team": None,
        "current_team": "PIT",
        "position": position,
        "string": 1.0,
        "until": None,
        "bye_week": 9,
        "pct_rostered": 0.0,
        "selected_position": "BN",
    }
    base.update(overrides)
    return base


@pytest.fixture
def league(stats: pd.DataFrame, schedule: pd.DataFrame, rosters: pd.DataFrame, team_aliases: pd.DataFrame) -> League:
    """Minimal League with just the attributes get_rates(reload=False) reads."""
    lg = League.__new__(League)
    lg.season = 2024
    lg.week = 5
    lg.earliest = {p: 202401 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]}
    lg.stats = FantasyScorer(SCORING).calculate_points(stats)
    lg.nfl_schedule = schedule
    lg.nfl_rosters = rosters
    lg.nfl_teams = team_aliases
    return lg


def _pick_real_player(stats: pd.DataFrame, position: str) -> str:
    """Grab a player_id_sr we know shows up in stats so the projection-side
    of the merge has a non-null row to duplicate against."""
    return stats.loc[stats["position"] == position, "player_id_sr"].iloc[0]


class TestGetRatesDeduplication:
    def test_duplicate_player_collapses_to_one_row(
        self, league: League, stats: pd.DataFrame
    ) -> None:
        # Same (player_id_sr, position), different `string` and
        # `selected_position` -- the exact shape that defeated the
        # subset-less drop_duplicates() before the fix.
        pid = _pick_real_player(stats, "RB")
        league.players = pd.DataFrame([
            _build_players_row(pid, "RB", string=1.0, selected_position="BN"),
            _build_players_row(pid, "RB", string=2.0, selected_position="RB"),
        ])

        league.get_rates(reload=False)

        matched = league.players[league.players["player_id_sr"] == pid]
        assert len(matched) == 1, (
            f"Expected exactly one row for {pid}, got {len(matched)}"
        )

    def test_no_duplicates_across_full_output(
        self, league: League, stats: pd.DataFrame
    ) -> None:
        # Mix of clean rows and a duplicated one -- guards against the fix
        # accidentally collapsing distinct players too.
        rb_pid = _pick_real_player(stats, "RB")
        wr_pid = _pick_real_player(stats, "WR")
        qb_pid = _pick_real_player(stats, "QB")
        league.players = pd.DataFrame([
            _build_players_row(rb_pid, "RB", string=1.0),
            _build_players_row(rb_pid, "RB", string=3.0, current_team="DAL"),
            _build_players_row(wr_pid, "WR"),
            _build_players_row(qb_pid, "QB"),
        ])

        league.get_rates(reload=False)

        real = league.players[
            ~league.players["player_id_sr"].astype(str).str.startswith("avg_")
        ]
        dupes = real[real.duplicated(subset=["player_id_sr", "position"], keep=False)]
        assert dupes.empty, f"Unexpected duplicates: {dupes['player_id_sr'].tolist()}"

    def test_keep_last_wins_on_conflict(
        self, league: League, stats: pd.DataFrame
    ) -> None:
        # The fix uses keep="last" because later rows reflect more recent
        # state (post-trade team affiliation, depth-chart promotions).
        # Without that pin the merge could silently start preferring stale
        # rows after a pandas upgrade.
        pid = _pick_real_player(stats, "WR")
        league.players = pd.DataFrame([
            _build_players_row(pid, "WR", current_team="OLD", string=3.0),
            _build_players_row(pid, "WR", current_team="NEW", string=1.0),
        ])

        league.get_rates(reload=False)

        row = league.players[league.players["player_id_sr"] == pid].iloc[0]
        assert row["current_team"] == "NEW"
        assert row["string"] == 1.0
