"""End-to-end checks that the data layer wires up cleanly to the
downstream scoring + projection pipeline.

These guard against any column-rename or dtype regression in the provider
that wouldn't surface in unit-level provider tests but would silently
zero-out projections in production.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_scoring import FantasyScorer
from league_configs import apply_default_scoring_categories
from projection_engine import ProjectionEngine


PPR_HALF_SCORING = apply_default_scoring_categories({
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


@pytest.fixture(scope="module")
def scored(stats: pd.DataFrame) -> pd.DataFrame:
    return FantasyScorer(PPR_HALF_SCORING).calculate_points(stats)


@pytest.fixture(scope="module")
def merged(scored: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    return scored.merge(schedule, on=["season", "week", "team"], how="left")


class TestScoring:
    def test_points_column_added(self, scored: pd.DataFrame) -> None:
        assert "points" in scored.columns
        assert scored["points"].notna().all()


class TestScheduleJoin:
    def test_every_row_gets_elo_diff(self, merged: pd.DataFrame) -> None:
        # A failure here usually means the schedule team codes drifted
        # from the stats team codes -- the same regression class as the
        # team_aliases test, just observed downstream.
        assert merged["elo_diff"].notna().all()


class TestProjectionEngine:
    @pytest.fixture(scope="class")
    def projections(self, merged: pd.DataFrame) -> pd.DataFrame:
        df = merged.copy()
        df["string"] = 1.0
        weighting = pd.DataFrame([
            {"position": pos, "basal": 1.0, "opp_elo_weight": 0.05,
             "string_weight": 0.05, "time_scale": 0.01}
            for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]
        ])
        ref_games = {p: 16 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]}
        engine = ProjectionEngine(weighting_factors=weighting, reference_games=ref_games)
        earliest = {p: 202401 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]}
        return engine.calculate_projections(df, earliest, current_week=202405)

    def test_projections_produced(self, projections: pd.DataFrame) -> None:
        assert len(projections) > 0
        assert "points_rate" in projections.columns

    def test_known_top_qbs_appear(self, scored: pd.DataFrame) -> None:
        # Sanity check on the entire stats -> scoring pipeline. Through
        # 2024 W1-W4, multiple of these QBs were locked-in top-10 fantasy
        # scorers; if scoring or column wiring breaks, this will catch it.
        top_qbs = (
            scored[scored.position == "QB"]
            .groupby(["name"], as_index=False)["points"]
            .sum()
            .nlargest(10, "points")["name"]
            .tolist()
        )
        known = {"Lamar Jackson", "Jayden Daniels", "Baker Mayfield",
                 "Sam Darnold", "Josh Allen", "Patrick Mahomes"}
        assert len(known.intersection(top_qbs)) >= 3
