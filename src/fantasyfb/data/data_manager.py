# fantasyfb/data/data_manager.py
"""
Data Manager - handles all data loading, caching, and API interactions.
"""

import pandas as pd
import os
import time
import datetime
from typing import Dict, List, Tuple, Optional
import logging
from pathlib import Path

from .yahoo_client import YahooClient
from ..utils.cache import DataCache
from ..utils import sportsref_nfl as sr

logger = logging.getLogger(__name__)


class DataManager:
    """
    Manages all data loading and caching for the fantasy league.
    
    Responsibilities:
    - Yahoo API data retrieval
    - Pro Football Reference data
    - Data caching and validation
    - Name corrections and data mapping
    """
    
    def __init__(self, yahoo_client: YahooClient):
        self.yahoo_client = yahoo_client
        self.cache = DataCache()
        
    def load_league_id(self, season: int, team_name: str = None) -> Tuple[str, List[Dict]]:
        """
        Load basic league information from Yahoo API.
        
        Args:
            team_name: Specific team name if user has multiple leagues
            
        Returns:
            Tuple of (league_id, teams_list)
        """
        cache_key = f"league_info_{team_name or 'default'}"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=24)
        
        if cached:
            return cached
        
        logger.info("Loading league information from Yahoo API...")
        
        # Get user's leagues
        leagues_data = self.yahoo_client.get_user_leagues()
        
        # Find the right league
        lg_id, team = self._select_league(leagues_data, season, team_name)
        
        # Cache the result
        result = (lg_id, team)
        self.cache.save_data(cache_key, result)
        
        return result
    
    def load_league_settings(self, lg_id: str) -> Tuple[Dict, Dict, pd.DataFrame]:
        """
        Load league settings including scoring and roster configuration.
        
        Args:
            lg_id: Yahoo league ID
            
        Returns:
            Tuple of (settings_dict, scoring_dict, roster_spots_df)
        """
        cache_key = f"league_settings_{lg_id}"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=168)  # Week-long cache
        
        if cached:
            return cached
        
        logger.info("Loading league settings...")
        
        settings_raw = self.yahoo_client.get_league_settings(lg_id)
        
        # Process settings
        settings = self._process_settings(settings_raw)
        scoring = self._process_scoring(settings_raw)
        roster_spots = self._process_roster_spots(settings_raw)
        
        result = (settings, scoring, roster_spots)
        self.cache.save_data(cache_key, result)
        
        return result
    
    def load_players(self, lg_id: str, season: int, week: int, force_refresh: bool = False) -> pd.DataFrame:
        """
        Load all NFL players eligible for the league.
        
        Args:
            lg_id: Yahoo league ID
            season: NFL season
            week: Current week
            force_refresh: Force refresh of player data
            
        Returns:
            DataFrame with player information
        """
        cache_key = f"players_{lg_id}_{season}_{week}"
        
        if not force_refresh:
            cached = self.cache.get_cached_data(cache_key, max_age_hours=6)
            if cached is not None:
                return cached
        
        logger.info("Loading player data from Yahoo API...")
        
        # Get raw player data from Yahoo
        players_raw = self.yahoo_client.get_all_players(lg_id)
        
        # Get current rosters
        rosters = self.yahoo_client.get_all_rosters(lg_id, week)
        
        # Process and merge data
        players = self._process_players(players_raw, rosters)
        
        # Add external data
        players = self._add_external_player_data(players, season)
        
        # Cache the result
        self.cache.save_data(cache_key, players)
        
        return players
    
    def load_nfl_teams(self) -> pd.DataFrame:
        """Load NFL team abbreviation mappings."""
        cache_key = "nfl_teams"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=168)
        
        if cached is not None:
            return cached
        
        # Load from GitHub (your existing source)
        nfl_teams = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/team_abbrevs.csv"
        )
        
        self.cache.save_data(cache_key, nfl_teams)
        return nfl_teams
    
    def load_nfl_schedule(self, season: int) -> pd.DataFrame:
        """Load NFL schedule with elo ratings."""
        cache_key = f"nfl_schedule_{season}"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=24)
        
        if cached is not None:
            return cached
        
        logger.info(f"Loading NFL schedule for {season}...")
        
        # Use your existing sportsref functionality
        schedule_path = "NFLSchedule.csv"
        
        if os.path.exists(schedule_path):
            nfl_schedule = pd.read_csv(schedule_path)
        else:
            nfl_schedule = pd.DataFrame(columns=['season','week','score1','score2'])
        
        # Check if we need to update
        before = nfl_schedule.season*100 + nfl_schedule.week < season*100 + 1
        missing = before & nfl_schedule.score1.isnull() & nfl_schedule.score2.isnull()
        
        if missing.any() or season not in nfl_schedule.season.unique():
            logger.info("Updating NFL schedule from Pro Football Reference...")
            s = sr.Schedule(season - 8, season, False, True, False)
            s.schedule.to_csv(schedule_path, index=False)
            nfl_schedule = s.schedule.copy()
        
        # Process schedule data (your existing logic)
        processed_schedule = self._process_nfl_schedule(nfl_schedule)
        
        self.cache.save_data(cache_key, processed_schedule)
        return processed_schedule
    
    def load_fantasy_schedule(self, lg_id: str, teams: List[Dict], season: int, week: int) -> pd.DataFrame:
        """Load fantasy league schedule."""
        cache_key = f"fantasy_schedule_{lg_id}_{season}_{week}"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=6)
        
        if cached is not None:
            return cached
        
        logger.info("Loading fantasy schedule...")
        
        schedule = self.yahoo_client.get_league_schedule(lg_id, teams, season, week)
        
        self.cache.save_data(cache_key, schedule)
        return schedule
    
    def get_current_week(self, lg_id: str) -> int:
        """Get current NFL week from Yahoo API."""
        return self.yahoo_client.get_current_week(lg_id)
    
    def _select_league(self, leagues_data: Dict, season: int, team_name: str) -> Tuple[str, List[Dict]]:
        """Select the appropriate league from user's leagues."""
        # Implementation of your existing league selection logic
        # This would extract the right league based on team_name
        for ind in range(leagues_data["count"]):
            game = leagues_data[str(ind)]["game"]
            if type(game) == dict:
                continue
            if game[0]["code"] == "nfl" \
            and game[0]["season"] == str(season):
                teams = game[1]["teams"]
                details = [teams[str(ind)]["team"][0] for ind in range(teams["count"])]
                names = [
                    [val["name"] for val in team if "name" in val][0]
                    for team in details
                ]
                if teams["count"] > 1:
                    # If user has more than one team, use the team_name input or prompt them to pick one
                    while team_name not in names:
                        print("Found multiple fantasy teams: " + ", ".join(names))
                        team_name = input("Which team would you like to analyze? ")
                    team = teams[str(names.index(team_name))]["team"][0]
                else:
                    # If user has only one team, use that one and override whatever name was given
                    team = teams["0"]["team"][0]
                    team_name = names[0]
                team_key = [val["team_key"] for val in team if "team_key" in val][0]
                lg_id = ".".join(team_key.split(".")[:3])
                return lg_id, team
        raise ValueError(
            f"Can't find a team by the name of {team_name} for the {season} season"
        )
    
    def _process_settings(self, settings_raw: Dict) -> Dict:
        """Process raw Yahoo settings into clean format."""
        # Extract playoff settings, etc.
        pass
    
    def _process_scoring(self, settings_raw: Dict) -> Dict:
        """Process scoring settings."""
        # Extract and clean scoring rules
        pass
    
    def _process_roster_spots(self, settings_raw: Dict) -> pd.DataFrame:
        """Process roster spot configuration."""
        # Convert to clean DataFrame format
        pass
    
    def _process_players(self, players_raw: List[Dict], rosters: Dict) -> pd.DataFrame:
        """Process raw player data from Yahoo."""
        # Convert to DataFrame and clean up
        pass
    
    def _add_external_player_data(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add injury status, depth charts, roster percentages, etc."""
        # Add all the external data your current system pulls
        pass
    
    def _process_nfl_schedule(self, schedule: pd.DataFrame) -> pd.DataFrame:
        """Process NFL schedule data."""
        # Your existing NFL schedule processing logic
        pass
