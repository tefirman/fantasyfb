"""Tests for the V1 vs V2 backtest harness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.sim.backtest import evaluate, run_backtest


class TestEvaluate:
    def test_columns_present(self) -> None:
        preds = pd.DataFrame({
            "variant": ["V2_neutral"] * 4,
            "position": ["QB", "QB", "RB", "RB"],
            "prediction": [20.0, 18.0, 12.0, 14.0],
            "actual":     [22.0, 16.0, 10.0, 18.0],
            "player_id_sr": ["a", "b", "c", "d"],
            "season": [2024]*4, "week": [5]*4,
        })
        summary = evaluate(preds)
        for col in ["variant", "position", "n", "mae", "rmse"]:
            assert col in summary.columns

    def test_mae_and_rmse_match_hand_calc(self) -> None:
        preds = pd.DataFrame({
            "variant": ["V"] * 3,
            "position": ["QB"] * 3,
            "prediction": [10.0, 20.0, 30.0],
            "actual":     [12.0, 18.0, 35.0],
            "player_id_sr": ["a", "b", "c"],
            "season": [2024]*3, "week": [1]*3,
        })
        summary = evaluate(preds).iloc[0]
        # Errors: 2, 2, 5 -> MAE = 3, RMSE = sqrt((4+4+25)/3) = sqrt(11)
        assert summary["mae"] == pytest.approx(3.0)
        assert summary["rmse"] == pytest.approx(np.sqrt(11.0))

    def test_empty_input_returns_empty_summary(self) -> None:
        empty = pd.DataFrame(columns=[
            "variant", "position", "prediction", "actual",
            "player_id_sr", "season", "week",
        ])
        summary = evaluate(empty)
        assert summary.empty
        assert list(summary.columns) == ["variant", "position", "n", "mae", "rmse"]


class TestRunBacktest:
    """End-to-end check on the live provider; one test week to keep
    runtime sane (the harness runs V1 + four V2 variants per week)."""

    @pytest.fixture(scope="class")
    def predictions(self, provider):
        from fantasyfb.scoring.fantasy_scoring import FantasyScorer
        from fantasyfb.configs import apply_default_scoring_categories

        scoring = apply_default_scoring_categories({
            "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
            "Rush Yds": 0.1, "Rush TD": 6,
            "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
            "Sack": 1, "Int": 2, "Fum Rec": 2,
            "Pts Allow 0": 10, "Pts Allow 1-6": 7, "Pts Allow 7-13": 4,
        })
        stats = provider.get_player_stats(202301, 202410)
        scored = FantasyScorer(scoring).calculate_points(stats)
        sched = provider.get_schedule(2023, 2024)

        # Single test week to keep this fast; with 13 weeks we'd add ~30s.
        return run_backtest(
            scored, sched, test_season=2024, test_weeks=[10],
        )

    def test_emits_all_variants(self, predictions: pd.DataFrame) -> None:
        variants = set(predictions["variant"].unique())
        expected = {"V1_full", "V2_neutral", "V2_default", "V2_fitted", "baseline"}
        assert expected.issubset(variants)

    def test_predictions_are_finite(self, predictions: pd.DataFrame) -> None:
        # NaN/inf in any variant -> something blew up in feature
        # calculation or the engine. This catches that bluntly.
        assert predictions["prediction"].notna().all()
        assert np.isfinite(predictions["prediction"]).all()

    def test_v2_beats_baseline_on_offensive_positions(
        self, predictions: pd.DataFrame
    ) -> None:
        # If V2 isn't beating "predict the position average for everyone"
        # on QB/RB/WR/TE, the engine isn't earning its keep.
        summary = evaluate(predictions)
        for pos in ["QB", "RB", "WR", "TE"]:
            base = summary.query(
                "position == @pos and variant == 'baseline'"
            )["mae"].iloc[0]
            v2 = summary.query(
                "position == @pos and variant == 'V2_neutral'"
            )["mae"].iloc[0]
            assert v2 < base, f"V2 didn't beat baseline at {pos}"
