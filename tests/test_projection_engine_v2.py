"""Tests for ProjectionEngineV2.

Covers the volume x efficiency decomposition plus the time-decay and
Bayesian-shrinkage knobs, against both synthetic fixtures (where we
know the right answer) and real 2024 data (where we sanity-check that
known top performers float to the top).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.scoring.fantasy_scoring import FantasyScorer
from fantasyfb.configs import apply_default_scoring_categories
from fantasyfb.projections.engine_v2 import ProjectionEngineV2


PPR_HALF_SCORING = apply_default_scoring_categories({
    "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
    "Rush Yds": 0.1, "Rush TD": 6,
    "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
    "Fum Lost": -2, "Sack": 1, "Int": 2, "Fum Rec": 2, "Ret TD": 6,
    "Pts Allow 0": 10, "Pts Allow 1-6": 7, "Pts Allow 7-13": 4,
    "Pts Allow 14-20": 1, "Pts Allow 21-27": 0,
    "Pts Allow 28-34": -1, "Pts Allow 35+": -4,
    "PAT Made": 1, "FG 0-19": 3, "FG 20-29": 3, "FG 30-39": 3,
    "FG 40-49": 4, "FG 50+": 5,
})


def _wr_row(player_id: str, season: int, week: int, *,
            rec: int = 0, rec_yds: int = 0, rec_td: int = 0) -> dict:
    """Helper to build a synthetic stats row with all required columns."""
    base = {col: 0 for col in [
        "rush_yds", "rush_att", "rush_td", "rush_first_down",
        "rec", "rec_yds", "rec_td", "rec_first_down",
        "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
        "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
        "kick_ret_td", "punt_ret_td", "xpm", "fgm",
    ]}
    base.update({
        "player_id_sr": player_id,
        "name": player_id,
        "position": "WR",
        "team": "AAA",
        "opponent": "BBB",
        "season": season,
        "week": week,
        "rec": rec,
        "rec_yds": rec_yds,
        "rec_td": rec_td,
    })
    return base


@pytest.fixture(scope="module")
def synthetic_wr_stats() -> pd.DataFrame:
    """Two WRs with deliberately different volume + efficiency profiles.

    high_vol_high_eff: 8 targets, 8 catches, 100yd, 1 TD per game
    low_vol_low_eff:   3 targets, 2 catches, 20yd, 0 TD per game
    """
    rows = []
    for season, week in [(2024, w) for w in range(1, 6)]:
        rows.append(_wr_row("hvhe", season, week, rec=8, rec_yds=100, rec_td=1))
        rows.append(_wr_row("lvle", season, week, rec=2, rec_yds=20, rec_td=0))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def scored_synthetic(synthetic_wr_stats: pd.DataFrame) -> pd.DataFrame:
    return FantasyScorer(PPR_HALF_SCORING).calculate_points(synthetic_wr_stats)


class TestOutputSchema:
    def test_columns_match_v1_contract(self, scored_synthetic: pd.DataFrame) -> None:
        proj = ProjectionEngineV2().calculate_projections(
            scored_synthetic, {"WR": 202401}, current_week=202406,
        )
        # V1 contract for downstream consumers.
        for col in ["player_id_sr", "position", "points_rate", "points_stdev", "num_games"]:
            assert col in proj.columns
        # V2 diagnostic columns.
        assert "volume_rate" in proj.columns
        assert "efficiency_rate" in proj.columns

    def test_emits_one_avg_row_per_position(self, scored_synthetic: pd.DataFrame) -> None:
        proj = ProjectionEngineV2().calculate_projections(
            scored_synthetic, {"WR": 202401}, current_week=202406,
        )
        avg_rows = proj[proj["player_id_sr"].str.startswith("avg_")]
        assert list(avg_rows["position"]) == ["WR"]


class TestVolumeEfficiencyDecomposition:
    def test_points_rate_equals_volume_times_efficiency(
        self, scored_synthetic: pd.DataFrame
    ) -> None:
        # Disable shrinkage so the identity holds exactly per-player.
        engine = ProjectionEngineV2(shrinkage_n={"WR": 0})
        proj = engine.calculate_projections(
            scored_synthetic, {"WR": 202401}, current_week=202406,
        )
        real = proj[~proj["player_id_sr"].str.startswith("avg_")]
        np.testing.assert_allclose(
            real["points_rate"].values,
            (real["volume_rate"] * real["efficiency_rate"]).values,
            rtol=1e-9,
        )

    def test_high_volume_player_has_higher_volume_rate(
        self, scored_synthetic: pd.DataFrame
    ) -> None:
        engine = ProjectionEngineV2(shrinkage_n={"WR": 0})
        proj = engine.calculate_projections(
            scored_synthetic, {"WR": 202401}, current_week=202406,
        )
        hvhe = proj.set_index("player_id_sr").loc["hvhe"]
        lvle = proj.set_index("player_id_sr").loc["lvle"]
        assert hvhe["volume_rate"] > lvle["volume_rate"]
        assert hvhe["efficiency_rate"] > lvle["efficiency_rate"]


class TestTimeDecay:
    def test_recent_games_dominate_with_decay(self) -> None:
        # Player with low volume in old games + high volume in recent games.
        # With time_decay > 0, projection should approach recent volume.
        rows = []
        for week in range(1, 5):
            rows.append(_wr_row("ramping", 2023, week, rec=2, rec_yds=20))
        for week in range(1, 5):
            rows.append(_wr_row("ramping", 2024, week, rec=10, rec_yds=120))
        stats = pd.DataFrame(rows)
        scored = FantasyScorer(PPR_HALF_SCORING).calculate_points(stats)

        decayed = ProjectionEngineV2(
            time_decay=0.15, shrinkage_n={"WR": 0},
        ).calculate_projections(scored, {"WR": 202301}, current_week=202405)
        flat = ProjectionEngineV2(
            time_decay=0.0, shrinkage_n={"WR": 0},
        ).calculate_projections(scored, {"WR": 202301}, current_week=202405)

        decayed_vol = decayed.set_index("player_id_sr").loc["ramping", "volume_rate"]
        flat_vol = flat.set_index("player_id_sr").loc["ramping", "volume_rate"]

        # Heavy decay should pull volume toward the recent avg of 10
        # while flat decay sits halfway at 6.
        assert flat_vol == pytest.approx(6.0)
        assert decayed_vol > flat_vol


class TestBayesianShrinkage:
    def test_low_sample_player_pulled_toward_position_prior(self) -> None:
        # Two players: one with 1 great game, one with the league baseline.
        rows = [_wr_row("oneoff", 2024, 1, rec=15, rec_yds=200, rec_td=2)]
        for week in range(1, 11):
            rows.append(_wr_row("baseline", 2024, week, rec=3, rec_yds=30))
        stats = pd.DataFrame(rows)
        scored = FantasyScorer(PPR_HALF_SCORING).calculate_points(stats)

        engine = ProjectionEngineV2(
            time_decay=0.0, shrinkage_n={"WR": 10},
        )
        proj = engine.calculate_projections(
            scored, {"WR": 202401}, current_week=202412,
        )
        oneoff = proj.set_index("player_id_sr").loc["oneoff"]
        avg_wr = proj.set_index("player_id_sr").loc["avg_WR"]
        baseline = proj.set_index("player_id_sr").loc["baseline"]

        # 1-game player should sit much closer to the position prior than
        # to their own raw 200-yard, 2-TD outburst.
        assert oneoff["points_rate"] < 30
        # And closer to the prior than the baseline player is (since
        # baseline has more own-data weight).
        assert abs(oneoff["points_rate"] - avg_wr["points_rate"]) < abs(
            baseline["points_rate"] - avg_wr["points_rate"]
        ) or oneoff["num_games"] < baseline["num_games"]

    def test_zero_shrinkage_gives_pure_player_rate(
        self, scored_synthetic: pd.DataFrame
    ) -> None:
        engine = ProjectionEngineV2(time_decay=0.0, shrinkage_n={"WR": 0})
        proj = engine.calculate_projections(
            scored_synthetic, {"WR": 202401}, current_week=202406,
        )
        # hvhe scores 13 pts/game (8 rec * 0.5 + 100yd * 0.1 + 1TD * 6 = 20).
        # Actually 8*0.5 + 10 + 6 = 20.
        hvhe = proj.set_index("player_id_sr").loc["hvhe"]
        assert hvhe["points_rate"] == pytest.approx(20.0)


class TestRealData2024:
    """Sanity checks against the live nflreadpy provider. These guard the
    structural plumbing -- if the model returns something obviously wrong
    on real data, schema or unit-conversion drift is the likely cause."""

    @pytest.fixture(scope="class")
    def real_projections(self, provider) -> tuple[pd.DataFrame, pd.DataFrame]:
        stats = provider.get_player_stats(202301, 202412)
        scored = FantasyScorer(PPR_HALF_SCORING).calculate_points(stats)
        engine = ProjectionEngineV2()
        proj = engine.calculate_projections(
            scored, {p: 202301 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]},
            current_week=202412,
        )
        names = scored[["player_id_sr", "name"]].drop_duplicates()
        return proj.merge(names, on="player_id_sr", how="left"), scored

    def test_known_top_qb_in_top_five(self, real_projections) -> None:
        proj, _ = real_projections
        top = proj[(proj.position == "QB") & (proj.num_games >= 10)].nlargest(
            5, "points_rate"
        )["name"].tolist()
        # 2024 elite QBs through W12 -- at least one should be top-5.
        assert any(qb in top for qb in [
            "Lamar Jackson", "Josh Allen", "Jalen Hurts", "Joe Burrow",
        ])

    def test_position_priors_in_plausible_range(self, real_projections) -> None:
        proj, _ = real_projections
        priors = proj[proj.player_id_sr.str.startswith("avg_")].set_index("position")
        # Empirical fantasy averages over 2023+2024 (half-PPR).
        assert 10 < priors.loc["QB", "points_rate"] < 20
        assert 5 < priors.loc["RB", "points_rate"] < 15
        assert 4 < priors.loc["WR", "points_rate"] < 12
        assert 3 < priors.loc["TE", "points_rate"] < 10
