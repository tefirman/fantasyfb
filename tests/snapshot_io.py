"""Record/replay plumbing for the weekly-pipeline snapshot tests.

A snapshot is a frozen copy of everything the weekly ``fantasyfb`` run
reads from the outside world, captured at the two seams ``League``
already exposes:

- the NFL data provider (``NFLDataProvider``: stats, schedule, rosters,
  depth charts, team aliases), and
- the fantasy platform client (``FantasyPlatformClient``: league config,
  teams, rosters, fantasy schedule, current week),

plus the one remaining direct download (``injured_list.csv``) and the
wall-clock time the run happened at. Replaying a snapshot re-runs the
real pipeline end to end -- projections, lineups, live-week actuals,
season sims, move analysis, Excel export -- fully offline and
deterministically, so a regression in any of it shows up in CI instead
of on a Sunday.

Layout of a snapshot directory (``tests/snapshots/<name>/``)::

    meta.json          when/what was recorded, and how to rebuild the League
    calls.json         every provider/client call -> its (encoded) result
    injured_list.csv   the manual injury projections at record time
    blobs/*.parquet    DataFrame results, content-addressed (deduped)

Record new snapshots with ``scripts/record_snapshot.py``.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import pickle
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

SNAPSHOT_ROOT = Path(__file__).resolve().parent / "snapshots"

# Kept small so the replay test stays fast; the invariants checked don't
# depend on sim precision, only on the pipeline's internal consistency.
SNAPSHOT_NUM_SIMS = 200
SNAPSHOT_PAYOUTS = [800, 300, 100]


# --------------------------------------------------------------------------
# Encoding results to JSON + parquet blobs
# --------------------------------------------------------------------------

class _BlobStore:
    def __init__(self, blob_dir: Path):
        self.blob_dir = blob_dir

    def put(self, df: pd.DataFrame) -> str:
        buf = io.BytesIO()
        try:
            df.to_parquet(buf)
            ext = "parquet"
        except (pa.ArrowException, TypeError, ValueError):
            # Mixed-type object columns pyarrow can't express. Pickle is
            # less portable across pandas versions, so it's the fallback.
            buf = io.BytesIO()
            pickle.dump(df, buf, protocol=4)
            ext = "pkl"
        data = buf.getvalue()
        name = f"{hashlib.sha1(data).hexdigest()[:16]}.{ext}"
        path = self.blob_dir / name
        if not path.exists():
            self.blob_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return name

    def get(self, name: str) -> pd.DataFrame:
        path = self.blob_dir / name
        if name.endswith(".pkl"):
            with open(path, "rb") as f:
                return pickle.load(f)
        df = pd.read_parquet(path)
        # pyarrow hands list-valued cells (e.g. eligible_positions) back
        # as numpy arrays; restore the lists the live clients return.
        for col in df.columns:
            if df[col].dtype == object and df[col].map(lambda v: isinstance(v, np.ndarray)).any():
                df[col] = df[col].map(
                    lambda v: v.tolist() if isinstance(v, np.ndarray) else v
                )
        return df


def _encode(obj: Any, blobs: _BlobStore) -> Any:
    if isinstance(obj, pd.DataFrame):
        return {"__df__": blobs.put(obj)}
    if isinstance(obj, pd.Series):
        return {"__series__": blobs.put(obj.to_frame()), "name": obj.name}
    if isinstance(obj, dict):
        return {"__dict__": [[_encode(k, blobs), _encode(v, blobs)] for k, v in obj.items()]}
    if isinstance(obj, tuple):
        return {"__tuple__": [_encode(v, blobs) for v in obj]}
    if isinstance(obj, list):
        return [_encode(v, blobs) for v in obj]
    if isinstance(obj, (pd.Timestamp,)):
        return {"__ts__": obj.isoformat()}
    if isinstance(obj, np.generic):
        return obj.item()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    raise TypeError(f"Can't snapshot a {type(obj).__name__}: {obj!r}")


def _decode(obj: Any, blobs: _BlobStore) -> Any:
    if isinstance(obj, list):
        return [_decode(v, blobs) for v in obj]
    if isinstance(obj, dict):
        if "__df__" in obj:
            return blobs.get(obj["__df__"])
        if "__series__" in obj:
            frame = blobs.get(obj["__series__"])
            return frame.iloc[:, 0].rename(obj["name"])
        if "__dict__" in obj:
            return {_decode(k, blobs): _decode(v, blobs) for k, v in obj["__dict__"]}
        if "__tuple__" in obj:
            return tuple(_decode(v, blobs) for v in obj["__tuple__"])
        if "__ts__" in obj:
            return pd.Timestamp(obj["__ts__"])
    return obj


def _key_arg(obj: Any) -> Any:
    """JSON-able stand-in for a call argument, used only to key lookups."""
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        return f"<{type(obj).__name__}>"
    if isinstance(obj, dict):
        return {str(k): _key_arg(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_key_arg(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def call_key(method: str, args: tuple, kwargs: dict) -> str:
    return json.dumps(
        [method, _key_arg(list(args)), _key_arg(kwargs)],
        sort_keys=True, default=str,
    )


# --------------------------------------------------------------------------
# Recording and replaying proxies
# --------------------------------------------------------------------------

class SnapshotStore:
    """In-memory ``{seam: {call_key: [encoded result, ...]}}`` plus its blobs.

    Results are encoded the moment a call returns, before the pipeline
    gets a chance to mutate the returned DataFrame in place.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.blobs = _BlobStore(self.directory / "blobs")
        self.calls: dict[str, dict[str, list[Any]]] = {}

    def add(self, seam: str, key: str, result: Any) -> None:
        self.calls.setdefault(seam, {}).setdefault(key, []).append(
            _encode(result, self.blobs)
        )

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with open(self.directory / "calls.json", "w") as f:
            json.dump(self.calls, f, indent=1, sort_keys=True)

    @classmethod
    def load(cls, directory: Path) -> SnapshotStore:
        store = cls(directory)
        with open(store.directory / "calls.json") as f:
            store.calls = json.load(f)
        return store


