"""Tests for MatchupModel.

Covers the three signal components (implied total, opp-allowed-vs-pos,
depth-chart string), the position-aware sign flip for DEF, and the
DataFrame integration that lineup_optimizer will eventually use.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from matchup_model import MatchupModel, _PositionWeights


@pytest.fixture(scope="module")
def synthetic_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tiny league with three teams, three weeks, two QBs per team.

    DEF_BAD allows a lot of QB points; DEF_GOOD allows few. League average
    sits in between. Team `HIGH` plays in a 50-point game environment
    every week; team `LOW` plays in a 35-point one.
    """
    stats_rows = []
    for week in range(1, 4):
        for team, opp in [("HIGH", "BAD"), ("BAD", "HIGH"),
                          ("MID",  "GOOD"), ("GOOD", "MID")]:
            # One QB per team putting up 20 fantasy points, except we
            # double the points scored against BAD to make it a clearly
            # generous defense vs QBs.
            pts = 30.0 if opp == "BAD" else 18.0
            stats_rows.append({
                "player_id_sr": f"qb_{team}",
                "name": f"QB {team}",
                "position": "QB",
                "team": team,
                "opponent": opp,
                "season": 2024,
                "week": week,
                "points": pts,
            })
    stats = pd.DataFrame(stats_rows)

    sched_rows = []
    for week in range(1, 4):
        for team, opp, implied, opp_implied in [
            ("HIGH", "BAD",  28.0, 22.0),  # high-total game
            ("BAD",  "HIGH", 22.0, 28.0),
            ("MID",  "GOOD", 18.0, 17.0),  # low-total game
            ("GOOD", "MID",  17.0, 18.0),
        ]:
            sched_rows.append({
                "season": 2024, "week": week,
                "team": team, "opp_team": opp,
                "implied_total": implied,
                "opp_implied_total": opp_implied,
            })
    schedule = pd.DataFrame(sched_rows)
    return stats, schedule


class TestBaselineFitting:
    def test_implied_total_baseline_uses_schedule_stats(
        self, synthetic_history
    ) -> None:
        _, schedule = synthetic_history
        m = MatchupModel.from_history(
            stats_df=pd.DataFrame(columns=["opponent", "season", "week", "position", "points"]),
            schedule_df=schedule,
        )
        # Mean across [28, 22, 18, 17] x 3 weeks = 21.25.
        assert m._implied_total_mean == pytest.approx(21.25, abs=0.01)

    def test_allowed_table_built_per_team_position(
        self, synthetic_history
    ) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        # BAD should allow more QB points per game than GOOD does.
        bad_qb = m._allowed_table.query(
            "opponent == 'BAD' and position == 'QB'"
        ).iloc[0]["allowed_per_game"]
        good_qb = m._allowed_table.query(
            "opponent == 'GOOD' and position == 'QB'"
        ).iloc[0]["allowed_per_game"]
        assert bad_qb > good_qb


class TestFactorDirection:
    def test_high_implied_total_helps_offense(self, synthetic_history) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        high = m.factor("QB", team_implied_total=28.0,
                        opp_implied_total=22.0, opp_team="HIGH")
        low = m.factor("QB", team_implied_total=18.0,
                       opp_implied_total=17.0, opp_team="HIGH")
        assert high > low

    def test_high_opp_implied_total_hurts_defense(self, synthetic_history) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        # DEF facing a 28-pt-implied offense vs a 17-pt-implied offense.
        bad = m.factor("DEF", team_implied_total=22.0,
                       opp_implied_total=28.0, opp_team="HIGH")
        good = m.factor("DEF", team_implied_total=17.0,
                        opp_implied_total=17.0, opp_team="GOOD")
        assert bad < good

    def test_generous_opponent_helps_offense(self, synthetic_history) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        vs_bad = m.factor("QB", team_implied_total=21.25,
                          opp_implied_total=21.25, opp_team="BAD")
        vs_good = m.factor("QB", team_implied_total=21.25,
                           opp_implied_total=21.25, opp_team="GOOD")
        assert vs_bad > vs_good

    def test_neutral_matchup_yields_factor_one(self, synthetic_history) -> None:
        # Team sitting at league-avg implied total, opp at the league-avg
        # allowed rate, starter (string=1) -- the model should return 1.0
        # exactly for the volume*efficiency*matchup identity to hold.
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        # Fake an opp not in the allowed table so z_allowed defaults to 0.
        f = m.factor(
            "QB", team_implied_total=m._implied_total_mean,
            opp_implied_total=m._implied_total_mean,
            opp_team="UNKNOWN_TEAM", string=1.0,
        )
        assert f == pytest.approx(1.0)


