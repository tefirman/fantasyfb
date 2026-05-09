"""fantasyfb: fantasy football league simulation and optimization toolkit.

Public API
----------
The most commonly used entry points are re-exported here so that
``import fantasyfb as fb`` continues to work after the package
restructuring (League, FantasyScorer, projection / matchup models, etc.).
For lower-level helpers, import directly from the relevant submodule:

    from fantasyfb.drafts.tools import compute_vorp, assign_tiers
    from fantasyfb.sim.backtest import run_backtest
    from fantasyfb.io.excel_exporter import FantasyExcelExporter
"""

from .league import League
from .scoring.fantasy_scoring import FantasyScorer
from .scoring.matchup_model import MatchupModel
from .scoring.lineup_optimizer import LineupOptimizer
from .projections.engine_v2 import ProjectionEngineV2
from .sim.season_simulator import SeasonSimulator
from .sim.schedule_manager import ScheduleManager
from .data.nfl_provider import NFLDataProvider
from .data.nflreadpy_provider import NflreadpyProvider
from .configs import get_league_config, apply_default_scoring_categories

__version__ = "0.3.0"

__all__ = [
    "League",
    "FantasyScorer",
    "MatchupModel",
    "LineupOptimizer",
    "ProjectionEngineV2",
    "SeasonSimulator",
    "ScheduleManager",
    "NFLDataProvider",
    "NflreadpyProvider",
    "get_league_config",
    "apply_default_scoring_categories",
    "__version__",
]
