#!/usr/bin/env python
"""Live salary cap draft cockpit (V2).

Wraps the interactive nomination/bid loop around ``salary_cap_cockpit``'s
pure view helpers. Replaces the legacy ``best_combos`` cartesian-product
optimizer (capped at 500 candidate lineups, slow on the clock) with
VORP-driven salary values, market inflation, and need-scaled bid
recommendations that render instantly.

Removed vs V1:
    --starterpct, --limit                 (replaced by need-scaled
                                           bid math in the cockpit)
    best_combos cartesian-product         (view_best is the greedy
                                           need-scaled replacement)
    possible_adds Monte Carlo for bench   (bench picks just take
                                           cockpit suggestions like
                                           any other slot)
    inline name_corrections HTTP fetch    (Yahoo linkage already
                                           happens upstream)

Commands at the prompt (also via the ``help`` command):
    <player name>  Start a nomination for that player; cockpit then
                   asks who won them and at what bid
    best           Top-N available per position with salary, inflated
                   value, and your max bid for each
    nominate       Drain-score ranking -- high market value, low fit
                   for your roster -- to bleed opponents' budgets
    whatif         Re-rank targets after a hypothetical bid lands
    lookup         Detailed view of one player (drafted or available)
    roster         Your current picks with the bid paid for each
    budgets        Every team's spent / remaining / max-bid snapshot
    exclude        Add a player to the per-session exclude list
    sim            Run a full season simulation with current rosters
    go back        Revert the previous pick
    help           Show this command list
    exit           Save progress and exit (no final summary)
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

try:
    import readline  # noqa: F401 -- imported for side effects via snake
except ImportError:  # pragma: no cover -- Windows fallback
    readline = None

from . import salary_cap_cockpit as cockpit
from .snake import (
    _enable_completion,
    _set_completion_candidates,
    check_pick_name,
    parse_payouts,
)
from .tools import (
    _bench_slots_from_spec,
    _roster_spec_to_dict,
    max_bid,
)


_PICK_COMMANDS = (
    "best", "nominate", "whatif", "lookup", "roster", "budgets",
    "exclude", "sim", "random", "random til full", "go back",
    "help", "exit",
)


_HELP_TEXT = """
Commands at the 'Player Up For Grabs' prompt:
  <player name>     Start a nomination for that player
  best              Top-N available per position with $ recommendations
  nominate          Drain-score ranking (who to nominate to drain opponents)
  whatif            Re-rank targets after a hypothetical bid
  lookup            Detailed view of a single player (drafted or available)
  roster            Show My Team's picks with bids paid
  budgets           Per-team budget status snapshot
  exclude           Add a player to the per-session exclude list
  sim               Run a season simulation with current rosters
  random            Auto-simulate one nomination + bidding round
  random til full   Auto-simulate the rest of the draft to completion
  go back           Revert the previous pick
  help              Show this command list
  exit              Save progress and exit (no final summary)
