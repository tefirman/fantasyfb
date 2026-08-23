#!/usr/bin/env python
"""Live snake-draft cockpit (redraft, V2).

Wraps the interactive pick loop around draft_cockpit's pure view helpers.
Replaces the old per-pick possible_adds Monte Carlo (10k full-season sims
per candidate) with a VORP/tier/ADP board that's instant on the clock.

Removed vs V1:
    name_corrections.csv HTTP fetch           (Yahoo<->NFL linkage by id
                                               already happens upstream)

New required arg:
    --adp PATH    FantasyPros-style ADP CSV
                  (columns Player / POS / Team / AVG, configurable below)

Commands during the draft (also available via the `help` command):
    <player name>  Mark the player as taken by the active team
    best           Top-N available per position. Prompts for pool (best
                   available vs. nearest ADP) and, outside --bestball
                   drafts, for scoring (normal vs. bestball upside)
    lookup         Detailed view of a single player
    exclude        Add a player to the per-session exclude list
    roster         My current roster
    sim            Full season-sim of current rosters
    simadd         Sim top-N available per position; ranks by win/playoff/
                   earnings delta. Same pool/scoring prompts as 'best',
                   plus a players-per-position count (best-available pool only)
    random         Auto-pick for the team currently on the clock
    random til me  Auto-pick for every team until your turn
    go back        Revert the previous pick
    help           Show the command list
    exit           Save progress and exit (no final summary)
"""

from __future__ import annotations

import argparse
import os
import sys
from difflib import SequenceMatcher
from typing import Iterable, Optional

import numpy as np
import pandas as pd

# readline gives input() history (up/down arrows, Ctrl-R) and tab-completion
# for free. Unix-only; on Windows the import fails and we just lose the
# polish without breaking the cockpit.
try:
    import readline
except ImportError:  # pragma: no cover -- Windows-only fallback
    readline = None

from . import snake_cockpit as cockpit
from .tools import round_direction


_PICK_COMMANDS = (
    "best", "lookup", "exclude", "go back", "sim", "simadd", "roster",
    "random", "random til me", "help", "exit",
)


# Completion pool for the next input() call. Mutable module-level state
# because readline's completer hook can't take extra args -- the cockpit
# updates this list before each prompt to reflect what's reasonable to
# type at that moment.
_completion_candidates: list[str] = []


def _completer(text: str, state: int) -> "str | None":
    """readline completer hook: return the `state`-th match for `text`.

    Case-insensitive prefix match against ``_completion_candidates``.
    Returning None signals "no more matches", which is how readline
    knows when to stop calling.
    """
    lowered = text.lower()
    matches = [c for c in _completion_candidates
               if c.lower().startswith(lowered)]
    if state < len(matches):
        return matches[state]
    return None


def _enable_completion() -> None:
    """Wire up the completer hook once at startup. Setting completer_delims
    to empty so player names with spaces ('Justin Jefferson') complete as
    one unit -- the default delimiters include whitespace, which would
    otherwise truncate completion at the first space.

    macOS ships Python linked against libedit rather than GNU readline,
    and the two use different parse_and_bind syntaxes. Without the libedit
    detection below, tab on macOS would just insert a literal tab
    character rather than triggering completion.
    """
    if readline is None:
        return
    readline.set_completer(_completer)
    readline.set_completer_delims("")
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def _set_completion_candidates(names: Iterable[str]) -> None:
    """Replace the completion pool used by the next input() prompt."""
    global _completion_candidates
    _completion_candidates = sorted({str(n) for n in names if n})


