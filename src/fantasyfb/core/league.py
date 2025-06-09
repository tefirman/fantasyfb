# fantasyfb/core/league.py
"""
Core League class - handles league settings, teams, and basic data loading.
"""

import pandas as pd
import datetime
from typing import Dict, List, Optional
import logging

from ..data.yahoo_client import YahooClient
from ..data.data_manager import DataManager
from ..analysis.player_analyzer import PlayerAnalyzer
from ..analysis.simulator import SeasonSimulator
from ..analysis.trades import TradeAnalyzer
from ..utils.config import LeagueConfig

logger = logging.getLogger(__name__)


class League:
    """
    Main League class that coordinates fantasy league analysis.
    
    This class now focuses on:
    - League settings and configuration
    - Team management
    - Coordinating between different analysis components
    """
    
    def __init__(
        self,
        team_name: str = None,
        season: int = None,
        week: int = None,
        config: LeagueConfig = None,
        **kwargs
    ):
        """
        Initialize a League object.
        
        Args:
            name: Fantasy team name
            season: NFL season year
            week: Current week
            config: League configuration object
            **kwargs: Additional configuration options
        """
        self.config = config or LeagueConfig(**kwargs)
        
        # Basic league info
        self.latest_season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        self.season = season if season else self.latest_season
        self.team_name = team_name
        self.week = week
        
        # Initialize components
        self.yahoo_client = YahooClient()
        self.data_manager = DataManager(self.yahoo_client)
        
        # Load core league data
        self._load_league_data()
        
        # Initialize analysis components (lazy loading)
        self._player_analyzer = None
        self._simulator = None
        self._trade_analyzer = None
        
        logger.info(f"Initialized league: {self.name} for season {self.season}")
    
    def _load_league_data(self):
        """Load essential league data from Yahoo API."""
        try:
            # Load league settings and teams
            self.lg_id = self.data_manager.load_league_id(self.season, self.team_name)[0]
            self.settings, self.scoring, self.roster_spots = self.data_manager.load_league_settings(self.lg_id)
            
            # Load current week
            self.current_week = self.data_manager.get_current_week(self.lg_id)
            self.week = self.week if self.week else self.current_week
            
            # Load NFL data
            self.nfl_teams = self.data_manager.load_nfl_teams()
            self.nfl_schedule = self.data_manager.load_nfl_schedule(self.season)
            
            logger.info(f"Loaded league data for {self.lg_id}")
            
        except Exception as e:
            logger.error(f"Failed to load league data: {e}")
            raise
    
    @property
    def player_analyzer(self) -> PlayerAnalyzer:
        """Lazy load player analyzer."""
        if self._player_analyzer is None:
            self._player_analyzer = PlayerAnalyzer(
                league=self,
                config=self.config.player_config
            )
        return self._player_analyzer
    
    @property
    def simulator(self) -> SeasonSimulator:
        """Lazy load season simulator."""
        if self._simulator is None:
            self._simulator = SeasonSimulator(
                league=self,
                config=self.config.simulation_config
            )
        return self._simulator
    
    @property
    def trade_analyzer(self) -> TradeAnalyzer:
        """Lazy load trade analyzer."""
        if self._trade_analyzer is None:
            self._trade_analyzer = TradeAnalyzer(
                league=self,
                simulator=self.simulator
            )
        return self._trade_analyzer
    
    def load_players(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Load and process player data.
        
        Args:
            force_refresh: Force refresh of cached data
            
        Returns:
            DataFrame with processed player data
        """
        if not hasattr(self, 'players') or force_refresh:
            logger.info("Loading player data...")
            
            # Get raw player data
            self.players = self.data_manager.load_players(
                self.lg_id, 
                self.season, 
                self.week
            )
            
            # Process with player analyzer
            self.players = self.player_analyzer.process_players(self.players)
            
            logger.info(f"Loaded {len(self.players)} players")
        
        return self.players
    
    def get_schedule(self) -> pd.DataFrame:
        """Get processed fantasy schedule."""
        if not hasattr(self, 'schedule'):
            self.schedule = self.data_manager.load_fantasy_schedule(
                self.lg_id, 
                self.teams, 
                self.season, 
                self.week
            )
        return self.schedule
    
    def season_sims(
        self, 
        postseason: bool = True, 
        payouts: List[float] = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Run season simulations.
        
        Args:
            postseason: Include playoff simulations
            payouts: Prize structure
            
        Returns:
            Tuple of (schedule_results, standings_results)
        """
        return self.simulator.season_sims(
            postseason=postseason,
            payouts=payouts or self.config.default_payouts
        )
    
    def bestball_sims(self, payouts: List[float] = None) -> pd.DataFrame:
        """Run best ball simulations."""
        return self.simulator.bestball_sims(
            payouts=payouts or self.config.default_payouts
        )
    
    def possible_adds(self, **kwargs) -> pd.DataFrame:
        """Analyze possible free agent additions."""
        return self.trade_analyzer.possible_adds(**kwargs)
    
    def possible_drops(self, **kwargs) -> pd.DataFrame:
        """Analyze possible player drops."""
        return self.trade_analyzer.possible_drops(**kwargs)
    
    def possible_trades(self, **kwargs) -> pd.DataFrame:
        """Analyze possible trades."""
        return self.trade_analyzer.possible_trades(**kwargs)
    
    def possible_pickups(self, **kwargs) -> pd.DataFrame:
        """Analyze add/drop combinations."""
        return self.trade_analyzer.possible_pickups(**kwargs)
    
    def refresh_data(self):
        """Refresh all league data."""
        logger.info("Refreshing league data...")
        
        # Clear cached data
        if hasattr(self, 'players'):
            delattr(self, 'players')
        if hasattr(self, 'schedule'):
            delattr(self, 'schedule')
        
        # Reset analysis components
        self._player_analyzer = None
        self._simulator = None
        self._trade_analyzer = None
        
        # Reload
        self._load_league_data()
        logger.info("League data refreshed")
    
    def get_team_name(self) -> str:
        """Get the user's team name."""
        return self.name
    
    def get_other_teams(self) -> List[Dict]:
        """Get all other teams in the league."""
        return [team for team in self.teams if team['name'] != self.name]
