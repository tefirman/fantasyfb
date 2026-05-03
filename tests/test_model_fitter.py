"""Tests for the walk-forward least-squares fitter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from matchup_model import _DEFAULT_WEIGHTS, _PositionWeights
from model_fitter import build_training_set, fit_matchup_weights


def _synthetic_training(
    n: int, true_alpha: float, true_beta: float, *,
    position: str = "QB", noise: float = 1.0, seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    z_total = rng.normal(0, 1, n)
    z_allowed = rng.normal(0, 1, n)
    neutral_rate = rng.uniform(15, 25, n)
    factor = 1 + true_alpha * z_total + true_beta * z_allowed
    actuals = neutral_rate * factor + rng.normal(0, noise, n)
    return pd.DataFrame({
        "position": position,
        "player_id_sr": [f"p_{i}" for i in range(n)],
        "season": 2024, "week": 1,
        "neutral_rate": neutral_rate,
        "actual_points": actuals,
        "z_implied_total": z_total,
        "z_allowed": z_allowed,
    })


class TestSyntheticRecovery:
    def test_recovers_known_coefficients(self) -> None:
        training = _synthetic_training(n=2000, true_alpha=0.25, true_beta=0.15,
                                       noise=1.0, seed=42)
        fitted = fit_matchup_weights(training, ridge_lambda=0.0)
        assert fitted["QB"].alpha == pytest.approx(0.25, abs=0.05)
        assert fitted["QB"].beta == pytest.approx(0.15, abs=0.05)

    def test_higher_ridge_pulls_fit_toward_defaults(self) -> None:
        # Regularization knob check: with a true alpha far from the
        # hand-tuned default and noisy data, increasing ridge_lambda
        # should move the fit closer to the default (and farther from
        # the unregularized OLS solution). Comparing two fits at
        # different ridge strengths is a cleaner test than asserting an
        # absolute distance, which depends on noise realization.
        default_alpha = _DEFAULT_WEIGHTS["QB"].alpha
        training = _synthetic_training(
            n=300, true_alpha=-0.5, true_beta=-0.5,
            position="QB", noise=20.0, seed=0,
        )
        weak = fit_matchup_weights(training, ridge_lambda=0.1)
        strong = fit_matchup_weights(training, ridge_lambda=5000.0)
        assert abs(strong["QB"].alpha - default_alpha) < abs(weak["QB"].alpha - default_alpha)


class TestFallbackBehavior:
    def test_below_min_samples_returns_defaults(self) -> None:
        training = _synthetic_training(n=10, true_alpha=0.5, true_beta=0.0)
        fitted = fit_matchup_weights(training, min_samples=50)
        assert fitted["QB"] == _DEFAULT_WEIGHTS["QB"]

    def test_emits_weights_for_every_position(self) -> None:
        training = _synthetic_training(n=10, true_alpha=0.0, true_beta=0.0)
        fitted = fit_matchup_weights(training, min_samples=50)
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            assert pos in fitted

    def test_carries_gamma_from_defaults(self) -> None:
        training = _synthetic_training(n=2000, true_alpha=0.0, true_beta=0.0)
        fitted = fit_matchup_weights(training)
        assert fitted["QB"].gamma == _DEFAULT_WEIGHTS["QB"].gamma


class TestCoefficientClipping:
    def test_clips_runaway_coefficients(self) -> None:
        # No regularization + tiny sample with extreme outliers can
        # produce huge coefficients; the clip guards downstream.
        rng = np.random.default_rng(0)
        n = 60
        training = pd.DataFrame({
            "position": "QB",
            "player_id_sr": [f"p_{i}" for i in range(n)],
            "season": 2024, "week": 1,
            "neutral_rate": np.full(n, 1.0),
            "actual_points": rng.normal(0, 50, n),  # huge spread
            "z_implied_total": rng.normal(0, 0.1, n),  # tiny variance
            "z_allowed": rng.normal(0, 0.1, n),
        })
        fitted = fit_matchup_weights(
            training, ridge_lambda=0.0, coefficient_clip=0.5,
        )
        assert -0.5 <= fitted["QB"].alpha <= 0.5
        assert -0.5 <= fitted["QB"].beta <= 0.5


class TestBuildTrainingSet:
    """End-to-end check of the walk-forward feature builder against the
    live provider."""

    def test_produces_expected_columns_on_real_data(
        self, provider, schedule
    ) -> None:
        from fantasy_scoring import FantasyScorer
        from league_configs import apply_default_scoring_categories

        scoring = apply_default_scoring_categories({
            "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
            "Rush Yds": 0.1, "Rush TD": 6,
            "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
        })
        # Pull a small training window to keep the test fast.
        stats = provider.get_player_stats(202301, 202408)
        scored = FantasyScorer(scoring).calculate_points(stats)
        sched = provider.get_schedule(2023, 2024)

        training = build_training_set(
            scored, sched, training_seasons=[2024],
            earliest_history=202301,
        )
        for col in [
            "player_id_sr", "position", "season", "week",
            "neutral_rate", "actual_points",
            "z_implied_total", "z_allowed",
        ]:
            assert col in training.columns
        assert len(training) > 100
        assert set(training["position"].unique()) >= {"QB", "RB", "WR", "TE"}

    def test_fitted_def_has_correctly_signed_alpha(
        self, provider, schedule
    ) -> None:
        # DEF is the position where the implied-total signal is cleanest:
        # high opp_implied_total = bad day for the defense. The fitter
        # should produce a negative alpha for DEF whether or not the
        # ridge prior agrees.
        from fantasy_scoring import FantasyScorer
        from league_configs import apply_default_scoring_categories
        from model_fitter import fit_from_history

        scoring = apply_default_scoring_categories({
            "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
            "Rush Yds": 0.1, "Rush TD": 6,
            "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
            "Sack": 1, "Int": 2, "Fum Rec": 2,
            "Pts Allow 0": 10, "Pts Allow 1-6": 7, "Pts Allow 7-13": 4,
            "Pts Allow 14-20": 1, "Pts Allow 28-34": -1, "Pts Allow 35+": -4,
        })
        stats = provider.get_player_stats(202201, 202418)
        scored = FantasyScorer(scoring).calculate_points(stats)
        sched = provider.get_schedule(2022, 2024)

        fitted = fit_from_history(scored, sched, training_seasons=[2024])
        assert fitted["DEF"].alpha < 0
        assert fitted["DEF"].beta > 0