_HELP_TEXT = """
Commands during the draft:
  <player name>   Draft this player for the team on the clock
  best            Top-N available per position by need-adjusted VORP.
                  Prompts for pool (best available / nearest ADP) and,
                  outside --bestball drafts, scoring (normal / bestball)
  lookup          Detailed view of one player
  exclude         Add a player to the per-session exclude list
  roster          Show My Team's current picks
  sim             Run a full season simulation with current rosters
  simadd          Sim top-N available per position; rank by win/playoff/earnings delta.
                  Same pool/scoring prompts as 'best', plus players-per-position count
                  (best-available pool only)
  random          Auto-pick for the team currently on the clock
  random til me   Auto-pick for everyone until it's your turn again
  go back         Revert the previous pick
  help            Show this command list
  exit            Save progress and exit the draft (no final summary)
"""


def check_pick_value(league, pick):
    pick = str(pick)
    if not pick.strip().isnumeric():
        print("Invalid pick value, must be numeric.")
        return None
    if int(pick.strip()) < 1 or int(pick.strip()) > len(league.teams):
        print(f"Invalid pick value, must be between 1 and {len(league.teams)}.")
        return None
    return int(pick.strip())


def check_pick_name(league, pick_name, exceptions=()):
    """Resolve a user-typed string against the player pool / command list.

    Returns the canonical player name if it matches an available player,
    the lower-cased command if it matches one in `exceptions`, or None
    after printing a fuzzy-match suggestion list.
    """
    available = league.players[league.players.fantasy_team.isnull()]
    taken = league.players[~league.players.fantasy_team.isnull()]
    lowered = pick_name.lower().strip()

    if pick_name in available.name.tolist():
        return pick_name
    if lowered in {e.lower() for e in exceptions}:
        return lowered

    if pick_name in taken.name.tolist():
        team = taken.loc[taken.name == pick_name, "fantasy_team"].values[0]
        print(f"Player has already been taken by {team}.")
        return None

    options = available.copy()
    options["similarity"] = options.name.apply(
        lambda x: SequenceMatcher(None, x, pick_name).ratio()
    )
    print("Can't find the player you provided. Closest options:")
    print(options.sort_values(by="similarity", ascending=False)
                 .iloc[:3][["name", "position", "current_team"]]
                 .to_string(index=False))
    return None


def _prompt_choice(question: str, choices: tuple, default: str) -> str:
    """Prompt for one of `choices` (case-insensitive), re-prompting on
    anything else. Blank input accepts `default`. The literal choice words
    are appended to `question` so it's always clear exactly what to type,
    e.g. "Pool? (best/nearest) [best] ".
    """
    lowered_choices = {c.lower(): c for c in choices}
    prompt = f"{question} ({'/'.join(choices)}) [{default}] "
    while True:
        raw = input(prompt).strip().lower()
        if not raw:
            return default
        if raw in lowered_choices:
            return lowered_choices[raw]
        print(f"Please enter one of: {', '.join(choices)}")


def _prompt_int(question: str, default: int) -> int:
    """Prompt for a positive integer, re-prompting on anything else.
    Blank input accepts `default`.
    """
    prompt = f"{question} [{default}] "
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive whole number.")


def provide_pick_order(league, customize=False, already=()):
    """Set the draft slot for the user, rename teams in pick order, and
    seed each fantasy team with synthetic average-position rosters so
    season_sims has something to work with before real picks come in.
    """
    already = list(already)
    if "My Team" in already and len(already) == len(league.teams):
        my_pick = already.index("My Team") + 1
    else:
        my_pick = check_pick_value(league, input("Which pick are you? "))
        while my_pick is None:
            my_pick = check_pick_value(league, input("Which pick are you? "))

    my_team = [t for t in league.teams if t["name"] == league.name]
    other_teams = [t for t in league.teams if t["name"] != league.name]
    league.teams = other_teams[:my_pick - 1] + my_team + other_teams[my_pick - 1:]

    avg_template = pd.concat(
        3 * [league.players.loc[
            league.players.player_id_sr.astype(str).str.startswith("avg_")
        ]],
        ignore_index=True, sort=False,
    )

    for pick in range(len(league.teams)):
        if pick + 1 == my_pick:
            pick_name = "My Team"
        elif customize:
            pick_name = input(f"Who has pick #{pick + 1}? ")
        elif len(already) == len(league.teams):
            pick_name = str(already[pick])
        else:
            pick_name = f"Team #{pick + 1}"

        old_name = league.teams[pick]["name"]
        league.schedule.loc[league.schedule.team_1 == old_name, "team_1"] = pick_name
        league.schedule.loc[league.schedule.team_2 == old_name, "team_2"] = pick_name
        league.teams[pick]["name"] = pick_name

        avg_template["fantasy_team"] = pick_name
        league.players = pd.concat(
            [league.players, avg_template.copy()],
            ignore_index=True, sort=False,
        )
    return league


