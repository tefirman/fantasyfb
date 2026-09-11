"""Tests for the V2 backtest harness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.scoring.matchup_model import MatchupModel, _DEFAULT_WEIGHTS
from fantasyfb.sim.backtest import _historical_strings, _v2_predictions, evaluate, run_backtest


class _FakeStringProvider:
    """Stub provider whose get_depth_charts records the (season, week) it
    was asked for and returns a fixed strings table, used to test that
    run_backtest/_v2_predictions actually wire real historical strings
    through rather than silently falling back to string=1.0."""

    def __init__(self, strings: pd.DataFrame) -> None:
        self.strings = strings
        self.calls: list[tuple[int, int]] = []

    def get_depth_charts(self, season=None, week=None):
        self.calls.append((season, week))
        return self.strings


class TestHistoricalStrings:
    def test_no_provider_returns_empty(self) -> None:
        out = _historical_strings(None, 2023, 5)
        assert out.empty
        assert list(out.columns) == ["player_id_sr", "string"]

    def test_provider_queried_for_requested_season_and_week(self) -> None:
        strings = pd.DataFrame({
            "player_id_sr": ["p1", "p2"],
            "current_team": ["AAA", "BBB"],
            "position": ["WR", "RB"],
            "string": [2.0, 3.0],
        })
        provider = _FakeStringProvider(strings)
        out = _historical_strings(provider, 2023, 7)
        assert provider.calls == [(2023, 7)]
        assert set(out["player_id_sr"]) == {"p1", "p2"}

    def test_empty_provider_result_returns_empty(self) -> None:
        provider = _FakeStringProvider(pd.DataFrame())
        out = _historical_strings(provider, 2023, 7)
        assert out.empty

    def test_rows_missing_player_id_are_dropped(self) -> None:
        strings = pd.DataFrame({
            "player_id_sr": ["p1", None],
            "current_team": ["AAA", "BBB"],
            "position": ["WR", "RB"],
            "string": [2.0, 3.0],
        })
        provider = _FakeStringProvider(strings)
        out = _historical_strings(provider, 2023, 7)
        assert list(out["player_id_sr"]) == ["p1"]


class TestV2PredictionsUsesRealStrings:
    """Confirm the matchup factor for a player actually changes based on
    the historical string passed in, closing the issue #78 blind spot
    where every backtest player was hardcoded to string=1.0."""

    @pytest.fixture
    def stub_engine(self, monkeypatch):
        class _StubEngine:
            def calculate_projections(self, stats, earliest, current_week):
                return pd.DataFrame({
                    "player_id_sr": ["wr_deep"],
                    "position": ["WR"],
                    "points_rate": [10.0],
                })
        return _StubEngine()

    @pytest.fixture
    def stats_and_schedule(self):
        stats = pd.DataFrame({
            "player_id_sr": ["wr_deep"],
            "season": [2023], "week": [6],
            "team": ["AAA"],
        })
        schedule = pd.DataFrame({
            "season": [2023], "week": [7],
            "team": ["AAA"], "opp_team": ["BBB"],
            "implied_total": [24.0], "opp_implied_total": [20.0],
        })
        return stats, schedule

    def test_deep_string_lowers_prediction_vs_default_string_one(
        self, stub_engine, stats_and_schedule
    ) -> None:
        stats, schedule = stats_and_schedule
        matchup = MatchupModel(weights=dict(_DEFAULT_WEIGHTS))
        cutoff = 202307

        no_strings = _v2_predictions(
            stub_engine, matchup, stats, schedule, cutoff, strings=None,
        )
        deep_strings = pd.DataFrame({
            "player_id_sr": ["wr_deep"], "string": [6.0],
        })
        with_strings = _v2_predictions(
            stub_engine, matchup, stats, schedule, cutoff, strings=deep_strings,
        )

        pred_default = no_strings.iloc[0]["prediction"]
        pred_deep = with_strings.iloc[0]["prediction"]
        assert pred_deep < pred_default

    def test_missing_player_in_strings_table_falls_back_to_starter(
        self, stub_engine, stats_and_schedule
    ) -> None:
        stats, schedule = stats_and_schedule
        matchup = MatchupModel(weights=dict(_DEFAULT_WEIGHTS))
        cutoff = 202307

        empty_strings = pd.DataFrame(columns=["player_id_sr", "string"])
        no_strings = _v2_predictions(
            stub_engine, matchup, stats, schedule, cutoff, strings=None,
        )
        with_empty = _v2_predictions(
            stub_engine, matchup, stats, schedule, cutoff, strings=empty_strings,
        )
        assert no_strings.iloc[0]["prediction"] == pytest.approx(
            with_empty.iloc[0]["prediction"]
        )


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
    runtime sane (the harness runs three V2 variants per week)."""

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
        # Passes the live provider so V2_default/V2_fitted exercise real
        # historical depth-chart strings rather than the old string=1.0
        # hardcode (issue #78).
        return run_backtest(
            scored, sched, test_season=2024, test_weeks=[10],
            provider=provider,
        )

    def test_emits_all_variants(self, predictions: pd.DataFrame) -> None:
        variants = set(predictions["variant"].unique())
        expected = {"V2_neutral", "V2_default", "V2_fitted", "baseline"}
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
