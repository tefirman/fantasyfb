"""Tests for MoveAnalyzer.possible_pickups.

Regression coverage for a crash reported live: a healthy player (no
active injury, `until` is NaN/None) being considered for a drop raised
TypeError comparing None >= int, because the "is this player out through
the current week" check didn't guard against a null `until` the way the
free-agent-availability filter earlier in the same method already does.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb.analysis.move_analyzer import MoveAnalyzer


class _FakeClient:
    def refresh_oauth(self, threshold: int = 59) -> None:
        pass


class _FakeLeague:
    """Minimal League stand-in: just enough attributes/methods for
    MoveAnalyzer.possible_pickups to run without a real simulation.
    """

    def __init__(self, players: pd.DataFrame) -> None:
        self.players = players
        self.client = _FakeClient()
        self.season = 2026
        self.week = 3
        self.teams = [{"name": "MyTeam", "team_key": "t1"}]
        self.my_team_key = "t1"
        self.season_sims_calls = 0

    def season_sims(self, postseason=True, payouts=(800, 300, 100), fixed_winner=None):
        self.season_sims_calls += 1
        standings = pd.DataFrame({
            "team": ["MyTeam"],
            "wins_avg": [8.0], "wins_stdev": [1.0],
            "points_avg": [100.0], "points_stdev": [10.0],
            "per_game_avg": [100.0], "per_game_stdev": [10.0], "per_game_fano": [1.0],
            "playoffs": [0.5], "playoff_bye": [0.1],
            "winner": [0.1], "runner_up": [0.1], "third": [0.1], "earnings": [50.0],
        })
        return None, standings


def _players() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["Healthy Starter", "Free Agent One", "Free Agent Two"],
        "position": ["RB", "RB", "RB"],
        "fantasy_team": ["MyTeam", None, None],
        "until": [None, None, None],
        "pct_rostered": [1.0, 0.2, 0.1],
        "WAR": [2.0, 1.5, 0.5],
    })


class TestPossiblePickupsUntilHandling:
    def test_healthy_player_with_null_until_does_not_raise(self) -> None:
        # This is the exact crash: comparing None >= int for a player
        # with no active injury.
        league = _FakeLeague(_players())
        analyzer = MoveAnalyzer(league)
        result = analyzer.possible_pickups(verbose=False, min_rostership=0.0)
        assert isinstance(result, pd.DataFrame)

    def test_healthy_player_uses_war_gated_candidates(self) -> None:
        # A healthy player (until is null) should only be compared against
        # free agents within 0.5 WAR of them -- not treated as "any free
        # agent is an upgrade," which is reserved for players out through
        # the current week.
        players = _players()
        league = _FakeLeague(players)
        analyzer = MoveAnalyzer(league)
        result = analyzer.possible_pickups(
            verbose=False, min_rostership=0.0, limit_per=10,
        )
        # Healthy Starter has WAR 2.0; Free Agent Two (WAR 0.5) is more
        # than 0.5 below that and should be excluded as a pickup option.
        pairs = set(zip(result["player_to_drop"], result["player_to_add"]))
        assert ("Healthy Starter", "Free Agent Two") not in pairs
        assert ("Healthy Starter", "Free Agent One") in pairs

    def test_injured_player_through_current_week_allows_any_free_agent(self) -> None:
        players = _players()
        # until=5, current as_of%100 (week) is 3 -- injured through week 5,
        # i.e. still out this week (5 >= 3).
        players.loc[players.name == "Healthy Starter", "until"] = 5
        players.loc[players.name == "Healthy Starter", "WAR"] = 10.0
        league = _FakeLeague(players)
        analyzer = MoveAnalyzer(league)
        result = analyzer.possible_pickups(verbose=False, min_rostership=0.0)
        # Even the much-lower-WAR free agent should be considered, since
        # the injured player is contributing nothing regardless.
        pairs = set(zip(result["player_to_drop"], result["player_to_add"]))
        assert ("Healthy Starter", "Free Agent Two") in pairs