def snake_pick_slot(pick_index: int, num_teams: int, reversal_round: int = 0) -> int:
    """0-indexed team slot owning the given 0-indexed overall pick under
    snake ordering, optionally with Third-Round Reversal applied.
    """
    rnd = pick_index // num_teams
    slot = pick_index % num_teams
    if round_direction(rnd + 1, reversal_round) == 1:
        slot = num_teams - 1 - slot
    return slot


def _apply_pick(league, board, name, team_name):
    """Mark `name` as drafted by `team_name` on both the league projections
    and the cockpit board so views and sims stay in sync.
    """
    league.players.loc[league.players.name == name, "fantasy_team"] = team_name
    board.loc[board["name"] == name, "fantasy_team"] = team_name


def _revert_pick(league, board, name):
    league.players.loc[league.players.name == name, "fantasy_team"] = None
    board.loc[board["name"] == name, "fantasy_team"] = pd.NA


def parse_payouts(raw, num_teams: int):
    default = [100 * num_teams * 0.6, 100 * num_teams * 0.3, 100 * num_teams * 0.1]
    if not raw:
        return default
    parts = [p.strip() for p in str(raw).split(",")]
    if not all(p.replace(".", "", 1).isdigit() for p in parts):
        print("Weird values provided for payouts... Assuming standard payouts...")
        return default
    payouts = [float(p) for p in parts][:3]
    if len(parts) > 3:
        print("Too many values provided for payouts... Only using top three...")
    return payouts


def parse_roster_spots(raw: Optional[str]) -> Optional[pd.DataFrame]:
    """Parse a "POS=count,POS=count,..." string (e.g. "QB=1,RB=2,W/R/T=2,
    Q/W/R/T=1,BN=6") into the position/count DataFrame GenericClient's
    roster_spots expects (see issue #59). Position codes aren't validated
    here -- GenericClient.__init__ raises ValueError on an unrecognized
    one, same error path whether the spec came from this CLI or the
    Python API directly.

    Returns:
        None if `raw` is falsy (caller should fall back to the platform
        default). Raises ValueError on malformed "POS=count" syntax or a
        non-positive-integer count.
    """
    if not raw:
        return None
    positions, counts = [], []
    for part in str(raw).split(","):
        part = part.strip()
        if "=" not in part:
            raise ValueError(
                f"Malformed roster spot {part!r} -- expected POSITION=COUNT"
            )
        pos, _, count = part.partition("=")
        pos, count = pos.strip(), count.strip()
        if not count.isdigit() or int(count) <= 0:
            raise ValueError(
                f"Malformed roster spot {part!r} -- count must be a positive whole number"
            )
        positions.append(pos)
        counts.append(int(count))
    return pd.DataFrame({"position": positions, "count": counts})


