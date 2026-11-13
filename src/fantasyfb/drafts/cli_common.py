"""Pieces shared by the snake and salary cap draft CLIs.

Both cockpits run the same shape of session: build a League from the CLI
arguments, prompt on stdin with readline tab-completion, run season sims to
rank candidates, and print the final standings. The helpers here keep that
in one place so the two ``main()`` loops only hold what differs between a
snake draft and a salary cap draft.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

import pandas as pd

# readline gives input() history (up/down arrows, Ctrl-R) and tab-completion
# for free. Unix-only; on Windows the import fails and we just lose the
# polish without breaking the cockpit.
try:
    import readline
except ImportError:  # pragma: no cover -- Windows-only fallback
    readline = None


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


def _print_df(df: pd.DataFrame, header: str) -> None:
    print(f"\n{header}")
    if df.empty:
        print("(no players)")
    else:
        print(df.to_string(index=False))


_SIM_COLUMNS = ["team", "points_avg", "wins_avg", "playoffs", "winner", "earnings"]
_DELTA_COLUMNS = ["wins_avg", "points_avg", "playoffs", "winner", "runner_up", "earnings"]


def ask(prompt: str, check: Callable[[str], object]):
    """Prompt until ``check`` accepts the answer (returns something not None)."""
    value = check(input(prompt))
    while value is None:
        value = check(input(prompt))
    return value


def build_league(args, **league_kwargs):
    """Construct the League a draft CLI runs against, from its parsed arguments.

    Prompts for whatever a ``--platform generic`` mock draft needs and wasn't
    given on the command line. ``league_kwargs`` are passed through to League
    (the snake draft adds ``bestball``).

    Raises:
        ValueError: with the message to show the user, for bad arguments.
    """
    if args.platform == "sleeper" and not args.sleeper_league_id:
        raise ValueError("--sleeper-league-id is required with --platform sleeper")

    num_teams = args.num_teams
    mock_scoring = args.mock_scoring
    roster_spots = parse_roster_spots(args.roster_spots)
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

    return fb.League(
        name=args.team, num_sims=10000, season=args.season,
        platform=args.platform, sleeper_league_id=args.sleeper_league_id,
        num_teams=num_teams or 12, mock_scoring=mock_scoring or "ppr",
        roster_spots=roster_spots,
        nfl_provider=NflreadpyProvider(refresh=args.refresh_cache),
        **league_kwargs,
    )


def reset_rosters(league, fresh_draft: bool) -> None:
    """Keep each player's current team (keepers / restored picks from
    --inprogress), unless ``fresh_draft`` says to disregard whatever's
    currently rostered, e.g. mock-drafting against a Sleeper league that's
    already mid-season and has real, non-keeper rosters from its own draft."""
    if fresh_draft:
        league.players["fantasy_team"] = None
    else:
        league.players["fantasy_team"] = league.players.get("fantasy_team")


def run_season_sims(league, payouts, bestball: bool = False) -> pd.DataFrame:
    """Standings from a full simulation of the league's current rosters."""
    if bestball:
        return league.bestball_sims(payouts=payouts)
    return league.season_sims(payouts=payouts)[1]


def print_sim_standings(standings: pd.DataFrame) -> None:
    print(standings[_SIM_COLUMNS].to_string(index=False))


def simulate_additions(
    league,
    baseline: Optional[pd.DataFrame],
    candidates: list,
    run_sims: Callable[[], pd.DataFrame],
    apply: Callable[[dict], None],
    undo: Callable[[dict], None],
):
    """Sim the effect of adding each candidate to "My Team".

    Each candidate is a dict with ``name``, a ``label`` for the progress line
    and ``extras`` (columns to put in front of the deltas, e.g. an assumed
    bid). ``apply``/``undo`` put a candidate on and take it off the roster.
    Runs at 1000 sims, and reuses ``baseline`` when one is already cached.

    Returns:
        ``(baseline, result)``: the baseline standings, and the per-candidate
        deltas from it sorted best first (None when there were no candidates).
    """
    original_num_sims = league.num_sims
    league.num_sims = 1000
    try:
        print("Running baseline sim...")
        if baseline is None:
            baseline = run_sims()
        baseline_row = baseline.loc[baseline.team == "My Team"]
        delta_cols = [c for c in _DELTA_COLUMNS if c in baseline.columns]
        rows = []
        for candidate in candidates:
            print(f"  Simulating {candidate['label']}...")
            apply(candidate)
            standings = run_sims()
            undo(candidate)
            row = {"name": candidate["name"], **candidate.get("extras", {})}
            for col in delta_cols:
                row[col] = round(
                    standings.loc[standings.team == "My Team", col].values[0]
                    - baseline_row[col].values[0], 3
                )
            rows.append(row)
    finally:
        league.num_sims = original_num_sims
    if not rows:
        return baseline, None
    sort_col = "winner" if "winner" in delta_cols else delta_cols[-1]
    return baseline, pd.DataFrame(rows).sort_values(sort_col, ascending=False)


def finish_draft(league, payouts, bestball: bool = False) -> None:
    """Final sims of the finished draft: print and save the standings, then
    say how it went for "My Team"."""
    standings = run_season_sims(league, payouts, bestball)
    print_sim_standings(standings)
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
