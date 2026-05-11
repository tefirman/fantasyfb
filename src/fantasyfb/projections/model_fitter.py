"""
Walk-forward least-squares fitting of MatchupModel weights.

Stage 3 of the V2 rebuild. The matchup factor is multiplicative around 1.0:

    factor = 1 + alpha * z_implied_total + beta * z_allowed_vs_pos
             - gamma * (string - 1)

Once a player's `neutral_rate` (volume * efficiency) is fixed, the alpha
and beta terms are linear in their parameters per position, so OLS does
the work. Gamma (depth-chart penalty) is left at its hand-tuned default
because we don't have reliable historical week-by-week depth charts to
fit against.

Walk-forward construction: for each historical game, we compute features
using only data from before that game. That isolates the matchup signal
from the player's own future performance and prevents the fit from
memorizing rather than generalizing.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..scoring.matchup_model import MatchupModel, _DEFAULT_WEIGHTS, _PositionWeights
from .engine_v2 import ProjectionEngineV2


_FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def build_training_set(
    stats_df: pd.DataFrame,
    schedule_df: pd.DataFrame,
    training_seasons: List[int],
    earliest_history: Optional[int] = None,
    min_neutral_rate: float = 0.5,
) -> pd.DataFrame:
    """Walk-forward feature/target table for matchup weight fitting.

    For each game in `training_seasons`, we compute:
        neutral_rate     -- ProjectionEngineV2 output as of the start of
                            the target week, using all stats from the
                            earliest history up to but not including the
                            target week.
        z_implied_total  -- z-score of the team's implied total against
                            the league baseline for that cutoff.
        z_allowed        -- z-score of opponent's allowed-fantasy-points-
                            vs-position against league baseline.
        actual_points    -- the actual fantasy points the player scored
                            in the target week (the regression target).

    Args:
        stats_df: per-game stats with `points` already populated.
        schedule_df: provider schedule with `implied_total` /
            `opp_implied_total` populated.
        training_seasons: seasons to use as targets (we still pull from
            earlier seasons for history).
        earliest_history: oldest YYYYWW to include in history. Defaults
            to two full seasons before the earliest training season.
        min_neutral_rate: drop rows whose neutral_rate falls below this
            threshold; a tiny denominator turns into a huge meaningless
            residual that would dominate the fit.

    Returns:
        Long-format DataFrame; one row per (player, week) actually played.
    """
    if earliest_history is None:
        earliest_history = (min(training_seasons) - 2) * 100 + 1

    engine = ProjectionEngineV2()
    rows: list[dict] = []

    for season in sorted(training_seasons):
        season_weeks = sorted(
            stats_df.loc[stats_df.season == season, "week"].unique()
        )
        for target_week in season_weeks:
            cutoff = season * 100 + target_week
            history = stats_df[
                (stats_df.season * 100 + stats_df.week) < cutoff
            ]
            history = history[
                (history.season * 100 + history.week) >= earliest_history
            ]
            if history.empty:
                continue

            earliest_per_pos = {p: earliest_history for p in _FANTASY_POSITIONS}
            projections = engine.calculate_projections(
                history, earliest_per_pos, current_week=cutoff,
            ).set_index("player_id_sr")["points_rate"].to_dict()

            sched_history = schedule_df[
                (schedule_df.season * 100 + schedule_df.week) < cutoff
            ]
            matchup = MatchupModel.from_history(history, sched_history)

            week_stats = stats_df[
                (stats_df.season == season) & (stats_df.week == target_week)
            ]
            week_sched_lookup = schedule_df[
                (schedule_df.season == season) & (schedule_df.week == target_week)
            ].set_index("team")[["implied_total", "opp_implied_total"]]

            for _, game in week_stats.iterrows():
                neutral_rate = projections.get(game["player_id_sr"])
                if neutral_rate is None or neutral_rate < min_neutral_rate:
                    continue

                sched_row = week_sched_lookup.loc[game["team"]] \
                    if game["team"] in week_sched_lookup.index else None
                if sched_row is None:
                    continue

                relevant_total = (
                    sched_row["opp_implied_total"]
                    if game["position"] == "DEF"
                    else sched_row["implied_total"]
                )
                if pd.isna(relevant_total) or relevant_total == 0:
                    continue

                rows.append({
                    "player_id_sr": game["player_id_sr"],
                    "position": game["position"],
                    "season": int(season),
                    "week": int(target_week),
                    "neutral_rate": float(neutral_rate),
                    "actual_points": float(game["points"]),
                    "z_implied_total": matchup._z_implied_total(relevant_total),
                    "z_allowed": matchup._z_allowed(
                        game["opponent"], game["position"]
                    ),
                })

    return pd.DataFrame(rows)


def fit_matchup_weights(
    training: pd.DataFrame,
    default_weights: Optional[Dict[str, _PositionWeights]] = None,
    min_samples: int = 50,
    coefficient_clip: float = 1.0,
    ridge_lambda: float = 5.0,
) -> Dict[str, _PositionWeights]:
    """Per-position OLS fit for `alpha` (implied total) and `beta` (allowed).

    Solves for each position the Bayesian-ridge problem:
        minimize ||y - X*beta||^2 + ridge_lambda * ||beta - beta_default||^2

    where y = actual / neutral - 1 and X = [z_implied, z_allowed]. Pulling
    toward the hand-tuned default rather than toward zero matters for the
    offensive positions: V2's neutral_rate already absorbs most of the
    "team scoring environment" signal through historical efficiency, so
    the residual signal that matchup adds is small. A vanilla ridge would
    collapse alphas to 0 in low-signal positions; ridge-to-defaults
    preserves the hand-tuned prior unless data overrides it.

    Args:
        training: output of :func:`build_training_set`.
        default_weights: prior weights to ridge-shrink toward. Below the
            `min_samples` threshold we return them unchanged.
        min_samples: minimum row count to attempt a fit; below this, fall
            through to defaults.
        coefficient_clip: upper bound for |alpha| and |beta| post-fit.
        ridge_lambda: L2 strength on deviations from defaults. Larger =
            trust defaults more relative to data. 5.0 is calibrated to
            yield meaningful movement on positions with hundreds of
            samples while keeping K/DEF (where data is noisy) close to
            their priors.

    Returns:
        Dict mapping position to fitted `_PositionWeights`. `gamma`
        is carried over from defaults; we don't have reliable historical
        depth-chart data to fit it against.
    """
    defaults = default_weights or dict(_DEFAULT_WEIGHTS)
    fitted: Dict[str, _PositionWeights] = {}

    for position in _FANTASY_POSITIONS:
        pos_rows = training[training.position == position]
        if len(pos_rows) < min_samples:
            fitted[position] = defaults[position]
            continue

        residual = (pos_rows["actual_points"] / pos_rows["neutral_rate"]) - 1.0
        # Winsorize at the 1st/99th percentile -- one freak game shouldn't
        # be allowed to swing the position's coefficients.
        lo, hi = residual.quantile([0.01, 0.99])
        residual = residual.clip(lo, hi).to_numpy()

        X = pos_rows[["z_implied_total", "z_allowed"]].to_numpy()

        # Ridge-to-defaults: shrink toward the hand-tuned prior, not zero.
        prior = np.array([defaults[position].alpha, defaults[position].beta])
        gram = X.T @ X + ridge_lambda * np.eye(X.shape[1])
        rhs = X.T @ residual + ridge_lambda * prior
        coefs = np.linalg.solve(gram, rhs)

        alpha = float(np.clip(coefs[0], -coefficient_clip, coefficient_clip))
        beta = float(np.clip(coefs[1], -coefficient_clip, coefficient_clip))

        fitted[position] = _PositionWeights(
            alpha=alpha, beta=beta, gamma=defaults[position].gamma,
        )

    return fitted


def fit_from_history(
    stats_df: pd.DataFrame,
    schedule_df: pd.DataFrame,
    training_seasons: List[int],
    **fit_kwargs,
) -> Dict[str, _PositionWeights]:
    """Convenience: build the training set, run the fit, return weights.

    Heavy compute is in :func:`build_training_set` (one V2 projection
    call per training week). Cache the training DataFrame if you're
    going to refit with different hyperparameters.
    """
    training = build_training_set(stats_df, schedule_df, training_seasons)
    return fit_matchup_weights(training, **fit_kwargs)