def _prompt_roster_spots() -> Optional[pd.DataFrame]:
    """Interactively prompt for a custom roster spec, same yes/no-then-detail
    shape as the custom-draft-order prompt. Re-prompts on malformed input
    rather than silently falling back, since a typo here should be caught
    immediately rather than producing a confusing draft later."""
    custom = input("Would you like to provide a custom roster spec? ")
    if custom.strip().lower() not in ("yes", "y"):
        return None
    print(
        "Enter roster spots as POSITION=COUNT pairs separated by commas, "
        "e.g. QB=1,RB=2,WR=2,TE=1,W/R/T=1,K=1,DEF=1,BN=7 "
        "(flex codes: W/T, W/R/T, Q/W/R/T for superflex)."
    )
    while True:
        raw = input("Roster spec: ")
        try:
            return parse_roster_spots(raw)
        except ValueError as exc:
            print(exc)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="snake_draft",
        description="Interactive snake-draft cockpit (redraft, V2).",
    )
    p.add_argument("--team", required=True,
                   help="team to draft for -- Yahoo team name (--platform "
                        "yahoo), the Sleeper team/manager display name "
                        "to identify your roster (--platform sleeper), or "
                        "whatever you want to call your team (--platform "
                        "generic)")
    p.add_argument("--adp", required=True,
                   help="path to ADP CSV (FantasyPros-style by default)")
    p.add_argument("--season", type=int, default=None,
                   help="Yahoo season year to connect to. Defaults to "
                        "fantasyfb.League's auto-detect, which targets the "
                        "most recently completed season -- pass the upcoming "
                        "season explicitly when drafting before the NFL "
                        "season starts (e.g. --season 2026 in May 2026). "
                        "Ignored with --platform sleeper/generic, since "
                        "neither is tied to a real, season-scoped league.")
    p.add_argument("--platform", default="generic",
                   choices=["yahoo", "sleeper", "generic"],
                   help="fantasy platform backend to draft against. "
                        "Defaults to 'generic' -- a fully synthetic mock "
                        "draft with no real Yahoo/Sleeper league, useful "
                        "for sanity-checking VORP rankings against a "
                        "scoring system you already have intuition for "
                        "(see issue #47). Pass 'yahoo' or 'sleeper' to "
                        "draft against a real league instead.")
    p.add_argument("--sleeper-league-id", default=None,
                   dest="sleeper_league_id",
                   help="numeric Sleeper league ID (from the league URL), "
                        "required with --platform sleeper")
    p.add_argument("--num-teams", type=int, default=None, dest="num_teams",
                   help="number of teams for a --platform generic mock "
                        "draft (default 12). Prompted for interactively "
                        "if not given.")
    p.add_argument("--mock-scoring", default=None, dest="mock_scoring",
                   choices=["standard", "half_ppr", "ppr"],
                   help="scoring system for a --platform generic mock "
                        "draft (default ppr). Prompted for interactively "
                        "if not given.")
    p.add_argument("--roster-spots", default=None, dest="roster_spots",
                   help="custom roster shape for a --platform generic mock "
                        "draft, as comma-separated POSITION=COUNT pairs, "
                        "e.g. 'QB=1,RB=2,WR=2,TE=1,W/R/T=1,K=1,DEF=1,BN=7' "
                        "(flex codes: W/T, W/R/T, Q/W/R/T for superflex; "
                        "see issue #59). Defaults to the fixed roster shape "
                        "for --mock-scoring; prompted for interactively if "
                        "not given.")
    p.add_argument("--fresh-draft", action="store_true", dest="fresh_draft",
                   help="ignore each team's current roster and treat every "
                        "player as available. Existing rosters are normally "
                        "preserved as keepers (useful for an in-progress "
                        "Yahoo league); pass this to mock-draft against a "
                        "league that's already mid-season -- e.g. a Sleeper "
                        "league you're borrowing settings/player-pool from "
                        "but that already has real rosters from its own "
                        "draft.")
    p.add_argument("--exclude", default=None,
                   help="comma-separated players to exclude from views")
    p.add_argument("--inprogress", default=None,
                   help="path to a DraftProgress.csv from a paused draft")
    p.add_argument("--output", default=None,
                   help="where to save draft progress (defaults to "
                        "--inprogress if provided, else DraftProgress.csv)")
    p.add_argument("--payouts", default=None,
                   help="comma-separated 1st,2nd,3rd payouts")
    p.add_argument("--adp-name-col", default="Player", dest="adp_name_col")
    p.add_argument("--adp-pos-col", default="POS", dest="adp_pos_col")
    p.add_argument("--adp-team-col", default="Team", dest="adp_team_col")
    p.add_argument("--adp-avg-col", default="AVG", dest="adp_avg_col")
    p.add_argument("--limit-per-position", type=int, default=5,
                   dest="limit_per_position",
                   help="rows per position in 'best' view")
    p.add_argument("--simadd-limit", type=int, default=3,
                   dest="simadd_limit",
                   help="default players per position to simulate in 'simadd' "
                        "(default 3); 'simadd' also prompts per-run to override this")
    p.add_argument("--bestball", nargs="?", const="underdog", default="",
                   metavar="PLATFORM",
                   help="enable best-ball scoring/roster settings. Optionally pass "
                        "a platform name (underdog, dk). Bare --bestball defaults "
                        "to 'underdog'. Switches sim and simadd to use bestball_sims.")
    p.add_argument("--nearest-window", type=int, default=2,
                   dest="nearest_window",
                   help="ADP window in rounds for the 'nearest' view and "
                        "for the 'random' command's candidate pool")
    p.add_argument("--random-pool-size", type=int, default=8,
                   dest="random_pool_size",
                   help="size of the top-VORP pool (within the ADP window, "
                        "see --nearest-window) the 'random' command "
                        "samples from (default 8). Smaller = more "
                        "deterministic auto-picks; larger = more chaos.")
    p.add_argument("--reversal-round", type=int, default=0,
                   dest="reversal_round",
                   help="apply Third-Round Reversal at this round number "
                        "(the round repeats the previous round's direction "
                        "instead of flipping back, then normal alternation "
                        "resumes -- matches Sleeper's draft 'reversal_round' "
                        "setting). Default 0 = disabled, plain snake.")
    p.add_argument("--refresh-cache", action="store_true", dest="refresh_cache",
                   help="bypass the local nflreadpy cache and force a fresh "
                        "download of stats/schedule/roster data for this run")
    return p


