"""Run backtest.run_backtest with real nflreadpy data and print MAE/RMSE.

Trains the LS-fit matchup weights on 2023, evaluates on 2024 weeks 1-17.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from backtest import evaluate, run_backtest
from fantasy_scoring import FantasyScorer
from league_configs import apply_default_scoring_categories, get_league_config
from model_fitter import fit_from_history
from nflreadpy_provider import NflreadpyProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-start", type=int, default=2021)
    parser.add_argument("--train-season", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--first-week", type=int, default=1)
    parser.add_argument("--last-week", type=int, default=17)
    parser.add_argument("--out", default="backtest_results.csv")
    parser.add_argument("--scoring", default="draftkings",
                        help="League config name passed to get_league_config")
    args = parser.parse_args()

    provider = NflreadpyProvider()

    print(
        f"Loading stats {args.history_start}01..{args.test_season}{args.last_week:02d}",
        flush=True,
    )
    stats = provider.get_player_stats(
        args.history_start * 100 + 1,
        args.test_season * 100 + args.last_week,
    )
    print(f"  stats rows: {len(stats):,}", flush=True)

    print(
        f"Loading schedule {args.history_start}..{args.test_season}",
        flush=True,
    )
    schedule = provider.get_schedule(args.history_start, args.test_season)
    print(f"  schedule rows: {len(schedule):,}", flush=True)

    config = get_league_config(args.scoring)
    if config is None:
        raise SystemExit(f"Unknown scoring config: {args.scoring}")
    scoring = apply_default_scoring_categories(dict(config["scoring"]))
    print(f"Computing fantasy points using {args.scoring} scoring", flush=True)
    stats = FantasyScorer(scoring).calculate_points(stats)

    print(f"Fitting matchup weights on season {args.train_season}", flush=True)
    fitted = fit_from_history(stats, schedule, [args.train_season])
    for pos, w in fitted.items():
        print(f"  {pos}: alpha={w.alpha:+.3f} beta={w.beta:+.3f} gamma={w.gamma:+.3f}")

    test_weeks = list(range(args.first_week, args.last_week + 1))
    print(
        f"Running backtest on {args.test_season} weeks "
        f"{args.first_week}..{args.last_week}",
        flush=True,
    )
    predictions = run_backtest(
        stats=stats,
        schedule=schedule,
        test_season=args.test_season,
        test_weeks=test_weeks,
        fitted_weights=fitted,
    )
    predictions.to_csv(args.out, index=False)
    print(f"Wrote per-row predictions to {args.out}", flush=True)

    summary = evaluate(predictions)
    pd.set_option("display.float_format", lambda x: f"{x:7.3f}")
    print()
    print("Per-(variant, position) accuracy:")
    print(summary.to_string(index=False))

    print()
    print("Default vs fitted delta (positive = fitted better):")
    pivot_mae = summary.pivot(index="position", columns="variant", values="mae")
    pivot_rmse = summary.pivot(index="position", columns="variant", values="rmse")
    if "V2_default" in pivot_mae.columns and "V2_fitted" in pivot_mae.columns:
        delta = pd.DataFrame({
            "n": summary.pivot(index="position", columns="variant", values="n")["V2_default"],
            "mae_default": pivot_mae["V2_default"],
            "mae_fitted": pivot_mae["V2_fitted"],
            "mae_delta": pivot_mae["V2_default"] - pivot_mae["V2_fitted"],
            "rmse_default": pivot_rmse["V2_default"],
            "rmse_fitted": pivot_rmse["V2_fitted"],
            "rmse_delta": pivot_rmse["V2_default"] - pivot_rmse["V2_fitted"],
        })
        print(delta.to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
