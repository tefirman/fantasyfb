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