"""


def check_bid(raw, max_legal: int):
    """Validate a typed bid against the salary cap rules.

    Returns the integer bid on success, ``None`` after printing a
    diagnostic on failure. Accepts a leading ``$`` and surrounding
    whitespace for convenience. The cap (`max_legal`) is the result of
    ``max_bid(...)`` for the winning team -- a higher bid would leave
    them unable to fill the rest of their roster at the min bid.
    """
    if raw is None:
        return None
    text = str(raw).strip().lstrip("$").strip()
    if not text.isdigit():
        print("Invalid bid; must be a non-negative integer (e.g. 42).")
        return None
    bid = int(text)
    if bid > max_legal:
        print(f"Bid ${bid} exceeds the maximum legal bid (${max_legal}) "
              "for that team -- they wouldn't be able to fill the rest "
              "of their roster.")
        return None
    return bid


def check_team_name(league, raw):
    """Resolve a typed team name (or manager handle) to a canonical
    team name on ``league``. Returns the canonical name or ``None``."""
    names = [t["name"] for t in league.teams]
    managers = [t.get("manager") for t in league.teams]
    text = str(raw).strip()
    if text in names:
        return text
    if text in managers:
        return next(t["name"] for t in league.teams if t.get("manager") == text)
    print("Team name must be one of: " + ", ".join(n for n in names if n))
    return None


def setup_teams(league, customize: bool = False, already=()):
    """Rename teams (user's team becomes ``'My Team'``) and seed each
    with synthetic average-position rosters so ``season_sims`` has
    something to project before real picks come in.

    Unlike snake's ``provide_pick_order`` there's no draft slot to pick
    -- in salary cap every team can bid on every nomination, so team
    order is purely cosmetic. User's team goes first by convention.
    """
    already = list(already)
    my_team = [t for t in league.teams if t["name"] == league.name]
    other_teams = [t for t in league.teams if t["name"] != league.name]
    league.teams = my_team + other_teams

    avg_template = pd.concat(
        3 * [league.players.loc[
            league.players.player_id_sr.astype(str).str.startswith("avg_")
        ]],
        ignore_index=True, sort=False,
    )

    for i, team in enumerate(league.teams):
        old_name = team["name"]
        if old_name == league.name:
            new_name = "My Team"
        elif customize:
            new_name = input(f"What's the name of team #{i + 1}? ").strip() \
                       or f"Team #{i + 1}"
        elif len(already) == len(league.teams):
            new_name = str(already[i])
        else:
            new_name = f"Team #{i + 1}"

        league.schedule.loc[league.schedule.team_1 == old_name, "team_1"] = new_name
        league.schedule.loc[league.schedule.team_2 == old_name, "team_2"] = new_name
        team["name"] = new_name

        avg_template["fantasy_team"] = new_name
        league.players = pd.concat(
            [league.players, avg_template.copy()],
            ignore_index=True, sort=False,
        )
    return league


def _apply_pick(league, board, name: str, team_name: str, bid: int) -> None:
    """Mark ``name`` as drafted by ``team_name`` at ``bid`` on both the
    league projections (so season_sims sees it) and the cockpit board
    (so views and the bid math stay in sync).
    """
    league.players.loc[league.players.name == name, "fantasy_team"] = team_name
    league.players.loc[league.players.name == name, "actual_salary"] = bid
    if board is not None:
        board.loc[board["name"] == name, "fantasy_team"] = team_name
        board.loc[board["name"] == name, "winning_bid"] = bid


def _revert_pick(league, board, name: str) -> None:
    league.players.loc[league.players.name == name, "fantasy_team"] = None
    if "actual_salary" in league.players.columns:
        league.players.loc[league.players.name == name, "actual_salary"] = np.nan
    board.loc[board["name"] == name, "fantasy_team"] = pd.NA
    board.loc[board["name"] == name, "winning_bid"] = np.nan


def all_rosters_full(board: pd.DataFrame, num_teams: int, roster_size: int) -> bool:
    """Termination condition: every team has filled every roster slot.

    Counts only real picks -- the synthetic ``avg_`` seed rows for
    season_sims are dropped from the board at build time so they don't
    inflate the count here.
    """
    filled = board["fantasy_team"].dropna()
    return len(filled) >= num_teams * roster_size


def compute_max_legal_bid(
    board: pd.DataFrame, team_name: str,
    salary_cap: int, roster_size: int, min_bid: int = 1,
) -> int:
    """Max legal bid for ``team_name`` given current spent / open slots.

    Thin wrapper around ``tools.max_bid`` that pulls the team's state
    off the board. Returns 0 if the team has no open slots.
    """
    team_picks = board[board["fantasy_team"] == team_name]
    spent = int(team_picks["winning_bid"].fillna(0).sum())
    remaining = salary_cap - spent
    open_slots = roster_size - len(team_picks)
    return max_bid(remaining, open_slots, min_bid=min_bid)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="salary-cap-draft",
        description="Interactive salary cap draft cockpit (V2).",
    )
    p.add_argument("--team", required=True,
                   help="Yahoo team name to draft for")
    p.add_argument("--salary-cap", type=int, default=200, dest="salary_cap",
                   help="per-team salary cap (default $200)")
    p.add_argument("--min-bid", type=int, default=1, dest="min_bid",
                   help="minimum bid per player (default $1)")
    p.add_argument("--season", type=int, default=None,
                   help="Yahoo season year. Defaults to League's "
                        "auto-detect, which targets the most recently "
                        "completed season -- pass the upcoming season "
                        "explicitly when drafting pre-season.")
    p.add_argument("--keepers", default=None,
                   help="path to a keepers CSV (columns: name, "
                        "fantasy_team, salary)")
    p.add_argument("--exclude", default=None,
                   help="comma-separated players to exclude from views")
    p.add_argument("--inprogress", default=None,
                   help="path to a DraftProgressSalaryCap.csv from a "
                        "paused draft")
    p.add_argument("--output", default=None,
                   help="where to save draft progress (defaults to "
                        "--inprogress if provided, else "
                        "DraftProgressSalaryCap.csv)")
    p.add_argument("--payouts", default=None,
                   help="comma-separated 1st,2nd,3rd payouts")
    p.add_argument("--limit-per-position", type=int, default=5,
                   dest="limit_per_position",
                   help="rows per position in 'best' view")
    p.add_argument("--nominate-limit", type=int, default=10,
                   dest="nominate_limit",
                   help="rows in 'nominate' drain-score view")
    return p


def _print_df(df: pd.DataFrame, header: str) -> None:
    print(f"\n{header}")
    if df.empty:
        print("(no players)")
    else:
        print(df.to_string(index=False))


def _team_names(league) -> list[str]:
    return [t["name"] for t in league.teams]


def _save_progress(progress: pd.DataFrame, path: str) -> None:
    progress.to_csv(path, index=False)


def _load_progress(path: str) -> pd.DataFrame:
    """Load an --inprogress file. Accepts both the V2 format
    (name, fantasy_team, winning_bid) and the legacy V1 column name
    (``salary`` instead of ``winning_bid``) so users migrating from V1
    don't have to manually rename columns.
    """
    progress = pd.read_csv(path)
    if "winning_bid" not in progress.columns and "salary" in progress.columns:
        progress = progress.rename(columns={"salary": "winning_bid"})
    return progress[["name", "fantasy_team", "winning_bid"]]


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    # Lazy import so --help and helper unit tests work without Yahoo creds.
    import fantasyfb as fb

    league = fb.League(name=args.team, num_sims=10000, season=args.season)
    num_teams = len(league.teams)
    spec = _roster_spec_to_dict(league.roster_spots)
    bench = _bench_slots_from_spec(league.roster_spots)
    roster_size = sum(spec.values()) + bench
    payouts = parse_payouts(args.payouts, num_teams)
    exclude = [v.strip() for v in args.exclude.split(",")] if args.exclude else []

    league.players["fantasy_team"] = league.players.get("fantasy_team")
    if "actual_salary" not in league.players.columns:
        league.players["actual_salary"] = np.nan

    # Restore from --inprogress before building the board so the board's
    # initial fantasy_team / winning_bid columns are already populated.
    if args.inprogress and os.path.exists(args.inprogress):
        progress = _load_progress(args.inprogress)
        given_order = progress["fantasy_team"].dropna().drop_duplicates().tolist()
        league = setup_teams(league, already=given_order)
        for _, row in progress.iterrows():
            _apply_pick(league, board=None, name=row["name"],
                        team_name=row["fantasy_team"],
                        bid=int(row["winning_bid"]))
        output_path = args.output or args.inprogress
    else:
        custom = input("Would you like to provide custom team names? (y/n) ")
        league = setup_teams(league, customize=custom.lower() in ("yes", "y"))
        progress = pd.DataFrame(columns=["name", "fantasy_team", "winning_bid"])
        output_path = args.output or "DraftProgressSalaryCap.csv"

    # Keepers: apply to the league before building the board so they
    # show up in views correctly.
    if args.keepers and os.path.exists(args.keepers):
        keepers = pd.read_csv(args.keepers)
        bad_names = ~keepers["name"].isin(league.players["name"])
        if bad_names.any():
            print("Player names not found in projections, ignoring: "
                  + ", ".join(keepers.loc[bad_names, "name"].astype(str)))
            keepers = keepers[~bad_names]
        team_names = set(_team_names(league))
        bad_teams = ~keepers["fantasy_team"].isin(team_names)
        if bad_teams.any():
            print("Team names not in league, ignoring: "
                  + ", ".join(keepers.loc[bad_teams, "fantasy_team"].astype(str)))
            keepers = keepers[~bad_teams]
        for _, kp in keepers.iterrows():
            _apply_pick(league, board=None, name=kp["name"],
                        team_name=kp["fantasy_team"], bid=int(kp["salary"]))
            progress = pd.concat([progress, pd.DataFrame([{
                "name": kp["name"],
                "fantasy_team": kp["fantasy_team"],
                "winning_bid": int(kp["salary"]),
            }])], ignore_index=True)
        _save_progress(progress, output_path)

    board = cockpit.build_board(
        league.players, league.roster_spots, num_teams,
        salary_cap=args.salary_cap, min_bid=args.min_bid,
    )
    # Replay applied picks onto the board (build_board snapshots the
    # pool but doesn't know about winning_bid).
    for _, row in progress.iterrows():
        mask = board["name"] == row["name"]
        board.loc[mask, "fantasy_team"] = row["fantasy_team"]
        board.loc[mask, "winning_bid"] = int(row["winning_bid"])

    _enable_completion()

    while not all_rosters_full(board, num_teams, roster_size):
        available_names = league.players.loc[
            league.players.fantasy_team.isnull(), "name"
        ].dropna().tolist()
        _set_completion_candidates(list(_PICK_COMMANDS) + available_names)

        pick_name = check_pick_name(
            league, input("\nPlayer Up For Grabs: "), _PICK_COMMANDS,
        )
        while pick_name is None:
            pick_name = check_pick_name(
                league, input("\nPlayer Up For Grabs: "), _PICK_COMMANDS,
            )

        if pick_name == "best":
            _print_df(
                cockpit.view_best(
                    board, my_team="My Team",
                    salary_cap=args.salary_cap, num_teams=num_teams,
                    roster_spec=league.roster_spots,
                    exclude=exclude,
                    limit_per_position=args.limit_per_position,
                    min_bid=args.min_bid,
                ),
                "Best targets (need-adjusted, with $ caps):",
            )

        elif pick_name == "nominate":
            _print_df(
                cockpit.view_nominate(
                    board, my_team="My Team",
                    salary_cap=args.salary_cap, num_teams=num_teams,
                    roster_spec=league.roster_spots,
                    exclude=exclude, limit=args.nominate_limit,
                ),
                "Drain candidates (high $ value + low fit for you):",
            )

        elif pick_name == "whatif":
            _set_completion_candidates(["nevermind"] + available_names)
            target = check_pick_name(
                league, input("Hypothetical player: "), ("nevermind",),
            )
            while target is None:
                target = check_pick_name(
                    league, input("Hypothetical player: "), ("nevermind",),
                )
            if target == "nevermind":
                continue
            _set_completion_candidates(_team_names(league))
            winner = check_team_name(league, input("Hypothetical winner: "))
            while winner is None:
                winner = check_team_name(league, input("Hypothetical winner: "))
            max_legal = compute_max_legal_bid(
                board, winner, args.salary_cap, roster_size, args.min_bid,
            )
            bid = check_bid(input(f"Hypothetical bid ($, max ${max_legal}): "),
                            max_legal)
            while bid is None:
                bid = check_bid(
                    input(f"Hypothetical bid ($, max ${max_legal}): "),
                    max_legal,
                )
            _print_df(
                cockpit.view_what_if(
                    board, name=target, bid=bid, winning_team=winner,
                    my_team="My Team", salary_cap=args.salary_cap,
                    num_teams=num_teams, roster_spec=league.roster_spots,
                    limit_per_position=args.limit_per_position,
                    min_bid=args.min_bid,
                ),
                f"If {winner} wins {target} at ${bid}, best becomes:",
            )

        elif pick_name == "lookup":
            _set_completion_candidates(
                ["nevermind"] + league.players["name"].dropna().tolist(),
            )
            focus = check_pick_name(
                league, input("Which player? "), ("nevermind",),
            )
            while focus is None:
                focus = check_pick_name(
                    league, input("Which player? "), ("nevermind",),
                )
            if focus != "nevermind":
                _print_df(
                    cockpit.view_lookup(
                        board, focus,
                        my_team="My Team", salary_cap=args.salary_cap,
                        num_teams=num_teams, roster_spec=league.roster_spots,
                        min_bid=args.min_bid,
                    ),
                    f"Lookup: {focus}",
                )

        elif pick_name == "roster":
            _print_df(cockpit.view_roster(board, "My Team"), "My Team:")

        elif pick_name == "budgets":
            _print_df(
                cockpit.view_budget_status(
                    board, _team_names(league),
                    salary_cap=args.salary_cap,
                    roster_spec=league.roster_spots,
                    min_bid=args.min_bid,
                ),
                "Per-team budgets:",
            )

        elif pick_name == "exclude":
            _set_completion_candidates(["nevermind"] + available_names)
            ignore = check_pick_name(
                league, input("Exclude which player? "), ("nevermind",),
            )
            while ignore is None:
                ignore = check_pick_name(
                    league, input("Exclude which player? "), ("nevermind",),
                )
            if ignore != "nevermind":
                exclude.append(ignore)

        elif pick_name == "random":
            try:
                name, winner, price = cockpit.simulate_nomination(
                    board, team_names=_team_names(league),
                    salary_cap=args.salary_cap,
                    roster_spec=league.roster_spots,
                    min_bid=args.min_bid,
                )
            except ValueError as exc:
                print(str(exc))
                continue
            print(f"Auto-pick: {winner} wins {name} for ${price}")
            _apply_pick(league, board, name, winner, price)
            progress = pd.concat([progress, pd.DataFrame([{
                "name": name, "fantasy_team": winner, "winning_bid": price,
            }])], ignore_index=True)
            _save_progress(progress, output_path)

        elif pick_name == "random til full":
            # Single RNG so the burst feels coherent (the seeds in
            # individual auctions are correlated rather than independent
            # restarts). Outer loop terminates when the board fills up.
            rng = np.random.default_rng()
            auto_count = 0
            while not all_rosters_full(board, num_teams, roster_size):
                try:
                    name, winner, price = cockpit.simulate_nomination(
                        board, team_names=_team_names(league),
                        salary_cap=args.salary_cap,
                        roster_spec=league.roster_spots,
                        min_bid=args.min_bid, rng=rng,
                    )
                except ValueError as exc:
                    print(str(exc))
                    break
                _apply_pick(league, board, name, winner, price)
                progress = pd.concat([progress, pd.DataFrame([{
                    "name": name, "fantasy_team": winner, "winning_bid": price,
                }])], ignore_index=True)
                auto_count += 1
            _save_progress(progress, output_path)
            print(f"Auto-simulated {auto_count} nominations.")

        elif pick_name == "go back":
            if progress.empty:
                print("No picks to revert.")
                continue
            last = progress.iloc[-1]
            _revert_pick(league, board, last["name"])
            progress = progress.iloc[:-1].reset_index(drop=True)
            _save_progress(progress, output_path)

        elif pick_name == "sim":
            standings = league.season_sims(payouts=payouts)[1]
            print(standings[["team", "points_avg", "wins_avg",
                             "playoffs", "winner", "earnings"]]
                  .to_string(index=False))

        elif pick_name == "help":
            print(_HELP_TEXT)

        elif pick_name == "exit":
            print(f"Exiting draft. Progress saved to {output_path}.")
            return 0

        elif pick_name in league.players.name.tolist():
            # Real nomination: show the player's full context, then
            # collect winning team + winning bid and apply the pick.
            _print_df(
                cockpit.view_lookup(
                    board, pick_name,
                    my_team="My Team", salary_cap=args.salary_cap,
                    num_teams=num_teams, roster_spec=league.roster_spots,
                    min_bid=args.min_bid,
                ),
                f"Lookup: {pick_name}",
            )

            _set_completion_candidates(_team_names(league))
            winner = check_team_name(league, input("Who picked them? "))
            while winner is None:
                winner = check_team_name(league, input("Who picked them? "))

            max_legal = compute_max_legal_bid(
                board, winner, args.salary_cap, roster_size, args.min_bid,
            )
            bid = check_bid(
                input(f"Winning bid ($, max ${max_legal}): "), max_legal,
            )
            while bid is None:
                bid = check_bid(
                    input(f"Winning bid ($, max ${max_legal}): "), max_legal,
                )

            _apply_pick(league, board, pick_name, winner, bid)
            progress = pd.concat([progress, pd.DataFrame([{
                "name": pick_name,
                "fantasy_team": winner,
                "winning_bid": bid,
            }])], ignore_index=True)
            _save_progress(progress, output_path)

    standings = league.season_sims(payouts=payouts)[1]
    print(standings[["team", "points_avg", "wins_avg",
                     "playoffs", "winner", "earnings"]]
          .to_string(index=False))
    standings.to_csv("DraftResults.csv", index=False)

    my_results = standings.reset_index(drop=True).loc[standings.team == "My Team"]
    rank = my_results.index[0]
    n = standings.shape[0]
    if rank < n / 4:
        print("You crushed it!!! Way to go!!!")
    elif rank < n / 2:
        print("Pretty darn good, but we'll see... Good luck!!!")
    elif rank < 3 * n / 4:
        print("Not great, but you can recover... Hit the waiver wire hard!!!")
    else:
        print("Less than ideal... but you have so many other redeeming qualities!!!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
