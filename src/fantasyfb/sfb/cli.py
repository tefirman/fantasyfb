"""``sfb-field``: field-wide Scott Fish Bowl odds, in three steps.

    sfb-field leagues leaderboard.html --out-dir sfb/          # once per season
    sfb-field collect sfb/leagues.csv --out-dir sfb/data       # pulls Sleeper (~20 minutes)
    sfb-field simulate sfb/data --out-dir sfb                  # offline, under a minute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.player_data_manager import INJURED_LIST_URL
from ..data.sleeper_client import SleeperClient
from .collect import DEFAULT_MAX_CALLS_PER_MINUTE, collect_field, collect_rosters
from .field import FieldData, simulate_field
from .injuries import scan_injuries, validate_injured_list
from .leagues import league_list, parse_leaderboard, read_league_ids
from .players import add_player_info


def _leagues(args) -> int:
    teams = parse_leaderboard(Path(args.leaderboard).read_text(encoding="utf-8", errors="replace"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    leagues = league_list(teams)
    leagues.to_csv(out_dir / "leagues.csv", index=False)
    teams.to_csv(out_dir / "leaderboard_snapshot.csv", index=False)
    counts = leagues.groupby("platform").size().to_dict()
    print(f"{len(teams)} teams in {len(leagues)} leagues {counts}; wrote leagues.csv and leaderboard_snapshot.csv to {out_dir}")
    return 0


def _collect(args) -> int:
    league_ids = args.only.split(",") if args.only else read_league_ids(args.leagues)
    errors = collect_field(league_ids, args.out_dir, workers=args.workers,
                           max_calls_per_minute=args.max_calls_per_minute)
    for league_id, error in errors:
        print(f"FAILED {league_id}: {error}", file=sys.stderr)
    return 1 if errors else 0


def _simulate(args) -> int:
    result = simulate_field(FieldData.load(args.data), num_sims=args.num_sims,
                            playoff_reps=args.playoff_reps, seed=args.seed)
    cut = result.cut_line
    print(f"{len(result.teams)} teams, quota {result.quota}; points cut line {np.nanmean(cut):.0f} "
          f"(sd {np.nanstd(cut):.1f}, 5-95%: {np.nanpercentile(cut, 5):.0f}-{np.nanpercentile(cut, 95):.0f})")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.teams.to_csv(out_dir / "odds.csv", index=False)
    pd.DataFrame({"num_sim": np.arange(len(cut)), "cut_line": cut}).to_csv(out_dir / "cut_line.csv", index=False)
    add_player_info(result.players).to_csv(out_dir / "players.csv", index=False)
    print(f"wrote odds.csv, cut_line.csv and players.csv to {out_dir}")
    return 0


def _injuries(args) -> int:
    rosters, errors = collect_rosters(read_league_ids(args.leagues))
    for league_id, error in errors:
        print(f"FAILED {league_id}: {error}", file=sys.stderr)
    if rosters.empty:
        print("no rosters collected", file=sys.stderr)
        return 1
    week = args.week or SleeperClient("").get_current_week()
    new, old = scan_injuries(
        rosters,
        SleeperClient("").get_all_players(),
        pd.read_csv(args.injured_list),
        week,
        args.min_teams,
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    new.to_csv(out_dir / "new_injuries.csv", index=False)
    old.to_csv(out_dir / "old_injuries.csv", index=False)
    print(f"week {week}: {len(new)} new injuries to research, {len(old)} listed players who look healthy")
    return 0


def _check_injuries(args) -> int:
    after = pd.read_csv(args.after)
    known = SleeperClient("").get_all_players().player_id_sr.dropna().str.strip().tolist()
    try:
        validate_injured_list(pd.read_csv(args.before), after, known, args.max_changes)
    except ValueError as e:
        print(f"injured_list.csv rejected: {e}", file=sys.stderr)
        return 1
    print(f"injured_list.csv ok ({len(after)} rows)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sfb-field", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    leagues = commands.add_parser("leagues", help="list the leagues on a saved SFB leaderboard page")
    leagues.add_argument("leaderboard", help="saved leaderboard HTML")
    leagues.add_argument("--out-dir", default=".", help="where to write leagues.csv (default: here)")
    leagues.set_defaults(run=_leagues)

    collect = commands.add_parser("collect", help="pull the Sleeper leagues (rate-limited)")
    collect.add_argument("leagues", help="leagues.csv from the leagues step")
    collect.add_argument("--out-dir", required=True, help="where to write the parquet files")
    collect.add_argument("--workers", type=int, default=3)
    collect.add_argument("--max-calls-per-minute", type=int, default=DEFAULT_MAX_CALLS_PER_MINUTE,
                         help="Sleeper asks for under 1,000 (default: %(default)s)")
    collect.add_argument("--only", help="comma-separated league IDs to (re)collect instead of the whole list")
    collect.set_defaults(run=_collect)

    injuries = commands.add_parser(
        "injuries", help="list injuries across the field that injured_list.csv doesn't cover (one Sleeper request per league)")
    injuries.add_argument("leagues", help="leagues.csv from the leagues step; current rosters are pulled fresh")
    injuries.add_argument("--injured-list", default=INJURED_LIST_URL, help="injured_list.csv path or URL (default: the live one)")
    injuries.add_argument("--week", type=int, help="week being projected (default: Sleeper's current week)")
    injuries.add_argument("--min-teams", type=int, default=20, help="field teams that must roster a player (default: %(default)s)")
    injuries.add_argument("--out-dir", default=".", help="where to write new_injuries.csv and old_injuries.csv")
    injuries.set_defaults(run=_injuries)

    check = commands.add_parser("check-injuries", help="validate an edited injured_list.csv before it is committed")
    check.add_argument("before", help="injured_list.csv as it was")
    check.add_argument("after", help="injured_list.csv as edited")
    check.add_argument("--max-changes", type=int, default=25)
    check.set_defaults(run=_check_injuries)

    simulate = commands.add_parser("simulate", help="simulate the field from collected data (offline)")
    simulate.add_argument("data", help="directory written by the collect step")
    simulate.add_argument("--out-dir", default=".", help="where to write odds.csv and cut_line.csv (default: here)")
    simulate.add_argument("--num-sims", type=int, default=1000)
    simulate.add_argument("--playoff-reps", type=int, default=20)
    simulate.add_argument("--seed", type=int, default=1)
    simulate.set_defaults(run=_simulate)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
