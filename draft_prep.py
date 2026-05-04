"""Pre-draft analytics CLI built on draft_tools.

Three views, all read-only and non-interactive -- intended for the
"sit down with the projections a few days before the draft" workflow,
not for running the draft itself (snake_draft.py / salary_cap_draft.py
own that).

Subcommands:
    tiers   -- per-position tier sheet (projection-only, no ADP needed)
    values  -- ranked table of biggest projection-vs-ADP deltas
    mock    -- run a mock draft from a given slot, print the resulting
               roster (or aggregate stats over many sims)

Each subcommand instantiates a fantasyfb.League so it picks up your
real roster_spots and scoring rules. That requires Yahoo creds the
same way the existing draft scripts do.

Examples:
    python draft_prep.py tiers --league "My Team"
    python draft_prep.py values --league "My Team" --adp ADP.csv --top 40
    python draft_prep.py mock --league "My Team" --adp ADP.csv \
        --my-pick 7 --strategy vorp --sims 50
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import pandas as pd

from draft_tools import (
    MockDraft,
    assign_tiers,
    compute_vorp,
    load_adp_csv,
    merge_adp,
)


def _build_league(args: argparse.Namespace):
    """Instantiate the League once and reuse for downstream analytics.

    Imported lazily so `--help` works without Yahoo deps installed.
    """
    import fantasyfb as fb
    return fb.League(name=args.league)


def _maybe_save(df: pd.DataFrame, path: Optional[str]) -> None:
    if path:
        df.to_csv(path, index=False)
        print(f"\nSaved to {path}")


def cmd_tiers(args: argparse.Namespace) -> int:
    league = _build_league(args)
    pool = league.players[~league.players["player_id_sr"].astype(str)
                          .str.startswith("avg_")]
    with_vorp = compute_vorp(pool, league.roster_spots, len(league.teams))
    tiered = assign_tiers(with_vorp, min_gap_z=args.gap_z)

    positions = [args.position] if args.position else ["QB", "RB", "WR", "TE", "K", "DEF"]
    show_cols = ["name", "current_team", "position", "tier",
                 "points_rate", "vorp_per_game"]
    show_cols = [c for c in show_cols if c in tiered.columns]

    out_frames = []
    for pos in positions:
        sub = (tiered[tiered["position"] == pos]
               .sort_values("points_rate", ascending=False)
               .head(args.top))
        if sub.empty:
            continue
        print(f"\n=== {pos} (top {len(sub)}) ===")
        print(sub[show_cols].to_string(index=False))
        out_frames.append(sub[show_cols])

    if out_frames:
        _maybe_save(pd.concat(out_frames, ignore_index=True), args.output)
    return 0


def cmd_values(args: argparse.Namespace) -> int:
    league = _build_league(args)
    pool = league.players[~league.players["player_id_sr"].astype(str)
                          .str.startswith("avg_")]
    with_vorp = compute_vorp(pool, league.roster_spots, len(league.teams))
    tiered = assign_tiers(with_vorp, min_gap_z=args.gap_z)

    adp = load_adp_csv(args.adp)
    merged = merge_adp(tiered, adp, num_teams=len(league.teams))

    # Drop players with no ADP (mostly undraftable depth) so the
    # "values" view stays a market-vs-projection comparison.
    rated = merged.dropna(subset=["adp", "adp_value"]).copy()
    rated = rated.sort_values("adp_value", ascending=False).head(args.top)

    show_cols = ["name", "current_team", "position", "tier",
                 "points_rate", "vorp_per_game", "adp", "adp_round",
                 "proj_rank", "adp_value"]
    show_cols = [c for c in show_cols if c in rated.columns]

    print(f"\nTop {len(rated)} value picks (positive = market under-rates):")
    print(rated[show_cols].to_string(index=False))
    _maybe_save(rated[show_cols], args.output)
    return 0


def cmd_mock(args: argparse.Namespace) -> int:
    league = _build_league(args)
    pool = league.players[~league.players["player_id_sr"].astype(str)
                          .str.startswith("avg_")]
    with_vorp = compute_vorp(pool, league.roster_spots, len(league.teams))

    adp = load_adp_csv(args.adp)
    merged = merge_adp(with_vorp, adp, num_teams=len(league.teams))
    # MockDraft wants ADP for everyone it might pick; players without
    # ADP get drafted only as last-resort filler. That's the right
    # behavior, no need to drop them.

    md = MockDraft(
        merged, league.roster_spots, num_teams=len(league.teams),
        my_pick=args.my_pick, snake=not args.linear, noise_sd=args.noise_sd,
        my_strategy=args.strategy,
    )

    if args.sims == 1:
        result = md.simulate(seed=args.seed)
        my_roster = result[result["is_user"]].sort_values("pick")
        print(f"\nYour mock-draft roster (pick #{args.my_pick}, "
              f"strategy={args.strategy}):")
        print(my_roster[["round", "pick", "name", "position",
                         "points_rate", "vorp_per_game", "adp"]]
              .to_string(index=False))
        total_vorp = my_roster["vorp_per_game"].sum()
        print(f"\nTotal starter+bench VORP per game: {total_vorp:.2f}")
        _maybe_save(result, args.output)
    else:
        runs = md.simulate_many(args.sims, seed=args.seed)
        my = runs[runs["is_user"]]
        # Show aggregate roster: which players the strategy actually
        # lands in each round, by frequency.
        print(f"\nMost frequent picks per round across {args.sims} sims:")
        agg = (my.groupby(["round", "name", "position"])
                 .size().reset_index(name="count")
                 .sort_values(["round", "count"], ascending=[True, False]))
        for rnd, group in agg.groupby("round"):
            top3 = group.head(3)
            line = ", ".join(
                f"{r['name']} ({r['position']}, {r['count']}/{args.sims})"
                for _, r in top3.iterrows()
            )
            print(f"  R{int(rnd):>2}: {line}")
        _maybe_save(runs, args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="draft_prep",
        description="Pre-draft analytics: tiers, values, mock drafts.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Shared args -- attached individually so each subcommand's --help
    # is self-contained.
    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--league", required=True,
                       help="Yahoo team name (passed to fantasyfb.League)")
        p.add_argument("--output", default=None,
                       help="optional CSV path to save the result")

    p_tiers = sub.add_parser("tiers", help="per-position tier sheet")
    add_common(p_tiers)
    p_tiers.add_argument("--position", default=None,
                         help="restrict to one position (QB/RB/WR/TE/K/DEF)")
    p_tiers.add_argument("--top", type=int, default=30,
                         help="rows per position (default 30)")
    p_tiers.add_argument("--gap-z", type=float, default=1.0, dest="gap_z",
                         help="tier-break z-score threshold (default 1.0)")
    p_tiers.set_defaults(func=cmd_tiers)

    p_vals = sub.add_parser("values", help="biggest projection-vs-ADP deltas")
    add_common(p_vals)
    p_vals.add_argument("--adp", required=True, help="path to ADP CSV")
    p_vals.add_argument("--top", type=int, default=40,
                        help="rows to show (default 40)")
    p_vals.add_argument("--gap-z", type=float, default=1.0, dest="gap_z",
                        help="tier-break z-score threshold (default 1.0)")
    p_vals.set_defaults(func=cmd_values)

    p_mock = sub.add_parser("mock", help="run mock draft(s)")
    add_common(p_mock)
    p_mock.add_argument("--adp", required=True, help="path to ADP CSV")
    p_mock.add_argument("--my-pick", type=int, required=True, dest="my_pick",
                        help="your 1-indexed draft slot")
    p_mock.add_argument("--strategy", default="vorp",
                        choices=["bpa", "vorp", "need"],
                        help="user pick strategy (default vorp)")
    p_mock.add_argument("--sims", type=int, default=1,
                        help="number of mock drafts to run (default 1)")
    p_mock.add_argument("--noise-sd", type=float, default=8.0, dest="noise_sd",
                        help="ADP noise stdev for opponents (default 8.0)")
    p_mock.add_argument("--linear", action="store_true",
                        help="use linear (non-snake) draft order")
    p_mock.add_argument("--seed", type=int, default=None,
                        help="RNG seed for reproducibility")
    p_mock.set_defaults(func=cmd_mock)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
