#!/usr/bin/env python3
"""V1 vs V2 projection engine bake-off.

Walk-forward backtest over a full regular season comparing:
  V1_full     – legacy ELO-weighted engine
  V2_neutral  – new volume×efficiency engine, no matchup adjustment
  V2_default  – V2 engine + hand-tuned Vegas matchup weights
  baseline    – position-average (sanity floor)

Lower MAE/RMSE = better. The result informs whether to retire V1 (issue #24).

Note: V2_fitted (LS-fitted matchup weights) is Stage 3 work and not yet
implemented in run_backtest(); it is omitted from this report.

Usage:
    python scripts/run_bakeoff.py
    python scripts/run_bakeoff.py --test-season 2023
    python scripts/run_bakeoff.py --weeks 1 9   # first-half sanity check
    python scripts/run_bakeoff.py --history-years 2 --test-season 2024
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

from fantasyfb.configs import apply_default_scoring_categories
from fantasyfb.data.nflreadpy_provider import NflreadpyProvider
from fantasyfb.scoring.fantasy_scoring import FantasyScorer
from fantasyfb.sim.backtest import evaluate, run_backtest


_HALF_PPR = apply_default_scoring_categories({
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

# Canonical variant display order (V2_fitted excluded until Stage 3).
_VARIANTS = ["V1_full", "V2_neutral", "V2_default", "baseline"]
_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
_WIDTH = 68


def _hr(char: str = "─") -> str:
    return char * _WIDTH


def _overall(summary: pd.DataFrame) -> pd.DataFrame:
    """Weighted-average MAE/RMSE across all positions."""
    rows = []
    for variant in _VARIANTS:
        grp = summary[summary["variant"] == variant]
        if grp.empty:
            continue
        n = grp["n"].sum()
        mae = (grp["mae"] * grp["n"]).sum() / n
        rmse = float(np.sqrt((grp["rmse"] ** 2 * grp["n"]).sum() / n))
        rows.append({"variant": variant, "n": int(n), "mae": mae, "rmse": rmse})
    return pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)


def _print_position_table(title: str, summary: pd.DataFrame, metric: str) -> None:
    print(f"\n{_hr()}")
    print(f"  {title}")
    print(_hr())
    pivot = (
        summary[summary["variant"].isin(_VARIANTS)]
        .pivot(index="position", columns="variant", values=metric)
        .reindex(index=_POSITIONS, columns=_VARIANTS)
        .round(3)
    )
    # Sort positions by number of observations (most populous first).
    n_by_pos = summary.groupby("position")["n"].sum().reindex(_POSITIONS).fillna(0)
    pivot = pivot.loc[n_by_pos.sort_values(ascending=False).index]
    print(pivot.to_string(na_rep="—"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run V1 vs V2 projection engine bake-off.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--test-season", type=int, default=2024,
        help="NFL season year to evaluate on",
    )
    parser.add_argument(
        "--history-years", type=int, default=3,
        help="Years of history to load before the test season",
    )
    parser.add_argument(
        "--weeks", type=int, nargs=2, default=[1, 18], metavar=("START", "END"),
        help="Inclusive week range to evaluate",
    )
    args = parser.parse_args()

    test_season = args.test_season
    history_start = test_season - args.history_years
    test_weeks = list(range(args.weeks[0], args.weeks[1] + 1))

    print(f"\n{_hr('═')}")
    print(f"  V1 vs V2 Bake-Off — {test_season} season, "
          f"weeks {test_weeks[0]}–{test_weeks[-1]}")
    print(f"  Training history: {history_start}–{test_season - 1}")
    print(_hr("═"))

    provider = NflreadpyProvider()

    print("\nLoading player stats ...", end=" ", flush=True)
    t0 = time.monotonic()
    stats_raw = provider.get_player_stats(
        history_start * 100 + 1,
        test_season * 100 + 18,
    )
    scored = FantasyScorer(_HALF_PPR).calculate_points(stats_raw)
    print(f"{len(scored):,} player-game rows  ({time.monotonic() - t0:.1f}s)")

    print("Loading schedule ...", end=" ", flush=True)
    t0 = time.monotonic()
    schedule = provider.get_schedule(history_start, test_season)
    print(f"{len(schedule):,} team-week rows  ({time.monotonic() - t0:.1f}s)")

    print(
        f"\nRunning walk-forward backtest over {len(test_weeks)} weeks "
        "(this fetches V1 weights from GitHub each week — allow 1–3 min) ...\n"
    )
    t0 = time.monotonic()
    predictions = run_backtest(
        stats=scored,
        schedule=schedule,
        test_season=test_season,
        test_weeks=test_weeks,
    )
    elapsed = time.monotonic() - t0
    print(f"  Done — {len(predictions):,} prediction rows in {elapsed:.0f}s\n")

    # V2_fitted is not implemented yet (Stage 3 LS fitting); omit it so the
    # table doesn't misleadingly show it tying the baseline.
    predictions = predictions[predictions["variant"] != "V2_fitted"].copy()

    if predictions.empty:
        print("ERROR: no predictions produced. Check data load.", file=sys.stderr)
        return 1

    summary = evaluate(predictions)
    overall = _overall(summary)

    _print_position_table(f"MAE by position ({test_season})", summary, "mae")
    _print_position_table(f"RMSE by position ({test_season})", summary, "rmse")

    print(f"\n{_hr()}")
    print("  Overall (weighted by player-game count)")
    print(_hr())
    print(overall[["variant", "n", "mae", "rmse"]].round(3).to_string(index=False))

    # ── Verdict ────────────────────────────────────────────────────────
    best = overall.iloc[0]
    v1_row = overall[overall["variant"] == "V1_full"]
    v2_row = overall[overall["variant"] == "V2_default"]
    v1_mae = v1_row["mae"].values[0] if not v1_row.empty else float("nan")
    v2_mae = v2_row["mae"].values[0] if not v2_row.empty else float("nan")
    delta = v1_mae - v2_mae  # positive means V2 better

    print(f"\n{_hr('═')}")
    print(f"  VERDICT")
    print(_hr("═"))
    print(f"  Best model : {best['variant']}  (overall MAE {best['mae']:.3f})")
    print(f"  V1_full    : MAE {v1_mae:.3f}")
    print(f"  V2_default : MAE {v2_mae:.3f}  (Δ {delta:+.3f} vs V1)")

    if best["variant"] in ("V2_neutral", "V2_default"):
        margin_pct = abs(delta) / v1_mae * 100
        print(f"\n  ✓ V2 wins by {margin_pct:.1f}% — safe to retire V1 (see issue #24).")
    elif best["variant"] == "V1_full":
        print("\n  ✗ V1 still leads — investigate V2 edge cases before retiring.")
    else:
        print("\n  ✗ Baseline wins — both engines underperform position average.")
    print(_hr("═"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
