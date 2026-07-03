"""
Backtest harness for the V2 projection engine.

Walks forward through a held-out test period and, for each (player, week)
that actually played, computes:

  V2_neutral    = V2 engine's points_rate (no matchup adjustment)
  V2_default    = V2 engine's points_rate * MatchupModel(default weights)
  V2_fitted     = V2 engine's points_rate * MatchupModel(LS-fitted weights)
  baseline      = position average

Then reports per-position MAE and RMSE.

Walk-forward construction guards against look-ahead bias: predictions for
week W only use stats from games played before W. The fitted weights are
trained on the season prior to the test season and applied to the test set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..scoring.matchup_model import MatchupModel, _DEFAULT_WEIGHTS, _PositionWeights
from ..projections.engine_v2 import ProjectionEngineV2


_FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


@dataclass
class BacktestRow:
    """Per-(player, week) prediction record across all model variants."""
    player_id_sr: str
    position: str
    season: int
    week: int
    actual: float
    v2_neutral: float
    v2_default: float
    v2_fitted: float
    baseline: float


def _v2_predictions(
    engine: ProjectionEngineV2,
    matchup: Optional[MatchupModel],
    stats: pd.DataFrame, schedule: pd.DataFrame, cutoff: int,
) -> pd.DataFrame:
    """V2 engine output, optionally multiplied by a matchup factor."""
    earliest = {p: cutoff - 200 for p in _FANTASY_POSITIONS}
    proj = engine.calculate_projections(stats, earliest, current_week=cutoff)
    proj = proj[~proj["player_id_sr"].astype(str).str.startswith("avg_")].copy()

    if matchup is None:
        proj["prediction"] = proj["points_rate"]
        return proj[["player_id_sr", "position", "prediction"]]

    season, week = divmod(cutoff, 100)
    week_sched = schedule[
        (schedule["season"] == season) & (schedule["week"] == week)
    ][["team", "opp_team", "implied_total", "opp_implied_total"]]

    # Fold matchup info onto each player via their team this week. Need
    # team -> player join, which means we go back to stats for "what
    # team is this player on as of cutoff."
    teams = (
        stats[stats.season * 100 + stats.week < cutoff]
        .sort_values(["season", "week"])
        .drop_duplicates(subset=["player_id_sr"], keep="last")
        [["player_id_sr", "team"]]
    )
    proj = proj.merge(teams, on="player_id_sr", how="left")
    proj = proj.merge(week_sched, on="team", how="left")

    factors = []
    for _, row in proj.iterrows():
        if pd.isna(row.get("implied_total")):
            factors.append(1.0)
            continue
        factors.append(matchup.factor(
            position=row["position"],
            team_implied_total=row["implied_total"],
            opp_implied_total=row["opp_implied_total"],
            opp_team=row["opp_team"] or "",
            string=1.0,  # historical depth charts unavailable
        ))
    proj["matchup_factor"] = factors
    proj["prediction"] = proj["points_rate"] * proj["matchup_factor"]
    return proj[["player_id_sr", "position", "prediction"]]


def run_backtest(
    stats: pd.DataFrame,
    schedule: pd.DataFrame,
    test_season: int,
    test_weeks: List[int],
    fitted_weights: Optional[Dict[str, _PositionWeights]] = None,
) -> pd.DataFrame:
    """Per-(player, week) predictions for every model variant.

    Args:
        stats: per-game stats with `points` populated; should cover
            multiple seasons before test_season for history.
        schedule: provider schedule with Vegas fields.
        test_season: season to backtest in.
        test_weeks: weeks within test_season to evaluate.
        fitted_weights: LS-fit weights for V2_fitted. If None, V2_fitted
            falls back to position-average predictions.

    Returns:
        Long DataFrame, one row per (player, week, variant). Columns:
        player_id_sr, position, season, week, variant, prediction, actual.
    """
    engine_v2 = ProjectionEngineV2()
    matchup_default = MatchupModel(weights=dict(_DEFAULT_WEIGHTS))
    matchup_fitted = (
        MatchupModel(weights=fitted_weights) if fitted_weights else None
    )

    rows: list[dict] = []

    for week in test_weeks:
        cutoff = test_season * 100 + week
        history = stats[stats.season * 100 + stats.week < cutoff]
        sched_history = schedule[
            schedule.season * 100 + schedule.week < cutoff
        ]
        if history.empty:
            continue

        # Refit matchup baselines (z-scoring, allowed-vs-pos table) on
        # the history available as of this week.
        matchup_default = MatchupModel.from_history(
            history, sched_history, weights=dict(_DEFAULT_WEIGHTS),
        )
        if fitted_weights is not None:
            matchup_fitted = MatchupModel.from_history(
                history, sched_history, weights=fitted_weights,
            )

        v2_neutral = _v2_predictions(engine_v2, None, history, schedule, cutoff)
        v2_default = _v2_predictions(engine_v2, matchup_default, history, schedule, cutoff)
        v2_fitted = (
            _v2_predictions(engine_v2, matchup_fitted, history, schedule, cutoff)
            if matchup_fitted is not None else None
        )

        actuals = stats[
            (stats.season == test_season) & (stats.week == week)
        ][["player_id_sr", "position", "points"]]

        # Position-average baseline for sanity check.
        position_means = (
            history.groupby("position")["points"].mean().to_dict()
        )

        for _, actual_row in actuals.iterrows():
            pid = actual_row["player_id_sr"]
            pos = actual_row["position"]
            actual = actual_row["points"]

            def _lookup(df: Optional[pd.DataFrame]) -> float:
                if df is None or df.empty:
                    return position_means.get(pos, 0.0)
                hit = df[df["player_id_sr"] == pid]
                if hit.empty:
                    return position_means.get(pos, 0.0)
                return float(hit.iloc[0]["prediction"])

            for variant, df in [
                ("V2_neutral", v2_neutral),
                ("V2_default", v2_default), ("V2_fitted", v2_fitted),
            ]:
                rows.append({
                    "player_id_sr": pid, "position": pos,
                    "season": test_season, "week": week,
                    "variant": variant,
                    "prediction": _lookup(df),
                    "actual": actual,
                })
            rows.append({
                "player_id_sr": pid, "position": pos,
                "season": test_season, "week": week,
                "variant": "baseline",
                "prediction": position_means.get(pos, 0.0),
                "actual": actual,
            })

    return pd.DataFrame(rows)


def evaluate(predictions: pd.DataFrame) -> pd.DataFrame:
    """Per-(variant, position) MAE and RMSE."""
    if predictions.empty:
        return pd.DataFrame(columns=["variant", "position", "n", "mae", "rmse"])
    err = predictions["prediction"] - predictions["actual"]
    predictions = predictions.assign(abs_err=err.abs(), sq_err=err ** 2)
    summary = (
        predictions.groupby(["variant", "position"], as_index=False)
        .agg(n=("abs_err", "size"),
             mae=("abs_err", "mean"),
             rmse=("sq_err", lambda s: np.sqrt(s.mean())))
    )
    return summary.sort_values(["position", "variant"]).reset_index(drop=True)
