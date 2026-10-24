"""Shared pytest fixtures for the fantasyfb test suite.

The provider fixtures fetch parquet data over the network on first use and
are session-scoped so the cost is paid once per test run rather than per
test function.
"""

from __future__ import annotations

import os
import sys
import warnings

import pandas as pd
import pytest

warnings.filterwarnings("ignore")

# Make the package importable when running `pytest` from the repo root
# without an editable install (src layout, so add `src/` to sys.path).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from fantasyfb.data.nflreadpy_provider import NflreadpyProvider  # noqa: E402


@pytest.fixture(scope="session")
def provider() -> NflreadpyProvider:
    return NflreadpyProvider()


@pytest.fixture(scope="session")
def stats(provider: NflreadpyProvider) -> pd.DataFrame:
    """2024 weeks 1-4 player stats. Small enough to be fast, large enough
    to cover every position and the year-range filter."""
    return provider.get_player_stats(202401, 202404)


@pytest.fixture(scope="session")
def schedule(provider: NflreadpyProvider) -> pd.DataFrame:
    return provider.get_schedule(2024, 2024)


@pytest.fixture(scope="session")
def rosters(provider: NflreadpyProvider) -> pd.DataFrame:
    return provider.get_rosters(2024, 2024)


@pytest.fixture(scope="session")
def depth_charts(provider: NflreadpyProvider) -> pd.DataFrame:
    return provider.get_depth_charts()


@pytest.fixture(scope="session")
def team_aliases(provider: NflreadpyProvider) -> pd.DataFrame:
    return provider.team_aliases()


@pytest.fixture(scope="module")
def replay_league(request):
    """A real ``League`` built offline from a recorded snapshot, with the
    clock frozen as it was at record time for as long as the module runs.

    Parametrize indirectly with a snapshot name prefix (``"generic"`` or
    ``"yahoo"``); defaults to the first snapshot.
    """
    import snapshot_io

    dirs = snapshot_io.snapshot_dirs()
    prefix = getattr(request, "param", "")
    matching = [d for d in dirs if d.name.startswith(prefix)]
    if not matching:
        pytest.skip("no recorded snapshots")
    snapshot_dir = matching[0]
    meta = snapshot_io.load_meta(snapshot_dir)
    store = snapshot_io.SnapshotStore.load(snapshot_dir)
    with snapshot_io.frozen_environment(snapshot_dir, meta["as_of"], offline=True):
        yield snapshot_io.build_league(
            meta,
            snapshot_io.ReplayProxy(store, "provider"),
            snapshot_io.ReplayProxy(store, "client"),
        )
