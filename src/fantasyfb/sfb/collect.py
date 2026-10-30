"""Collect the league data a field simulation needs from Sleeper.

Every league costs about 18 Sleeper requests, and Sleeper asks callers to stay
under 1,000 requests a minute or risk an IP block (docs.sleeper.com), so
requests go through a shared limiter that stops the whole run at the first
HTTP 429 rather than retrying through it.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

from ..data.sleeper_client import SleeperClient
from ..league import League
from ..sim.season_simulator import SeasonSimulator

TABLES = ("starters", "schedule", "settings", "teams")
DEFAULT_MAX_CALLS_PER_MINUTE = 500


class RequestLimiter:
    """Spaces requests evenly across threads and stops after a 429."""

    def __init__(self, max_per_minute: int):
        self.interval = 60.0 / max_per_minute
        self.calls = 0
        self.rate_limited = 0
        self._next = 0.0
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def get(self, send, url, *args, **kwargs):
        if self._stopped.is_set():
            raise RuntimeError("Stopped after Sleeper returned HTTP 429 (too many requests)")
        with self._lock:
            now = time.time()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
            self.calls += 1
        time.sleep(wait)
        response = send(url, *args, **kwargs)
        if response.status_code == 429:
            self.rate_limited += 1
            self._stopped.set()
        return response


@contextmanager
def throttled_requests(max_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE):
    """Routes every ``requests.get`` (which the Sleeper client uses) through one limiter."""
    limiter = RequestLimiter(max_per_minute)
    send = requests.get
    requests.get = lambda url, *args, **kwargs: limiter.get(send, url, *args, **kwargs)
    try:
        yield limiter
    finally:
        requests.get = send


def starters_by_week(league: League) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Each week's starters, and the team projections they add up to.

    Returns:
        ``(projections, starters)``: ``projections`` has ``fantasy_team``, ``week``,
        ``points_avg`` and ``points_stdev`` for all 17 weeks; ``starters`` has one
        row per started player for the weeks from the league's current week on
        (earlier weeks are locked to real scores and need no draws).
    """
    projections, starters = [], []
    for week in range(1, 18):
        league.starters(week)
        players = league._apply_live_week_actuals(league.players, week)
        players["points_var"] = players.points_stdev ** 2
        started = players.loc[players.starter, ["fantasy_team", "player_id", "points_avg", "points_stdev", "points_var"]]
        team = started.groupby("fantasy_team")[["points_avg", "points_var"]].sum().reset_index()
        projections.append(team.assign(week=week))
        if week >= league.week:
            starters.append(started.assign(week=week))
    projections = pd.concat(projections, ignore_index=True)
    projections["points_stdev"] = projections.points_var ** 0.5
    return projections, pd.concat(starters, ignore_index=True)


def collect_league(template: League, league_id: str) -> Dict[str, pd.DataFrame]:
    """Pulls one league and returns its rows for each table in ``TABLES``.

    Args:
        template: a League for any SFB league; its NFL data and projections are
            reused, which is only valid for leagues with the same scoring and
            roster spots (``League.for_league`` refuses others).
        league_id: Sleeper league ID.
    """
    league = template.for_league(SleeperClient(league_id))
    projections, starters = starters_by_week(league)
    simulator = SeasonSimulator({
        "playoff_start_week": league.settings["playoff_start_week"],
        "num_playoff_teams": league.settings["num_playoff_teams"],
        "num_teams": len(league.teams),
        "median_win": league.settings.get("median_win", False),
        "playoff_win_threshold": league.settings.get("playoff_win_threshold"),
    })
    schedule = simulator.schedule_with_projections(projections, league.schedule)
    schedule = schedule[["week", "team_1", "team_2", "points_avg_1", "points_stdev_1",
                         "points_avg_2", "points_stdev_2"]]
    roster_ids = {team["name"]: int(team["team_key"]) for team in league.teams}
    return dict(
        starters=starters.rename(columns={"fantasy_team": "team", "points_avg": "mu", "points_stdev": "sd"})
                         .drop(columns="points_var").assign(league_id=league_id),
        schedule=schedule.assign(league_id=league_id),
        settings=pd.DataFrame([dict(
            league_id=league_id,
            first_week=league.week,
            playoff_start_week=league.settings["playoff_start_week"],
            num_playoff_teams=league.settings["num_playoff_teams"],
            median_win=bool(league.settings.get("median_win", False)),
            playoff_win_threshold=league.settings.get("playoff_win_threshold") or 0,
            num_teams=len(league.teams),
        )]),
        teams=pd.DataFrame({"league_id": league_id, "team": list(roster_ids),
                            "roster_id": list(roster_ids.values())}),
    )


def collect_field(
    league_ids: Iterable[str],
    out_dir,
    template_id: Optional[str] = None,
    workers: int = 3,
    max_calls_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE,
    log=print,
) -> List[Tuple[str, str]]:
    """Collects many leagues and writes one parquet file per table to ``out_dir``.

    Files already in ``out_dir`` are kept except for the leagues collected now,
    so a failed league can be retried alone, or a few leagues refreshed.

    Args:
        league_ids: Sleeper league IDs to collect.
        out_dir: directory for the parquet files.
        template_id: league to build the shared projections from; defaults to the first of ``league_ids``.
        workers: threads pulling leagues at once. Projection work is CPU-bound,
            so more than a few threads won't speed it up.
        max_calls_per_minute: cap on Sleeper requests across all threads.
        log: called with a progress message per league.

    Returns:
        ``(league_id, error)`` for each league that failed; the rest are written.
    """
    league_ids = [str(league_id) for league_id in league_ids]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    errors, parts = [], {table: [] for table in TABLES}
    with throttled_requests(max_calls_per_minute) as limiter:
        template = League(platform="sleeper", sleeper_league_id=template_id or league_ids[0], num_sims=1000)
        started = time.time()

        def run(league_id):
            try:
                return league_id, collect_league(template, league_id)
            except Exception as e:  # one bad league shouldn't sink the run
                return league_id, f"{type(e).__name__}: {e}"

        with ThreadPoolExecutor(workers) as pool:
            for league_id, result in pool.map(run, league_ids):
                if isinstance(result, str):
                    errors.append((league_id, result))
                    log(f"{league_id} FAILED {result}")
                else:
                    for table in TABLES:
                        parts[table].append(result[table])
                    log(f"{league_id} ok ({len(parts['settings'])}/{len(league_ids)})")
        elapsed = time.time() - started
        log(f"{len(league_ids) - len(errors)} ok, {len(errors)} failed in {elapsed:.0f}s; "
            f"{limiter.calls} Sleeper calls ({limiter.calls / max(elapsed, 1) * 60:.0f}/min), "
            f"{limiter.rate_limited} rate-limited")

    done = [lid for lid in league_ids if lid not in {e[0] for e in errors}]
    for table in TABLES:
        new = pd.concat(parts[table], ignore_index=True) if parts[table] else None
        path = out_dir / f"{table}.parquet"
        if path.exists():
            old = pd.read_parquet(path)
            old = old[~old.league_id.isin(done)]
            new = old if new is None else pd.concat([old, new], ignore_index=True)
        if new is not None:
            new.to_parquet(path, index=False)
    return errors