class TestStringPenalty:
    def test_backup_gets_discount(self, synthetic_history) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        starter = m.factor("RB", 22.0, 22.0, "GOOD", string=1.0)
        backup = m.factor("RB", 22.0, 22.0, "GOOD", string=2.0)
        third = m.factor("RB", 22.0, 22.0, "GOOD", string=3.0)
        assert starter > backup > third

    def test_string_below_one_does_not_boost(self, synthetic_history) -> None:
        # Defensive guard against weird depth-chart data; the penalty
        # should only ever subtract, never add.
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        starter = m.factor("RB", 22.0, 22.0, "GOOD", string=1.0)
        weird = m.factor("RB", 22.0, 22.0, "GOOD", string=0.5)
        assert weird == starter


class TestApplyFactors:
    def test_attaches_matchup_factor_column(self, synthetic_history) -> None:
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        players = pd.DataFrame({
            "player_id_sr": ["qb_HIGH", "qb_GOOD"],
            "current_team": ["HIGH", "GOOD"],
            "position": ["QB", "QB"],
            "string": [1.0, 1.0],
        })
        out = m.apply_factors(players, schedule, as_of=202401)
        assert "matchup_factor" in out.columns
        # HIGH plays in the high-total game -> should beat GOOD.
        high_row = out[out.current_team == "HIGH"].iloc[0]
        good_row = out[out.current_team == "GOOD"].iloc[0]
        assert high_row["matchup_factor"] > good_row["matchup_factor"]

    def test_team_on_bye_gets_neutral_factor(self, synthetic_history) -> None:
        # A team that doesn't appear in the schedule for the requested
        # week (bye) should pass through with factor 1.0 rather than NaN.
        stats, schedule = synthetic_history
        m = MatchupModel.from_history(stats, schedule)
        players = pd.DataFrame({
            "player_id_sr": ["qb_BYE"],
            "current_team": ["TEAM_NOT_PLAYING"],
            "position": ["QB"],
            "string": [1.0],
        })
        out = m.apply_factors(players, schedule, as_of=202401)
        assert out.iloc[0]["matchup_factor"] == 1.0


class TestRealData2024:
    """Sanity checks against the live nflreadpy provider."""

    def test_high_total_game_lifts_qb_factor(
        self, provider, schedule
    ) -> None:
        from fantasy_scoring import FantasyScorer
        from league_configs import apply_default_scoring_categories

        scoring = apply_default_scoring_categories({
            "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
            "Rush Yds": 0.1, "Rush TD": 6,
            "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
        })
        stats = provider.get_player_stats(202401, 202412)
        scored = FantasyScorer(scoring).calculate_points(stats)
        m = MatchupModel.from_history(scored, schedule)

        # Find the highest implied-total team-game in 2024 W10.
        w10 = schedule[
            (schedule.season == 2024) & (schedule.week == 10)
        ].sort_values("implied_total", ascending=False)
        top = w10.iloc[0]
        # And a near-league-avg implied total entry for the same week.
        median = w10.iloc[len(w10) // 2]

        f_top = m.factor("QB",
                         team_implied_total=top["implied_total"],
                         opp_implied_total=top["opp_implied_total"],
                         opp_team=top["opp_team"])
        f_med = m.factor("QB",
                         team_implied_total=median["implied_total"],
                         opp_implied_total=median["opp_implied_total"],
                         opp_team=median["opp_team"])
        assert f_top > f_med > 0.8
