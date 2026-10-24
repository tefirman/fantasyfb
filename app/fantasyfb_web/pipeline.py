"""
One simulation run for a Sleeper or Yahoo league: build a ``League``, run the season
sims (plus any optional move analyses), and render the same interactive
report the ``fantasyfb --format html`` CLI writes.

This mirrors the report-building half of ``fantasyfb.league.main``. Keep the
two in step until that logic moves into the package as a reusable function.
"""

from __future__ import annotations

import datetime
import warnings
from dataclasses import dataclass
from typing import Callable, Tuple

from fantasyfb.data.sleeper_client import FREE_AGENT_RANK_CUTOFF, UnsupportedScoringWarning
from fantasyfb.io.html_exporter import FantasyHtmlExporter

# How many free agents per position the "adds" analysis re-simulates. Each one
# is a full season sim, so this is the main knob on how long a run takes.
ADDS_PER_POSITION = 5


@dataclass(frozen=True)
class RunOptions:
    """Everything a run needs. Frozen so identical requests can be de-duplicated."""

    league_id: str  # Sleeper league ID; empty for Yahoo, where the team name picks the league
    team: str
    season: int
    sims: int = 1000
    payouts: Tuple[float, float, float] = (60.0, 30.0, 10.0)
    adds: bool = False
    drops: bool = False
    deltas: bool = False
    platform: str = "sleeper"  # "sleeper" or "yahoo"


def _default_league_factory(opts: RunOptions, auth=None):
    # Imported lazily so the web app starts (and its tests run) without
    # paying for the full package import up front.
    from fantasyfb.league import League

    if opts.platform == "yahoo":
        from fantasyfb.data.yahoo_client import YahooFantasyClient

        # Bounded retries and no stdin: a revoked token must fail the run,
        # not hang the only worker.
        client = YahooFantasyClient(oauth=auth, max_query_tries=3, retry_wait=5)
        client.connect_to_league(opts.season, opts.team)
        return League(
            name=opts.team, season=opts.season, num_sims=opts.sims, client=client
        )

    return League(
        name=opts.team,
        season=opts.season,
        num_sims=opts.sims,
        platform="sleeper",
        sleeper_league_id=opts.league_id,
    )


def free_agent_pool(players):
    """
    Unrostered players who could be added, with injured-for-the-season players left out.

    Sleeper's player map also lists retired players (Brady, Brees, Gronkowski) who
    still have search volume. They have no NFL team, so they can't score, but they
    get a position-average projection and would crowd the list, so a Sleeper pool
    (recognised by its ``sleeper_rank`` column) keeps only players on an NFL team.
    """
    pool = players.loc[
        players.fantasy_team.isnull() & (players.until.isnull() | (players.until < 17))
    ]
    if "sleeper_rank" in pool.columns:
        pool = pool.loc[pool.current_team.notnull()]
    return pool


def top_free_agents(
    players, per_position: int = ADDS_PER_POSITION, max_rank: int = FREE_AGENT_RANK_CUTOFF,
) -> list:
    """
    Names of the best available free agents by WAR, ``per_position`` per position.

    Sleeper exposes no roster percentages, so ``possible_adds``'s usual
    ``min_rostership`` filter can't narrow the pool. Without this its
    per-position ``head()`` takes whichever free agents happen to come first
    in ``players``, not the best ones. When the players carry Sleeper's
    popularity rank (``sleeper_rank``), only players ranked ``max_rank`` or
    better are considered: the rest include retired players who get the
    position-average projection and would otherwise top the WAR ranking.
    """
    available = free_agent_pool(players).loc[
        lambda df: ~df.name.str.contains("Average_", na=False)
    ]
    if "sleeper_rank" in available.columns:
        available = available.loc[available.sleeper_rank <= max_rank]
    return (
        available.sort_values("WAR", ascending=False)
        .groupby("position")
        .head(per_position)
        .name.tolist()
    )


def build_report(
    opts: RunOptions,
    progress: Callable[[str], None] = lambda stage: None,
    league_factory: Callable[..., object] = _default_league_factory,
    auth=None,
) -> str:
    """
    Run the pipeline for ``opts`` and return the report as an HTML string.

    Args:
        opts: what to run
        progress: called with a short label as each stage starts
        league_factory: builds the ``League``; injectable for tests
        auth: the signed-in user's Yahoo tokens (Yahoo runs only)
    """
    payouts = list(opts.payouts)

    progress("Loading league, player pool, and projections")
    # Categories the projections can't cover surface in the report, where the
    # person who ran it will see them; a warning alone would only reach the
    # server log.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UnsupportedScoringWarning)
        league = league_factory(opts, auth) if auth is not None else league_factory(opts)
    notices = [
        str(w.message) for w in caught if issubclass(w.category, UnsupportedScoringWarning)
    ]

    exporter = FantasyHtmlExporter(
        output_path="",
        week=league.week,
        me=opts.team,
        sims=league.num_sims,
        day=datetime.datetime.now().strftime("%A"),
        platform=opts.platform.capitalize(),
        notices=notices,
        median_win=bool(league.settings.get("median_win")),
        sfb=bool(league.settings.get("sfb")),
    )

    players = league.players
    rosters = (
        players.loc[~players.fantasy_team.isnull()]
        .sort_values(by=["fantasy_team", "WAR"], ascending=[True, False])
    )
    exporter.export_rosters(rosters)
    available = free_agent_pool(players).sort_values(by="WAR", ascending=False)
    exporter.export_available(available.drop(columns=["fantasy_team"]))

    progress("Simulating the season")
    schedule, standings = league.season_sims(True, payouts=payouts)
    exporter.export_schedule(schedule)
    exporter.export_standings(standings)

    if opts.adds:
        progress("Evaluating free agent adds")
        if opts.platform == "yahoo":
            # Yahoo reports roster percentages, so the default rostership
            # filter already narrows the pool to players worth testing.
            adds = league.possible_adds(
                exclude=["Tom Brady"],
                limit_per=ADDS_PER_POSITION,
                payouts=payouts,
                verbose=False,
            )
        else:
            adds = league.possible_adds(
                focus_on=top_free_agents(league.players),
                limit_per=ADDS_PER_POSITION,
                payouts=payouts,
                min_rostership=0.0,
                verbose=False,
            )
        exporter.export_analysis(adds, "Adds")

    if opts.drops:
        progress("Evaluating drops")
        drops = league.possible_drops(payouts=payouts, verbose=False)
        exporter.export_analysis(drops, "Drops")

    if opts.deltas:
        progress("Building the rooting guide")
        exporter.export_deltas(league.perGameDelta(payouts=payouts))

    progress("Rendering report")
    return exporter.render()