class RecordingProxy:
    """Forwards every call to ``target`` and records the result."""

    def __init__(self, target: Any, seam: str, store: SnapshotStore):
        self._target = target
        self._seam = seam
        self._store = store

    def __getattr__(self, attr: str) -> Any:
        value = getattr(self._target, attr)
        if not callable(value):
            self._store.add(self._seam, call_key("attr:" + attr, (), {}), value)
            return value

        def recorded(*args, **kwargs):
            result = value(*args, **kwargs)
            self._store.add(self._seam, call_key(attr, args, kwargs), result)
            return result

        return recorded


class SnapshotMiss(LookupError):
    """The pipeline made a call the snapshot never saw."""


class ReplayProxy:
    """Answers calls from a recorded snapshot; never touches the network.

    Repeated calls with the same arguments get the recorded results in
    the order they were recorded, then keep repeating the last one. Each
    call gets a fresh copy, so in-place mutation downstream can't leak
    between calls.
    """

    def __init__(self, store: SnapshotStore, seam: str):
        self._store = store
        self._seam = seam
        self._calls = store.calls.get(seam, {})
        self._cursor: dict[str, int] = {}
        self._decoded: dict[tuple, Any] = {}

    def _lookup(self, key: str) -> Any:
        if key not in self._calls:
            raise SnapshotMiss(
                f"{self._seam} call not in snapshot {self._store.directory.name}: "
                f"{key}\nIf the pipeline legitimately changed which calls it "
                "makes, re-record with scripts/record_snapshot.py."
            )
        results = self._calls[key]
        idx = min(self._cursor.get(key, 0), len(results) - 1)
        self._cursor[key] = idx + 1
        cache_key = (key, idx)
        if cache_key not in self._decoded:
            self._decoded[cache_key] = _decode(results[idx], self._store.blobs)
        return copy.deepcopy(self._decoded[cache_key])

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        attr_key = call_key("attr:" + attr, (), {})
        if attr_key in self._calls:
            return self._lookup(attr_key)

        def replayed(*args, **kwargs):
            return self._lookup(call_key(attr, args, kwargs))

        return replayed


# --------------------------------------------------------------------------
# Environment patches shared by recording and replay
# --------------------------------------------------------------------------

@contextlib.contextmanager
def frozen_environment(snapshot_dir: Path, as_of: str, offline: bool) -> Iterator[None]:
    """Freeze the clock at ``as_of``, point the injury-list download at the
    snapshot's saved copy, and (for replay) refuse any network access."""
    from freezegun import freeze_time

    from fantasyfb.data import player_data_manager

    orig_url = player_data_manager.INJURED_LIST_URL
    orig_connect = socket.socket.connect
    player_data_manager.INJURED_LIST_URL = str(Path(snapshot_dir) / "injured_list.csv")
    if offline:
        def _no_network(self, address, *a, **k):
            raise OSError(f"snapshot replay attempted network access to {address!r}")
        socket.socket.connect = _no_network
    try:
        with freeze_time(as_of):
            yield
    finally:
        player_data_manager.INJURED_LIST_URL = orig_url
        socket.socket.connect = orig_connect