def _print_df(df: pd.DataFrame, header: str) -> None:
    print(f"\n{header}")
    if df.empty:
        print("(no players)")
    else:
        print(df.to_string(index=False))


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.platform == "sleeper" and not args.sleeper_league_id:
        print("--sleeper-league-id is required with --platform sleeper")
        return 1

    num_teams = args.num_teams
    mock_scoring = args.mock_scoring
    try:
        roster_spots = parse_roster_spots(args.roster_spots)
    except ValueError as exc:
        print(exc)
        return 1
    if args.platform == "generic":
        if num_teams is None:
            num_teams = _prompt_int("How many teams?", 12)
        if mock_scoring is None:
            mock_scoring = _prompt_choice(
                "Scoring system?", ("standard", "half_ppr", "ppr"), "ppr",
            )
        if roster_spots is None:
            roster_spots = _prompt_roster_spots()

    # Lazy import so `--help` and the helper unit tests work without
    # Yahoo creds / yahoo_fantasy_api installed.
    import fantasyfb as fb
    from fantasyfb.data.nflreadpy_provider import NflreadpyProvider

    league = fb.League(
        name=args.team, num_sims=10000, season=args.season,
        bestball=args.bestball, platform=args.platform,
        sleeper_league_id=args.sleeper_league_id,
        num_teams=num_teams or 12, mock_scoring=mock_scoring or "ppr",
        roster_spots=roster_spots,
        nfl_provider=NflreadpyProvider(refresh=args.refresh_cache),
    )
    num_teams = len(league.teams)
    num_spots = league.roster_spots.loc[
        league.roster_spots.position != "IR", "count"
    ].sum()
    tot_picks = num_teams * num_spots
    payouts = parse_payouts(args.payouts, num_teams)
    exclude = [v.strip() for v in args.exclude.split(",")] if args.exclude else []

    # Preserve existing fantasy_team values (keepers / restored picks
    # from --inprogress) before build_board snapshots the pool -- unless
    # --fresh-draft says to disregard whatever's currently rostered
    # (e.g. mock-drafting against a Sleeper league that's already
    # mid-season and has real, non-keeper rosters from its own draft).
    if args.fresh_draft:
        league.players["fantasy_team"] = None
    else:
        league.players["fantasy_team"] = league.players.get("fantasy_team")

    if args.inprogress and os.path.exists(args.inprogress):
        progress = pd.read_csv(args.inprogress)
        pick_num = progress.shape[0]
        given_order = progress.iloc[:progress.fantasy_team.nunique()] \
                              .fantasy_team.tolist()
        league = provide_pick_order(league, already=given_order)
        league.players = pd.merge(
            left=league.players,
            right=progress[["player_id_sr", "fantasy_team"]],
            how="left", on="player_id_sr", suffixes=("", "_prev"),
        )
        picked = ~league.players.fantasy_team_prev.isnull()
        league.players.loc[picked, "fantasy_team"] = (
            league.players.loc[picked, "fantasy_team_prev"]
        )
        del league.players["fantasy_team_prev"]
        output_path = args.output or args.inprogress
    else:
        custom_order = input("Would you like to provide a custom draft order? ")
        league = provide_pick_order(league, custom_order.lower() in ("yes", "y"))
        pick_num = 0
        progress = pd.DataFrame()
        output_path = args.output or "DraftProgress.csv"

    board = cockpit.build_board(
        league.players, league.roster_spots, num_teams,
        adp_csv_path=args.adp,
        name_col=args.adp_name_col, adp_col=args.adp_avg_col,
        position_col=args.adp_pos_col, team_col=args.adp_team_col,
    )

    _enable_completion()

    _sim_baseline = None  # cached baseline standings for simadd; invalidated on each pick

    while pick_num < tot_picks:
        round_num = pick_num // num_teams + 1
        slot = snake_pick_slot(pick_num, num_teams, args.reversal_round)
        prompt = (f"Round #{round_num}, Pick #{pick_num + 1}, "
                  f"{league.teams[slot]['name']}: ")

        # Refresh completion candidates: only-still-available players plus
        # the in-draft commands. Drafted players drop off automatically as
        # the user picks them.
        available_names = league.players.loc[
            league.players.fantasy_team.isnull(), "name"
        ].dropna().tolist()
        _set_completion_candidates(list(_PICK_COMMANDS) + available_names)

        pick_name = check_pick_name(league, input(prompt), _PICK_COMMANDS)
        while pick_name is None:
            pick_name = check_pick_name(league, input(prompt), _PICK_COMMANDS)

        if pick_name in league.players.name.tolist():
            team_name = league.teams[slot]["name"]
            _apply_pick(league, board, pick_name, team_name)
            progress = pd.concat(
                [progress, league.players.loc[league.players.name == pick_name]],
                ignore_index=True, sort=False,
            )
            progress.to_csv(output_path, index=False)
            pick_num += 1
            _sim_baseline = None

        elif pick_name == "best":
            my_roster = cockpit.build_my_roster(
                board, "My Team", league.roster_spots,
            )
            pool = _prompt_choice(
                "Pool -- best available or nearest ADP?",
                ("best", "nearest"), "best",
            )
            # Bestball scoring is mandatory once the whole draft is running
            # in bestball mode; otherwise it's an optional upside lens.
            if args.bestball:
                bestball_scoring = True
            else:
                bestball_scoring = _prompt_choice(
                    "Scoring -- normal or bestball (upside-weighted)?",
                    ("normal", "bestball"), "normal",
                ) == "bestball"

            if pool == "nearest":
                view_fn = cockpit.view_nearestbestball if bestball_scoring else cockpit.view_nearest
                result = view_fn(
                    board, pick_overall=pick_num + 1, num_teams=num_teams,
                    exclude=exclude, window_rounds=args.nearest_window,
                    my_roster=my_roster,
                )
                label = (f"Available within next {args.nearest_window} rounds of ADP "
                          f"({'best-ball VORP, upside-weighted' if bestball_scoring else 'need-adjusted'}):")
            else:
                view_fn = cockpit.view_bestball if bestball_scoring else cockpit.view_best
                result = view_fn(
                    board, exclude=exclude,
                    limit_per_position=args.limit_per_position,
                    my_roster=my_roster,
                )
                label = (f"Best available by need-adjusted "
                          f"{'best-ball VORP (upside-weighted)' if bestball_scoring else 'VORP'}:")
            _print_df(result, label)

        elif pick_name == "lookup":
            # Lookup completion includes drafted players too -- the
            # cockpit happily shows you who already owns them.
            _set_completion_candidates(
                ["nevermind"]
                + league.players["name"].dropna().tolist()
            )
            focus = check_pick_name(
                league, input("Which player would you like to check? "),
                ("nevermind",),
            )
            while focus is None:
                focus = check_pick_name(
                    league, input("Which player would you like to check? "),
                    ("nevermind",),
                )
            if focus != "nevermind":
                _print_df(cockpit.view_lookup(board, focus),
                          f"Lookup: {focus}")

        elif pick_name == "exclude":
            # Exclude only makes sense for available players.
            available_names = league.players.loc[
                league.players.fantasy_team.isnull(), "name"
            ].dropna().tolist()
            _set_completion_candidates(["nevermind"] + available_names)
            ignore = check_pick_name(
                league,
                input("Which player would you like to exclude from "
                      "consideration? "),
                ("nevermind",),
            )
            while ignore is None:
                ignore = check_pick_name(
                    league,
                    input("Which player would you like to exclude from "
                          "consideration? "),
                    ("nevermind",),
                )
            if ignore != "nevermind":
                exclude.append(ignore)

        elif pick_name == "go back":
            if progress.empty:
                print("No picks to revert.")
                continue
            last_name = progress.iloc[-1]["name"]
            _revert_pick(league, board, last_name)
            progress = progress.iloc[:-1].reset_index(drop=True)
            progress.to_csv(output_path, index=False)
            pick_num -= 1
            _sim_baseline = None

        elif pick_name == "sim":
            if args.bestball:
                _sim_baseline = league.bestball_sims(payouts=payouts)
            else:
                _sim_baseline = league.season_sims(payouts=payouts)[1]
            print(_sim_baseline[["team", "points_avg", "wins_avg",
                                  "playoffs", "winner", "earnings"]]
                  .to_string(index=False))

        elif pick_name == "simadd":
            my_roster = cockpit.build_my_roster(board, "My Team", league.roster_spots)
            pool = _prompt_choice(
                "Pool -- best available or nearest ADP?",
                ("best", "nearest"), "best",
            )
            # Bestball scoring is mandatory once the whole draft is running
            # in bestball mode; otherwise it's an optional upside lens for
            # spotting bench-relevant players a normal sim can't tell apart.
            if args.bestball:
                bestball_scoring = True
            else:
                bestball_scoring = _prompt_choice(
                    "Candidate ranking -- normal or bestball (upside-weighted)?",
                    ("normal", "bestball"), "normal",
                ) == "bestball"

            if pool == "nearest":
                view_fn = cockpit.view_nearestbestball if bestball_scoring else cockpit.view_nearest
                candidates = view_fn(
                    board, pick_overall=pick_num + 1, num_teams=num_teams,
                    exclude=exclude, window_rounds=args.nearest_window,
                    my_roster=my_roster,
                )["name"].tolist()
            else:
                sim_limit = _prompt_int(
                    "Players per position to simulate?", args.simadd_limit,
                )
                view_fn = cockpit.view_bestball if bestball_scoring else cockpit.view_best
                candidates = view_fn(
                    board, exclude=exclude,
                    limit_per_position=sim_limit,
                    my_roster=my_roster,
                )["name"].tolist()
            candidates = [c for c in candidates
                          if league.players.loc[league.players.name == c, "position"]
                          .isin(["K", "DEF"]).sum() == 0]
            def _run_sims():
                if args.bestball:
                    return league.bestball_sims(payouts=payouts)
                return league.season_sims(payouts=payouts)[1]

            orig_num_sims = league.num_sims
            league.num_sims = 1000
            print("Running baseline sim...")
            if _sim_baseline is None:
                _sim_baseline = _run_sims()
            baseline_row = _sim_baseline.loc[_sim_baseline.team == "My Team"]
            delta_cols = ["wins_avg", "points_avg", "playoffs", "winner", "runner_up", "earnings"]
            delta_cols = [c for c in delta_cols if c in _sim_baseline.columns]
            rows = []
            for candidate in candidates:
                print(f"  Simulating {candidate}...")
                league.players.loc[league.players.name == candidate, "fantasy_team"] = "My Team"
                new_standings = _run_sims()
                league.players.loc[league.players.name == candidate, "fantasy_team"] = None
                row = {"name": candidate}
                for col in delta_cols:
                    row[col] = round(
                        new_standings.loc[new_standings.team == "My Team", col].values[0]
                        - baseline_row[col].values[0], 3
                    )
                rows.append(row)
            league.num_sims = orig_num_sims
            if rows:
                sort_col = "winner" if "winner" in delta_cols else delta_cols[-1]
                result = pd.DataFrame(rows).sort_values(sort_col, ascending=False)
                _print_df(result, "Simulated impact of adding each player (delta from baseline):")

        elif pick_name == "roster":
            _print_df(cockpit.view_roster(board, "My Team"),
                      "My Team:")

        elif pick_name == "random":
            team_name = league.teams[slot]["name"]
            auto_name = cockpit.random_pick(
                board, team_name=team_name,
                roster_spec=league.roster_spots,
                exclude=exclude,
                pool_size=args.random_pool_size,
                pick_overall=pick_num + 1, num_teams=num_teams,
                window_rounds=args.nearest_window,
            )
            print(f"Auto-drafting {auto_name} for {team_name}")
            _apply_pick(league, board, auto_name, team_name)
            progress = pd.concat(
                [progress, league.players.loc[league.players.name == auto_name]],
                ignore_index=True, sort=False,
            )
            progress.to_csv(output_path, index=False)
            pick_num += 1
            _sim_baseline = None

        elif pick_name == "random til me":
            # Inner loop: auto-pick for every team until "My Team" is on
            # the clock again (or the draft ends). Single rng so picks
            # within one burst feel coherent rather than independently
            # sampled. Outer loop will re-prompt as soon as we break.
            rng = np.random.default_rng()
            auto_count = 0
            while pick_num < tot_picks:
                next_slot = snake_pick_slot(pick_num, num_teams, args.reversal_round)
                next_team = league.teams[next_slot]["name"]
                if next_team == "My Team":
                    break
                auto_name = cockpit.random_pick(
                    board, team_name=next_team,
                    roster_spec=league.roster_spots,
                    exclude=exclude,
                    pool_size=args.random_pool_size,
                    pick_overall=pick_num + 1, num_teams=num_teams,
                    window_rounds=args.nearest_window,
                    rng=rng,
                )
                print(f"  Auto-drafting {auto_name} for {next_team}")
                _apply_pick(league, board, auto_name, next_team)
                progress = pd.concat(
                    [progress, league.players.loc[league.players.name == auto_name]],
                    ignore_index=True, sort=False,
                )
                progress.to_csv(output_path, index=False)
                pick_num += 1
                auto_count += 1
            if auto_count == 0:
                print("It's already your pick.")
            else:
                print(f"Auto-drafted {auto_count} picks. You're up.")
                _sim_baseline = None

        elif pick_name == "help":
            print(_HELP_TEXT)

        elif pick_name == "exit":
            print(f"Exiting draft. Progress saved to {output_path}.")
            return 0

    standings = league.bestball_sims(payouts=payouts) if args.bestball else league.season_sims(payouts=payouts)[1]
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
