"""Record a weekly-pipeline snapshot for tests/test_weekly_snapshot.py.

Runs the real weekly pipeline (League construction, season sims, adds,
drops, Excel export) against live data with the clock frozen at
``--as-of``, recording every NFL-provider and platform-client call so
the test can replay it offline. See tests/snapshot_io.py for the format.

Best recorded mid-slate (e.g. Sunday night, before Monday Night Football)
so the snapshot exercises the live-week code paths: some games final,
some not.

Examples:

    # Your real Yahoo league, right now (needs oauth2.json + .env)
    python scripts/record_snapshot.py --platform yahoo --team "My Team" \\
        --name yahoo_2026_w05

    # Public Sleeper league
    python scripts/record_snapshot.py --platform sleeper \\
        --sleeper-league-id 1367870433398915072 --team "<team or manager>" \\
        --name sleeper_2026_w05

    # Synthetic league (no credentials): 12 PPR teams whose rosters come
    # from a deterministic snake draft on prior-season fantasy points
    python scripts/record_snapshot.py --platform generic \\
        --as-of 2026-09-20T23:30 --week 2 --name generic_2026_w02_sunday_night

Any snapshot directory under tests/snapshots/ is picked up by the test
automatically.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tests"))

import snapshot_io

from fantasyfb.configs import get_league_config
from fantasyfb.data.generic_client import GenericClient
from fantasyfb.data.nflreadpy_provider import NflreadpyProvider
from fantasyfb.data.player_data_manager import INJURED_LIST_URL
from fantasyfb.scoring.fantasy_scoring import FantasyScorer

_FLEX = {"W/T": ["WR", "TE"], "W/R/T": ["WR", "RB", "TE"], "Q/W/R/T": ["QB", "WR", "RB", "TE"]}
_BENCH_POSITIONS = ["QB", "RB", "WR", "TE"]


class DraftedGenericClient(GenericClient):
    """GenericClient with populated rosters and a fixed current week.

    Rosters come from a deterministic snake draft: each team takes the
    highest prior-season fantasy scorer that fills an open starting slot,
    then best available QB/RB/WR/TE for the bench. Weeks already played
    get fixed pseudo-random final scores, since a synthetic league has no
    real results to report.
    """

    def __init__(self, current_week: int, **kwargs):
        super().__init__(**kwargs)
        self._current_week = current_week
        self._rosters = None

    def get_current_week(self) -> int:
        return self._current_week

    def _prior_season_points(self) -> pd.Series:
        stats = self.nfl_provider.get_player_stats(
            (self.season - 1) * 100 + 1, (self.season - 1) * 100 + 18
        )
        scoring = get_league_config(self.scoring_preset)["scoring"]
        scored = FantasyScorer(scoring).calculate_points(stats)
        return scored.groupby("player_id_sr")["points"].sum()

    def _draft(self, teams: list[dict]) -> pd.DataFrame:
        pool = self.get_all_players()
        pool["rank_points"] = pool["player_id_sr"].map(self._prior_season_points()).fillna(0.0)
        pool = pool.sort_values(["rank_points", "name"], ascending=[False, True])
        spots = self.get_league_config()["roster_spots"]
        starting = [
            pos for pos, count in zip(spots.position, spots["count"])
            if pos not in ("BN", "IR") for _ in range(int(count))
        ]
        num_bench = int(spots.loc[spots.position == "BN", "count"].sum())
        open_slots = {t["name"]: list(starting) for t in teams}
        bench_left = {t["name"]: num_bench for t in teams}
        taken = set()
        rows = []
        order = [t["name"] for t in teams]
        rounds = len(starting) + num_bench
        for rnd in range(rounds):
            for team in (order if rnd % 2 == 0 else order[::-1]):
                for _, player in pool.iterrows():
                    if player.player_id in taken:
                        continue
                    slot = next(
                        (s for s in open_slots[team]
                         if s == player.position or player.position in _FLEX.get(s, [])),
                        None,
                    )
                    if slot is None and not (
                        bench_left[team] > 0 and player.position in _BENCH_POSITIONS
                    ):
                        continue
                    if slot is not None:
                        open_slots[team].remove(slot)
                    else:
                        bench_left[team] -= 1
                        slot = "BN"
                    taken.add(player.player_id)
                    rows.append({
                        "player_id": player.player_id,
                        "selected_position": slot,
                        "fantasy_team": team,
                    })
                    break
        return pd.DataFrame(rows, columns=["player_id", "selected_position", "fantasy_team"])

    def get_team_rosters(self, teams: list[dict], week: int) -> pd.DataFrame:
        if self._rosters is None:
            self._rosters = self._draft(teams)
        return self._rosters.copy()

    def get_schedule(self, teams, current_week, playoff_start_week, end_week=None):
        schedule = super().get_schedule(teams, current_week, playoff_start_week, end_week)
        rng = np.random.default_rng(self.season * 100 + self._current_week)
        played = schedule.week < self._current_week
        schedule.loc[played, ["score_1", "score_2"]] = rng.normal(
            115, 22, size=(int(played.sum()), 2)
        ).round(2)
        return schedule


def _build_client(args, provider):
    if args.platform == "yahoo":
        from fantasyfb.data.yahoo_client import YahooFantasyClient

        client = YahooFantasyClient()
        team, _ = client.connect_to_league(args.season, args.team)
        return client, team
    if args.platform == "sleeper":
        from fantasyfb.data.sleeper_client import SleeperClient

        if not args.sleeper_league_id:
            sys.exit("--sleeper-league-id is required for --platform sleeper")
        return SleeperClient(args.sleeper_league_id, my_team_name=args.team), args.team
    if args.week is None:
        sys.exit("--week is required for --platform generic (it has no real current week)")
    team = args.team or "Snapshot Team"
    client = DraftedGenericClient(
        current_week=args.week, num_teams=args.num_teams, scoring=args.mock_scoring,
        my_team_name=team, season=args.season, nfl_provider=provider,
    )
    client.scoring_preset = args.mock_scoring
    return client, team


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--platform", choices=["yahoo", "sleeper", "generic"], required=True)
    parser.add_argument("--name", required=True, help="snapshot directory name under tests/snapshots/")
    parser.add_argument("--team", help="your team name (yahoo/sleeper) or display name (generic)")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None,
                        help="week to analyze; required for generic, defaults to the current week otherwise")
    parser.add_argument("--as-of", default=None,
                        help="wall-clock time to freeze the run at, e.g. 2026-09-20T23:30 (default: now)")
    parser.add_argument("--sleeper-league-id")
    parser.add_argument("--num-teams", type=int, default=12)
    parser.add_argument("--mock-scoring", default="ppr", choices=["standard", "half_ppr", "ppr"])
    parser.add_argument("--description", default="")
    parser.add_argument("--force", action="store_true", help="overwrite an existing snapshot")
    args = parser.parse_args()

    # Naive local time on purpose: League compares against naive now().
    as_of = args.as_of or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")  # noqa: DTZ005
    as_of_dt = datetime.datetime.fromisoformat(as_of)
    if args.season is None:
        args.season = as_of_dt.year - int(as_of_dt.month < 6)

    out_dir = snapshot_io.SNAPSHOT_ROOT / args.name
    if out_dir.exists():
        if not args.force:
            sys.exit(f"{out_dir} already exists (pass --force to overwrite)")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    try:
        urllib.request.urlretrieve(INJURED_LIST_URL, out_dir / "injured_list.csv")

        meta = {
            "platform": args.platform,
            "team": None,
            "season": args.season,
            "week": args.week,
            "as_of": as_of,
            "seed": 0,
            "description": args.description,
            "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005
            "versions": {"pandas": pd.__version__, "numpy": np.__version__},
        }

        provider = NflreadpyProvider()
        store = snapshot_io.SnapshotStore(out_dir)
        with snapshot_io.frozen_environment(out_dir, as_of, offline=False):
            client, meta["team"] = _build_client(args, provider)
            league = snapshot_io.build_league(
                meta,
                snapshot_io.RecordingProxy(provider, "provider", store),
                snapshot_io.RecordingProxy(client, "client", store),
            )
            meta["week"] = league.week
            meta["current_week"] = league.current_week
            with tempfile.TemporaryDirectory() as tmp:
                snapshot_io.run_weekly(league, Path(tmp))
        store.save()
        with open(out_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)
    except BaseException:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    size = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"Recorded {out_dir} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