def load_meta(snapshot_dir: Path) -> dict[str, Any]:
    with open(Path(snapshot_dir) / "meta.json") as f:
        return json.load(f)


def snapshot_dirs() -> list[Path]:
    if not SNAPSHOT_ROOT.exists():
        return []
    return sorted(p for p in SNAPSHOT_ROOT.iterdir() if (p / "meta.json").exists())


# --------------------------------------------------------------------------
# The weekly run, shared by the recorder and the replay test
# --------------------------------------------------------------------------

def build_league(meta: dict[str, Any], provider: Any, client: Any):
    from fantasyfb import League

    np.random.seed(meta.get("seed", 0))
    return League(
        name=meta["team"],
        season=meta["season"],
        week=meta.get("week"),
        num_sims=SNAPSHOT_NUM_SIMS,
        nfl_provider=provider,
        client=client,
        fit_matchup=True,
    )


def run_weekly(league, output_dir: Path | None = None) -> dict[str, Any]:
    """Mirror of ``fantasyfb.league.main``'s default weekly run, plus adds
    and drops, returning every intermediate a test might want to check."""
    from fantasyfb.io.excel_exporter import FantasyExcelExporter

    out: dict[str, Any] = {}
    out["players"] = league.players.copy()
    # Captured here, while the clock is still frozen: both depend on
    # which games count as final "now".
    out["completed_teams"] = league._completed_nfl_teams(league.week)
    out["actuals"] = league._live_week_actuals(league.week)
    out["live_week_players"] = league._apply_live_week_actuals(league.players, league.week)

    np.random.seed(1)
    out["schedule_sim"], out["standings_sim"] = league.season_sims(
        True, payouts=list(SNAPSHOT_PAYOUTS)
    )
    # possible_adds/possible_drops each run a full season sim per
    # candidate; one candidate apiece (the best free agent, the least
    # valuable rostered player) exercises the paths at a fraction of the
    # cost. Sleeper/generic leagues report no roster percentages (all
    # 0.0), so the default 5% floor would filter out every free agent.
    has_rostership = (league.players.pct_rostered > 0).any()
    free_agents = league.players[
        league.players.fantasy_team.isnull()
        & ~league.players.name.str.contains("Average_")
        & (league.players.pct_rostered >= (0.05 if has_rostership else 0.0))
    ]
    np.random.seed(2)
    out["adds"] = league.possible_adds(
        focus_on=free_agents.nlargest(1, "WAR").name.tolist(),
        payouts=list(SNAPSHOT_PAYOUTS), verbose=False,
        min_rostership=0.05 if has_rostership else 0.0,
    )
    my_team = next(t["name"] for t in league.teams if t["team_key"] == league.my_team_key)
    mine = league.players[league.players.fantasy_team == my_team]
    np.random.seed(3)
    out["drops"] = league.possible_drops(
        focus_on=mine.nsmallest(1, "WAR").name.tolist(),
        payouts=list(SNAPSHOT_PAYOUTS), verbose=False,
    )
    out["players_after_moves"] = league.players.copy()

    if output_dir is not None:
        excel_file = str(Path(output_dir) / "FantasyFootballProjections_Snapshot.xlsx")
        exporter = FantasyExcelExporter(excel_file)
        rosters = (
            league.players.loc[~league.players.fantasy_team.isnull()]
            .sort_values(by=["fantasy_team", "WAR"], ascending=[True, False])
            .copy()
        )
        exporter.export_rosters(rosters)
        available = league.players.loc[
            league.players.fantasy_team.isnull()
            & (league.players.until.isnull() | (league.players.until < 17))
        ].sort_values(by="WAR", ascending=False)
        del available["fantasy_team"]
        exporter.export_available(available)
        exporter.export_schedule(out["schedule_sim"])
        exporter.export_standings(out["standings_sim"])
        exporter.export_analysis(out["adds"], "Adds")
        exporter.export_analysis(out["drops"], "Drops")
        exporter.close()
        out["excel_file"] = excel_file
    return out
