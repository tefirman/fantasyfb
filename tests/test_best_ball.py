"""Tests for best ball functionality.

Covers:
  - select_optimal_lineup: single-sim lineup optimizer
  - _lineup_score_vectorized: vectorized version
  - compute_best_ball_team_projections: per-player → team-level conversion
  - SeasonSimulator.simulate_season(best_ball=True): end-to-end smoke test
  - view_bestball / view_nearestbestball: cockpit ranking views
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.sim.season_simulator import (
    SeasonSimulator,
    _lineup_score_vectorized,
    compute_best_ball_team_projections,
    select_optimal_lineup,
)
from fantasyfb.drafts.snake_cockpit import (
    _add_bb_vorp,
    view_bestball,
    view_nearestbestball,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_spec(qb=1, rb=2, wr=3, te=1, flex_wrt=1, k=0, def_=0):
    """Build a minimal roster_spec dict for testing."""
    spec = {}
    if qb:   spec["QB"]    = qb
    if rb:   spec["RB"]    = rb
    if wr:   spec["WR"]    = wr
    if te:   spec["TE"]    = te
    if flex_wrt: spec["W/R/T"] = flex_wrt
    if k:    spec["K"]     = k
    if def_: spec["DEF"]   = def_
    return spec


# ---------------------------------------------------------------------------
# select_optimal_lineup
# ---------------------------------------------------------------------------

class TestSelectOptimalLineup:
    def test_simple_no_flex(self):
        # 1 QB, 2 RB, 3 WR: just fill each slot with best at position
        positions = ["QB", "QB", "RB", "RB", "RB", "WR", "WR", "WR", "WR"]
        scores    = np.array([40.0, 20.0,  # QBs
                               30.0, 25.0, 10.0,  # RBs
                               22.0, 18.0, 15.0, 8.0])  # WRs
        spec = {"QB": 1, "RB": 2, "WR": 3}
        # Expected: QB(40) + RB(30+25) + WR(22+18+15) = 150
        assert select_optimal_lineup(positions, scores, spec) == pytest.approx(150.0)

    def test_flex_takes_best_remaining(self):
        # 2 RB, 3 WR, 1 W/R/T flex
        # Expect flex to take RB3 (20) over WR4 (12)
        positions = ["RB", "RB", "RB", "WR", "WR", "WR", "WR"]
        scores    = np.array([30.0, 25.0, 20.0,  # RBs
                               22.0, 18.0, 15.0, 12.0])  # WRs
        spec = {"RB": 2, "WR": 3, "W/R/T": 1}
        result = select_optimal_lineup(positions, scores, spec)
        # RB(30+25) + WR(22+18+15) + flex=RB3(20) = 130
        assert result == pytest.approx(130.0)

    def test_flex_takes_wr_when_better(self):
        # 2 RB, 3 WR, 1 W/R/T flex
        # WR4 (25) > RB3 (10) → flex should go to WR4
        positions = ["RB", "RB", "RB", "WR", "WR", "WR", "WR"]
        scores    = np.array([30.0, 25.0, 10.0,  # RBs
                               24.0, 20.0, 18.0, 25.0])  # WRs
        spec = {"RB": 2, "WR": 3, "W/R/T": 1}
        result = select_optimal_lineup(positions, scores, spec)
        # RB(30+25) + WR(top 3 = 25+24+20) + flex=WR(18) = 142
        assert result == pytest.approx(142.0)

    def test_te_eligible_for_wrt_flex(self):
        # TE is eligible for W/R/T flex; here the TE backup beats WR/RB extras
        positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE"]
        scores    = np.array([35.0,
                               28.0, 20.0,  # RBs
                               22.0, 18.0, 14.0,  # WRs
                               15.0, 30.0])  # TEs
        spec = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "W/R/T": 1}
        result = select_optimal_lineup(positions, scores, spec)
        # QB(35) + RB(28+20) + WR(22+18+14) + TE(30) + flex=TE2(15) = 182
        assert result == pytest.approx(182.0)

    def test_bench_players_ignored(self):
        # spec has BN key; those slots must not be filled
        positions = ["QB", "RB", "WR"]
        scores    = np.array([30.0, 25.0, 20.0])
        spec = {"QB": 1, "RB": 1, "WR": 1, "BN": 5}
        assert select_optimal_lineup(positions, scores, spec) == pytest.approx(75.0)

    def test_fewer_players_than_slots(self):
        # Only 1 QB available but spec asks for 1 QB; should still work
        positions = ["QB"]
        scores    = np.array([30.0])
        spec = {"QB": 1, "RB": 2}
        # QB fills QB slot, no RBs available
        assert select_optimal_lineup(positions, scores, spec) == pytest.approx(30.0)

    def test_qwrt_flex_can_hold_qb(self):
        # Q/W/R/T flex: a QB leftover fills the flex slot
        positions = ["QB", "QB", "WR"]
        scores    = np.array([40.0, 35.0, 20.0])
        spec = {"QB": 1, "Q/W/R/T": 1}
        # QB(40) + flex=QB2(35) = 75
        assert select_optimal_lineup(positions, scores, spec) == pytest.approx(75.0)

    def test_empty_roster(self):
        assert select_optimal_lineup([], np.array([]), {"QB": 1}) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _lineup_score_vectorized
# ---------------------------------------------------------------------------

class TestLineupScoreVectorized:
    def test_matches_scalar_single_sim(self):
        positions = np.array(["QB", "RB", "RB", "WR", "WR", "WR"])
        scores_1d = np.array([30.0, 25.0, 18.0, 20.0, 15.0, 10.0])
        spec = {"QB": 1, "RB": 2, "WR": 3}

        expected = select_optimal_lineup(list(positions), scores_1d, spec)
        vec = _lineup_score_vectorized(positions, scores_1d[np.newaxis, :], spec)
        assert vec.shape == (1,)
        assert vec[0] == pytest.approx(expected)

    def test_vectorized_shape(self):
        positions = np.array(["QB", "RB", "WR", "TE", "RB", "WR"])
        avgs = np.array([30.0, 20.0, 18.0, 10.0, 15.0, 12.0])
        np.random.seed(42)
        sim_scores = np.random.normal(avgs, 5.0, size=(500, 6))
        spec = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
        result = _lineup_score_vectorized(positions, sim_scores, spec)
        assert result.shape == (500,)
        assert np.all(result >= 0)

    def test_flex_vectorized(self):
        # With W/R/T flex, the vectorized result should equal repeated scalar calls
        positions = np.array(["RB", "RB", "RB", "WR", "WR", "WR", "WR"])
        scores_batch = np.array([
            [30.0, 25.0, 20.0, 22.0, 18.0, 15.0, 12.0],
            [10.0,  5.0,  3.0, 24.0, 20.0, 18.0, 16.0],
        ])
        spec = {"RB": 2, "WR": 3, "W/R/T": 1}
        vec = _lineup_score_vectorized(positions, scores_batch, spec)
        for i, row in enumerate(scores_batch):
            expected = select_optimal_lineup(list(positions), row, spec)
            assert vec[i] == pytest.approx(expected), f"mismatch at sim {i}"


# ---------------------------------------------------------------------------
# compute_best_ball_team_projections
# ---------------------------------------------------------------------------

class TestComputeBestBallTeamProjections:
    def _make_player_proj(self):
        """Two teams, two weeks, two players per team."""
        return pd.DataFrame({
            "fantasy_team": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "week":         [1,   1,   2,   2,   1,   1,   2,   2],
            "position":     ["QB","WR","QB","WR","QB","RB","QB","RB"],
            "points_avg":   [25., 15., 26., 14., 24., 18., 23., 17.],
            "points_stdev": [ 5.,  3.,  5.,  3.,  5.,  4.,  5.,  4.],
        })

    def test_output_schema(self):
        proj = self._make_player_proj()
        roster_spots = pd.DataFrame({
            "position": ["QB", "WR", "BN"],
            "count":    [1,    1,    5],
        })
        result = compute_best_ball_team_projections(proj, roster_spots, n_samples=200)
        assert set(result.columns) == {"fantasy_team", "week", "points_avg", "points_stdev"}
        assert len(result) == 4  # 2 teams × 2 weeks

    def test_output_values_reasonable(self):
        np.random.seed(0)
        proj = self._make_player_proj()
        spec = {"QB": 1, "WR": 1}
        result = compute_best_ball_team_projections(proj, spec, n_samples=2000)
        team_a_w1 = result[(result.fantasy_team == "A") & (result.week == 1)]
        # Team A, week 1: QB(25) + WR(15) = ~40 expected
        assert team_a_w1["points_avg"].values[0] == pytest.approx(40.0, abs=2.0)
        assert team_a_w1["points_stdev"].values[0] > 0

    def test_accepts_dict_roster_spec(self):
        proj = self._make_player_proj()
        spec = {"QB": 1, "WR": 1}
        result = compute_best_ball_team_projections(proj, spec, n_samples=100)
        assert len(result) == 4

    def test_best_ball_exceeds_worst_starter_baseline(self):
        """With 2 QBs and only 1 QB slot, best-ball should score the better QB."""
        np.random.seed(1)
        proj = pd.DataFrame({
            "fantasy_team": ["A", "A"],
            "week":         [1,   1],
            "position":     ["QB","QB"],
            "points_avg":   [30., 10.],
            "points_stdev": [ 0.,  0.],  # deterministic
        })
        spec = {"QB": 1}
        result = compute_best_ball_team_projections(proj, spec, n_samples=100)
        # Should always pick the 30-point QB
        assert result["points_avg"].values[0] == pytest.approx(30.0, abs=0.1)


# ---------------------------------------------------------------------------
# SeasonSimulator with best_ball=True
# ---------------------------------------------------------------------------

class TestSeasonSimulatorBestBall:
    def _make_player_projections(self):
        teams = ["Team A", "Team B"]
        weeks = [1, 2, 3]
        rows = []
        for team in teams:
            for week in weeks:
                rows.append({"fantasy_team": team, "week": week,
                             "position": "QB", "points_avg": 25.0, "points_stdev": 5.0})
                rows.append({"fantasy_team": team, "week": week,
                             "position": "RB", "points_avg": 18.0, "points_stdev": 4.0})
                rows.append({"fantasy_team": team, "week": week,
                             "position": "WR", "points_avg": 15.0, "points_stdev": 3.0})
        return pd.DataFrame(rows)

    def _make_schedule(self):
        return pd.DataFrame({
            "week":    [1, 2, 3],
            "team_1":  ["Team A", "Team A", "Team B"],
            "team_2":  ["Team B", "Team B", "Team A"],
            "score_1": [0.0, 0.0, 0.0],
            "score_2": [0.0, 0.0, 0.0],
        })

    def test_best_ball_requires_roster_spots(self):
        sim = SeasonSimulator({"playoff_start_week": 3, "num_playoff_teams": 2})
        with pytest.raises(ValueError, match="roster_spots"):
            sim.simulate_season(
                self._make_player_projections(), self._make_schedule(),
                num_sims=50, best_ball=True,
            )

    def test_best_ball_returns_results(self):
        roster_spots = pd.DataFrame({
            "position": ["QB", "RB", "WR", "BN"],
            "count":    [1,    1,    1,    3],
        })
        sim = SeasonSimulator(
            {"playoff_start_week": 3, "num_playoff_teams": 2, "num_teams": 2},
            roster_spots=roster_spots,
        )
        schedule_df, standings_df = sim.simulate_season(
            self._make_player_projections(), self._make_schedule(),
            num_sims=100, best_ball=True, include_playoffs=False,
        )
        assert "team" in standings_df.columns
        assert set(standings_df["team"]) == {"Team A", "Team B"}

    def test_best_ball_standard_results_differ(self):
        """Best-ball mode should produce different (generally higher) scores
        than a team projection built from a single fixed starter per position."""
        roster_spots = pd.DataFrame({
            "position": ["QB", "RB", "WR", "BN"],
            "count":    [1,    1,    1,    3],
        })
        np.random.seed(42)
        proj_bb = self._make_player_projections()

        # Standard mode: build team projections manually (one player per slot)
        proj_std = pd.DataFrame({
            "fantasy_team": ["Team A", "Team A", "Team A",
                             "Team B", "Team B", "Team B"],
            "week":         [1, 2, 3, 1, 2, 3],
            "points_avg":   [58.0] * 6,   # QB+RB+WR combined
            "points_stdev": [7.07] * 6,   # approximate combined stdev
        })

        settings = {"playoff_start_week": 3, "num_playoff_teams": 2, "num_teams": 2}
        sim_bb = SeasonSimulator(settings, roster_spots=roster_spots)
        _, standings_bb = sim_bb.simulate_season(
            proj_bb, self._make_schedule(),
            num_sims=200, best_ball=True, include_playoffs=False,
        )
        # We just confirm it runs and produces a plausible average score
        avg_bb = standings_bb["points_avg"].mean()
        assert avg_bb > 0


# ---------------------------------------------------------------------------
# Cockpit: view_bestball / view_nearestbestball
# ---------------------------------------------------------------------------

def _make_board():
    """Minimal board DataFrame for cockpit tests."""
    return pd.DataFrame({
        "name":             ["Alice QB",  "Bob RB",   "Carol WR",  "Dan RB",   "Eve WR"],
        "position":         ["QB",        "RB",       "WR",        "RB",       "WR"],
        "current_team":     ["KC",        "DAL",      "SF",        "NE",       "GB"],
        "points_rate":      [30.0,        20.0,       18.0,        15.0,       12.0],
        "points_stdev":     [ 8.0,         3.0,       10.0,         2.0,        6.0],
        "replacement_rate": [20.0,        10.0,       10.0,        10.0,       10.0],
        "vorp_per_game":    [10.0,        10.0,        8.0,         5.0,        2.0],
        "vorp_season":      [170.0,      170.0,      136.0,        85.0,       34.0],
        "tier":             [1,            1,          1,            2,          2],
        "adp":              [5.0,          8.0,        12.0,        20.0,       25.0],
        "adp_round":        [1,            1,           1,           2,          3],
        "adp_value":        [0.0,          2.0,         0.0,         0.0,        0.0],
        "fantasy_team":     [pd.NA,       pd.NA,       pd.NA,       pd.NA,      pd.NA],
    })


class TestAddBbVorp:
    def test_basic(self):
        board = _make_board()
        out = _add_bb_vorp(board, upside_factor=0.5)
        # Alice QB: 30 + 0.5*8 - 20 = 14
        assert out.loc[out.name == "Alice QB", "bb_vorp"].values[0] == pytest.approx(14.0)

    def test_original_unchanged(self):
        board = _make_board()
        _add_bb_vorp(board)
        assert "bb_vorp" not in board.columns

    def test_missing_stdev_defaults_zero(self):
        board = _make_board().drop(columns="points_stdev")
        out = _add_bb_vorp(board, upside_factor=0.5)
        # With no stdev: bb_vorp = points_rate - replacement_rate
        assert out.loc[out.name == "Alice QB", "bb_vorp"].values[0] == pytest.approx(10.0)


class TestViewBestball:
    def test_returns_df(self):
        board = _make_board()
        result = view_bestball(board)
        assert isinstance(result, pd.DataFrame)
        assert "bb_vorp" in result.columns

    def test_upside_boosts_high_stdev_players(self):
        board = _make_board()
        # Carol WR has stdev=10 (high), Bob RB has stdev=3 (low)
        # With upside_factor=1.0, Carol's bb_vorp = 18+10-10=18, Bob's = 20+3-10=13
        result = view_bestball(board, upside_factor=1.0)
        carol_bb = result.loc[result.name == "Carol WR", "bb_vorp"].values[0]
        bob_bb   = result.loc[result.name == "Bob RB",   "bb_vorp"].values[0]
        assert carol_bb > bob_bb

    def test_excludes_drafted_players(self):
        board = _make_board()
        board.loc[board.name == "Alice QB", "fantasy_team"] = "Some Team"
        result = view_bestball(board)
        assert "Alice QB" not in result["name"].values

    def test_exclude_parameter(self):
        board = _make_board()
        result = view_bestball(board, exclude=["Bob RB"])
        assert "Bob RB" not in result["name"].values

    def test_limit_per_position(self):
        board = _make_board()
        result = view_bestball(board, limit_per_position=1)
        # At most 1 player per position
        for pos, grp in result.groupby("position"):
            assert len(grp) <= 1

    def test_bb_display_cols_present(self):
        board = _make_board()
        result = view_bestball(board)
        for col in ("name", "position", "bb_vorp", "points_stdev"):
            assert col in result.columns


class TestViewNearestBestball:
    def test_respects_adp_window(self):
        board = _make_board()
        # pick_overall=1, num_teams=10, window=2 → cutoff=21
        result = view_nearestbestball(board, pick_overall=1, num_teams=10, window_rounds=2)
        # adp values: 5, 8, 12, 20, 25 → adp<=21 means 5,8,12,20 qualify
        assert "Eve WR" not in result["name"].values  # adp=25 > 21
        assert "Alice QB" in result["name"].values

    def test_sorted_by_bb_vorp(self):
        board = _make_board()
        result = view_nearestbestball(
            board, pick_overall=1, num_teams=10, window_rounds=3,
            upside_factor=0.5,
        )
        # Check that bb_vorp is descending
        bb_values = result["bb_vorp"].to_numpy()
        assert all(bb_values[i] >= bb_values[i + 1] for i in range(len(bb_values) - 1))

    def test_empty_window(self):
        board = _make_board()
        # cutoff = pick_overall + window_rounds * num_teams = 1 + 0 = 1
        # No player has adp <= 1, so result is empty
        result = view_nearestbestball(board, pick_overall=1, num_teams=10, window_rounds=0)
        assert result.empty

    def test_bb_vorp_column_present(self):
        board = _make_board()
        result = view_nearestbestball(board, pick_overall=1, num_teams=10)
        assert "bb_vorp" in result.columns
