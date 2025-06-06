# fantasyfb/data/yahoo_client.py
"""
Yahoo API Client - handles all Yahoo Fantasy API interactions.
"""

import os
import time
import json
import datetime
from typing import Dict, List
import logging
from pathlib import Path

import pandas as pd
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class YahooClient:
    """
    Handles Yahoo Fantasy Sports API interactions.
    
    Responsibilities:
    - OAuth authentication and token management
    - API rate limiting and retry logic
    - Raw data retrieval from Yahoo
    """
    
    def __init__(self, credentials_file: str = ".env"):
        """
        Initialize Yahoo API client.
        
        Args:
            credentials_file: Path to credentials file
        """
        self.credentials_file = credentials_file
        self._oauth = None
        self._gm = None
        self._last_request_time = 0
        self._min_request_interval = 3  # seconds between requests
        
        self._load_credentials()
        self._initialize_oauth()
    
    def _load_credentials(self):
        """Load Yahoo OAuth credentials."""
        load_dotenv(self.credentials_file)
        
        if "CONSUMER_KEY" not in os.environ or "CONSUMER_SECRET" not in os.environ:
            logger.warning("No valid credentials found, using example file")
            # Copy from example if needed
            if Path(".env.example").exists():
                import shutil
                shutil.copyfile(".env.example", ".env")
                load_dotenv()
        
        # Check if credentials need updating
        if (os.environ.get("CONSUMER_KEY") == "updatekey" and 
            os.environ.get("CONSUMER_SECRET") == "updatesecret"):
            raise ValueError(
                "Please update your Yahoo OAuth credentials in .env file. "
                "Get them from: https://developer.yahoo.com/apps/create/"
            )
    
    def _initialize_oauth(self):
        """Initialize OAuth2 authentication."""
        try:
            # Create oauth file if it doesn't exist
            if not os.path.exists("oauth2.json"):
                creds = {
                    "consumer_key": os.environ["CONSUMER_KEY"],
                    "consumer_secret": os.environ["CONSUMER_SECRET"],
                }
                with open("oauth2.json", "w") as f:
                    json.dump(creds, f)
            
            self._oauth = OAuth2(None, None, from_file="oauth2.json")
            self._gm = yfa.Game(self._oauth, "nfl")
            
            logger.info("Yahoo OAuth initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Yahoo OAuth: {e}")
            raise
    
    def _rate_limit(self):
        """Enforce rate limiting between API requests."""
        time_since_last = time.time() - self._last_request_time
        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    def _refresh_oauth_if_needed(self, threshold_minutes: int = 59):
        """Refresh OAuth token if it's about to expire."""
        if not self._oauth:
            return
        
        try:
            # Check token age
            current_time = datetime.datetime.now().timestamp()
            token_age = current_time - self._oauth.token_time
            
            if token_age >= threshold_minutes * 60:
                logger.info("Refreshing Yahoo OAuth token...")
                time.sleep(max(3600 - token_age + 5, 0))  # Wait for token to expire
                
                self._oauth = OAuth2(None, None, from_file="oauth2.json")
                self._gm = yfa.Game(self._oauth, "nfl")
                
                logger.info("OAuth token refreshed")
                
        except Exception as e:
            logger.error(f"Failed to refresh OAuth token: {e}")
    
    def _safe_api_call(self, func, *args, max_retries: int = 3, **kwargs):
        """
        Make a safe API call with retry logic.
        
        Args:
            func: Function to call
            max_retries: Maximum number of retry attempts
            *args, **kwargs: Arguments for the function
            
        Returns:
            API response
        """
        self._rate_limit()
        self._refresh_oauth_if_needed()
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = (2 ** attempt) * 5
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {max_retries} attempts")
                    raise
    
    def get_user_leagues(self) -> Dict:
        """Get all NFL leagues for the authenticated user."""
        logger.info("Fetching user leagues...")
        
        def _get_leagues():
            profile = self._gm.yhandler.get_teams_raw()["fantasy_content"]
            return profile["users"]["0"]["user"][1]["games"]
        
        return self._safe_api_call(_get_leagues)
    
    def get_league_settings(self, lg_id: str) -> Dict:
        """Get league settings and scoring configuration."""
        logger.info(f"Fetching league settings for {lg_id}...")
        
        def _get_settings():
            lg = self._gm.to_league(lg_id)
            return lg.yhandler.get_settings_raw(lg_id)
        
        return self._safe_api_call(_get_settings)
    
    def get_all_players(self, lg_id: str, injury_tries: int = 10) -> List[Dict]:
        """
        Get all NFL players eligible for the league.
        
        Args:
            lg_id: Yahoo league ID
            injury_tries: Max attempts to get injury data
            
        Returns:
            List of player dictionaries
        """
        logger.info("Fetching all players...")
        
        lg = self._gm.to_league(lg_id)
        
        # Try multiple times to get injury data
        for attempt in range(injury_tries):
            players = []
            
            # Get rostered players
            players.extend(self._get_players_by_status(lg, "T"))  # Taken
            
            # Get available players  
            players.extend(self._get_players_by_status(lg, "A"))  # Available
            
            # Check if we got injury data
            players_df = pd.DataFrame(players)
            if not players_df.empty and not players_df.get('status', pd.Series()).isnull().all():
                logger.info(f"Got injury data on attempt {attempt + 1}")
                break
            
            if attempt < injury_tries - 1:
                logger.warning(f"No injury data on attempt {attempt + 1}, retrying...")
                time.sleep(2)
        
        logger.info(f"Fetched {len(players)} players")
        return players
    
    def _get_players_by_status(self, lg, status: str) -> List[Dict]:
        """Get players by availability status (T=Taken, A=Available)."""
        players = []
        
        for page_ind in range(100):  # Pagination
            def _get_page():
                return lg.yhandler.get_players_raw(lg.league_id, page_ind * 25, status)
            
            try:
                page = self._safe_api_call(_get_page)
                page_players = page["fantasy_content"]["league"][1]["players"]
                
                if not page_players:  # No more pages
                    break
                
                # Process players on this page
                for player_ind in range(page_players["count"]):
                    player_data = page_players[str(player_ind)]["player"][0]
                    player = self._process_player_data(player_data)
                    players.append(player)
                    
            except Exception as e:
                logger.error(f"Failed to get players page {page_ind}: {e}")
                break
        
        return players
    
    def _process_player_data(self, player_data: List[Dict]) -> Dict:
        """Process raw Yahoo player data into clean format."""
        vals = {}
        
        for field in player_data:
            if isinstance(field, dict):
                vals.update(field)
        
        # Clean up data
        if 'name' in vals and isinstance(vals['name'], dict):
            vals['name'] = vals['name']['full']
        
        if 'eligible_positions' in vals:
            vals['eligible_positions'] = [
                pos['position'] for pos in vals['eligible_positions']
            ]
        
        if 'bye_weeks' in vals and isinstance(vals['bye_weeks'], dict):
            vals['bye_weeks'] = vals['bye_weeks']['week']
        
        return vals
    
    def get_all_rosters(self, lg_id: str, week: int) -> Dict[str, List[Dict]]:
        """Get current rosters for all teams."""
        logger.info(f"Fetching all rosters for week {week}...")
        
        lg = self._gm.to_league(lg_id)
        rosters = {}
        
        # Get team list first
        league_info = self._safe_api_call(
            lg.yhandler.get_standings_raw, lg_id
        )["fantasy_content"]
        teams_info = league_info["league"][1]["standings"][0]["teams"]
        
        teams = [
            {
                "team_key": teams_info[str(ind)]["team"][0][0]["team_key"],
                "name": teams_info[str(ind)]["team"][0][2]["name"],
            }
            for ind in range(teams_info["count"])
        ]
        
        # Get roster for each team
        for team in teams:
            def _get_roster():
                tm = lg.to_team(team["team_key"])
                return pd.DataFrame(tm.roster(week))
            
            try:
                roster_df = self._safe_api_call(_get_roster)
                rosters[team["name"]] = roster_df.to_dict('records') if not roster_df.empty else []
            except Exception as e:
                logger.warning(f"Failed to get roster for {team['name']}: {e}")
                rosters[team["name"]] = []
        
        return rosters
    
    def get_league_schedule(self, lg_id: str, teams: List[Dict], season: int, week: int) -> pd.DataFrame:
        """Get fantasy league schedule."""
        logger.info("Fetching league schedule...")
        
        lg = self._gm.to_league(lg_id)
        schedule = []
        
        for team in teams:
            tm = lg.to_team(team["team_key"])
            
            # Get matchups for each week
            playoff_start = 14  # Default, should come from settings
            limit = max(playoff_start, week + 1)
            
            for w in range(1, limit):
                def _get_matchup():
                    return tm.yhandler.get_matchup_raw(tm.team_key, w)
                
                try:
                    matchup = self._safe_api_call(_get_matchup)
                    matchup_data = matchup["fantasy_content"]["team"][1]["matchups"]
                    
                    if "0" in matchup_data:
                        team_1 = matchup_data["0"]["matchup"]["0"]["teams"]["0"]["team"]
                        team_2 = matchup_data["0"]["matchup"]["0"]["teams"]["1"]["team"]
                        
                        schedule.append({
                            "week": w,
                            "team_1": team_1[0][2]["name"],
                            "team_2": team_2[0][2]["name"],
                            "score_1": float(team_1[1]["team_points"]["total"]),
                            "score_2": float(team_2[1]["team_points"]["total"]),
                        })
                        
                except Exception as e:
                    logger.warning(f"Failed to get matchup for week {w}: {e}")
        
        return pd.DataFrame(schedule).drop_duplicates().reset_index(drop=True)
    
    def get_current_week(self, lg_id: str) -> int:
        """Get current NFL week."""
        lg = self._gm.to_league(lg_id)
        return lg.current_week()
