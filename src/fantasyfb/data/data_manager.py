# fantasyfb/data/data_manager.py
"""
Data Manager - handles all data loading, caching, and API interactions.
"""

import datetime
import logging
import os
from typing import Dict, List, Tuple

import pandas as pd

from ..utils import sportsref_nfl as sr
from ..utils.cache import DataCache
from .yahoo_client import YahooClient

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

    def load_fantasy_teams(self, lg_id: str) -> List[Dict]:
        """Load all fantasy teams in the league."""
        cache_key = f"fantasy_teams_{lg_id}"
        cached = self.cache.get_cached_data(cache_key, max_age_hours=24)

        if cached is not None:
            return cached

        logger.info("Loading fantasy teams...")

        # Use the YahooClient's method to get league standings
        league_info = self.yahoo_client.get_league_standings(lg_id)
        teams_info = league_info["fantasy_content"]["league"][1]["standings"][0]["teams"]

        teams = []
        for ind in range(teams_info["count"]):
            team_data = teams_info[str(ind)]["team"][0]
            team = {
                "team_key": team_data[0]["team_key"],
                "name": team_data[2]["name"],
            }

            # Add manager if available
            try:
                if len(team_data) > 3 and "managers" in team_data[-1]:
                    team["manager"] = team_data[-1]["managers"][0]["manager"]["nickname"]
            except:
                team["manager"] = "Unknown"

            teams.append(team)

        self.cache.save_data(cache_key, teams)
        return teams

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
        rosters = self.yahoo_client.get_league_rosters(lg_id, week)

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
        settings_content = settings_raw["fantasy_content"]["league"][1]["settings"][0]

        # Extract key league settings
        settings = {
            "playoff_start_week": int(settings_content["playoff_start_week"]),
            "num_playoff_teams": int(settings_content["num_playoff_teams"]),
            "uses_playoff_reseeding": settings_content.get("uses_playoff_reseeding", False),
        }

        # Add other relevant settings that might be useful
        if "max_teams" in settings_content:
            settings["max_teams"] = int(settings_content["max_teams"])

        if "trade_end_date" in settings_content:
            settings["trade_end_date"] = settings_content["trade_end_date"]

        if "waiver_type" in settings_content:
            settings["waiver_type"] = settings_content["waiver_type"]

        return settings

    def _process_scoring(self, settings_raw: Dict) -> Dict:
        """Process scoring settings from raw Yahoo API response."""
        settings_content = settings_raw["fantasy_content"]["league"][1]["settings"][0]

        # Extract scoring categories and modifiers
        categories = pd.DataFrame([
            stat["stat"] for stat in settings_content["stat_categories"]["stats"]
        ])

        modifiers = pd.DataFrame([
            stat["stat"] for stat in settings_content["stat_modifiers"]["stats"]
        ])

        # Merge categories with their point values
        scoring_df = pd.merge(
            left=categories,
            right=modifiers,
            how="inner",
            on="stat_id",
        )[["display_name", "value"]].astype({"value": float})

        # Handle the interception naming issue
        scoring_df.loc[
            (scoring_df.display_name == "Int") & (scoring_df.value <= 0),
            "display_name"
        ] = "Int Thrown"

        # Convert to dictionary and remove duplicates
        scoring = (
            scoring_df.drop_duplicates(subset=["display_name"])
            .set_index("display_name")["value"]
            .to_dict()
        )

        # Add missing standard scoring categories with default values
        default_scoring = {
            "Pass Comp": 0.0,
            "Pass 1D": 0.0,
            "Rush Att": 0.0,
            "Rush 1D": 0.0,
            "Rec 1D": 0.0,
            "TE Rec Bonus": 0.0,
            "TE 1D Bonus": 0.0,
            "Pass 300+": 0.0,
            "Rush 100+": 0.0,
            "Rec 100+": 0.0,
            "Ret Yds": 0.0,
        }

        # Add defaults for missing categories
        for category, default_value in default_scoring.items():
            if category not in scoring:
                scoring[category] = default_value

        # Handle field goal scoring if missing
        if "FG 0-19" not in scoring:
            scoring["FG 0-19"] = 3.0

        # Handle reception scoring if missing (PPR vs non-PPR)
        if "Rec" not in scoring:
            scoring["Rec"] = 0.0

        return scoring

    def _process_roster_spots(self, settings_raw: Dict) -> pd.DataFrame:
        """Process roster spot configuration from raw Yahoo API response."""
        settings_content = settings_raw["fantasy_content"]["league"][1]["settings"][0]

        # Extract roster positions from the API response
        roster_positions = [
            pos["roster_position"]
            for pos in settings_content["roster_positions"]
        ]

        # Convert to DataFrame
        roster_spots = pd.DataFrame(roster_positions)

        # Ensure count column is integer
        roster_spots['count'] = roster_spots['count'].astype(int)

        # The DataFrame should have columns: ['position', 'count']
        # where position includes things like 'QB', 'RB', 'WR', 'TE', 'W/R/T', 'K', 'DEF', 'BN', 'IR'
        # and count is the number of roster spots for each position

        return roster_spots

    def _process_players(self, players_raw: List[Dict], rosters: Dict) -> pd.DataFrame:
        """Process raw player data from Yahoo API into clean DataFrame format."""

        # Convert raw player data to DataFrame
        players = pd.DataFrame(players_raw)

        if players.empty:
            return pd.DataFrame()

        # Ensure player_id is integer
        players.player_id = players.player_id.astype(int)

        # Process fantasy team assignments from rosters
        selected = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])

        for team_name, roster_players in rosters.items():
            if not roster_players:  # Skip empty rosters
                continue

            roster_df = pd.DataFrame(roster_players)
            if not roster_df.empty:
                # Check if players are missing from main players list
                missing_players = ~roster_df.player_id.isin(players.player_id)
                if missing_players.any():
                    missing_names = roster_df.loc[missing_players, "name"].tolist()
                    logger.warning(f"Some players missing from main list: {', '.join(missing_names)}")

                # Add fantasy team assignment
                roster_df["fantasy_team"] = team_name
                selected = pd.concat([
                    selected,
                    roster_df[["player_id", "selected_position", "fantasy_team"]]
                ], ignore_index=True)

        # Merge roster assignments with player data
        players = pd.merge(left=players, right=selected, how="left", on="player_id")

        # Handle missing fantasy_team column
        if "fantasy_team" not in players.columns:
            players["fantasy_team"] = None

        # Handle defense name conflicts (multiple DEF with same names)
        players.loc[players.player_id == 100014, "name"] += " Rams"
        players.loc[players.player_id == 100024, "name"] += " Chargers"
        players.loc[players.player_id == 100020, "name"] += " Jets"
        players.loc[players.player_id == 100019, "name"] += " Giants"

        # Extract primary position from display_position
        players["position"] = players.display_position.apply(
            lambda x: [pos for pos in x.split(',') if pos in ['QB','WR','TE','K','RB','DEF']][0]
            if pd.notna(x) else 'UNKNOWN'
        )

        # Select and rename columns for consistency
        processed_players = players[[
            "name",
            "eligible_positions",
            "selected_position",
            "status",
            "player_id",
            "editorial_team_abbr",
            "fantasy_team",
            "position"
        ]].copy()

        return processed_players

    def _add_external_player_data(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add external data like team mappings, injuries, depth charts, etc."""

        # Apply name corrections between Yahoo and Pro Football Reference
        players = self._apply_name_corrections(players)

        # Map team abbreviations from Yahoo to NFL standard
        players = self._map_team_abbreviations(players)

        # Map player IDs between Yahoo and SportsRef systems
        players = self._map_player_ids(players, season)

        # Add injury data and projections
        players = self._add_injury_data(players, season)

        # Add bye week information
        players = self._add_bye_weeks(players, season)

        # Add roster percentages (how often players are rostered across Yahoo)
        players = self._add_roster_percentages(players)

        # Add depth chart information
        players = self._add_depth_charts(players, season)

        return players

    def _apply_name_corrections(self, players: pd.DataFrame) -> pd.DataFrame:
        """Apply name corrections between Yahoo and Pro Football Reference."""
        corrections = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/name_corrections.csv"
        )

        players = pd.merge(left=players, right=corrections, how="left", on="name")
        to_fix = ~players.new_name.isnull()
        players.loc[to_fix, "name"] = players.loc[to_fix, "new_name"]

        return players.drop(columns=['new_name'], errors='ignore')

    def _map_team_abbreviations(self, players: pd.DataFrame) -> pd.DataFrame:
        """Map Yahoo team abbreviations to NFL standard abbreviations."""
        # Load NFL team mappings
        nfl_teams = self.load_nfl_teams()

        # Merge to get current_team (NFL standard abbreviation)
        players = pd.merge(
            left=players,
            right=nfl_teams[["real_abbrev", "yahoo"]].rename(
                columns={"yahoo": "editorial_team_abbr", "real_abbrev": "current_team"}
            ),
            how="inner",
            on="editorial_team_abbr",
        )

        return players

    def _map_player_ids(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Map between Yahoo player IDs and SportsRef player IDs."""
        # Load NFL rosters for ID mapping
        nfl_rosters = sr.get_bulk_rosters(season - 1, season, "NFLRosters.csv")
        nfl_rosters = nfl_rosters.rename(columns={
            'player': 'name',
            'player_id': 'player_id_sr',
            'team': 'current_team'
        })

        # Map IDs based on name and team
        players = pd.merge(
            left=players,
            right=nfl_rosters[['name', 'current_team', 'player_id_sr']].drop_duplicates(),
            how='left',
            on=['name', 'current_team']
        )

        # Handle special cases
        # Two Michael Carter's on the same team issue
        players = players.loc[~players.player_id_sr.isin(['CartMi02'])].reset_index(drop=True)

        # Check for duplicate IDs
        id_check = players.groupby('player_id_sr').size()
        if (id_check > 1).any():
            duplicates = id_check[id_check > 1].index.tolist()
            logger.warning(f'Found duplicate player IDs: {", ".join(duplicates)}')

        # Handle defenses
        defenses = players.position.isin(['DEF'])
        players.loc[defenses, 'player_id_sr'] = players.loc[defenses, 'name']

        # Handle missing mappings with draft data
        latest_draft = sr.get_draft(season)[['player', 'player_id', 'team_abbrev']]\
            .rename(columns={'player': 'name', 'player_id': 'player_id_sr', 'team_abbrev': 'current_team'})

        missing = players.player_id_sr.isnull() & players.name.isin(latest_draft.name.unique())
        if missing.any():
            unsigned = players[missing].reset_index(drop=True)
            del unsigned['player_id_sr']
            unsigned = pd.merge(
                left=unsigned,
                right=latest_draft[['name', 'current_team', 'player_id_sr']].drop_duplicates(subset=['name'], keep='first'),
                how='inner',
                on=['name', 'current_team']
            )
            players = pd.concat([players[~missing], unsigned], ignore_index=True)

        # Use Yahoo ID as fallback for still missing
        still_missing = players.player_id_sr.isnull()
        players.loc[still_missing, 'player_id_sr'] = players.loc[still_missing, 'player_id']

        return players

    def _add_injury_data(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add injury projections and status."""
        players["until"] = float("NaN")

        # Load injury projections for current season
        try:
            inj_proj = pd.read_csv(
                "https://raw.githubusercontent.com/"
                + "tefirman/fantasy-data/main/fantasyfb/injured_list.csv"
            )

            # Use current week - we'll estimate it from the season
            current_week = 1  # Default fallback
            try:
                current_year = datetime.datetime.now().year
                if season == current_year or (season == current_year - 1 and datetime.datetime.now().month < 6):
                    # It's the current season, estimate week from date
                    current_week = min(max(1, (datetime.datetime.now() - datetime.datetime(current_year, 9, 1)).days // 7), 18)
            except:
                current_week = 1

            inj_proj = inj_proj.loc[inj_proj.until >= current_week]

            players = pd.merge(
                left=players,
                right=inj_proj,
                how="left",
                on=["player_id_sr", "name", "position"],
                suffixes=('', '_proj')
            )

            # Use projection where available
            has_proj = ~players.until_proj.isnull()
            if has_proj.any():
                # Convert to numeric, handling any problematic values like empty lists
                proj_values = players.loc[has_proj, 'until_proj'].copy()
                # Handle empty lists and other non-numeric values
                proj_values = proj_values.apply(lambda x: float('nan') if isinstance(x, list) and len(x) == 0 else x)
                proj_values = pd.to_numeric(proj_values, errors='coerce')
                players.loc[has_proj, 'until'] = proj_values
            players = players.drop(columns=['until_proj'], errors='ignore')

        except Exception as e:
            logger.warning(f"Could not load injury projections: {e}")

        return players

    def _add_bye_weeks(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add bye week information."""
        # Calculate bye weeks from NFL schedule
        nfl_schedule = self.load_nfl_schedule(season)

        byes = pd.DataFrame()
        for team in nfl_schedule.team.unique():
            bye_week = 1
            while (
                (nfl_schedule.team == team) &
                (nfl_schedule.season == season) &
                (nfl_schedule.week == bye_week)
            ).any():
                bye_week += 1

            byes = pd.concat([
                byes,
                pd.DataFrame({"current_team": [team], "bye_week": [bye_week]})
            ], ignore_index=True)

        players = pd.merge(left=players, right=byes, how="left", on="current_team")
        return players

    def _add_roster_percentages(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add roster percentage data from Yahoo."""
        # This would use your existing roster percentage logic from the original code
        # For now, just add a placeholder
        players['pct_rostered'] = 0.0

        # TODO: Implement actual roster percentage fetching
        # This involves paginated API calls to Yahoo with player IDs
        # Following the pattern from the original add_roster_pcts method

        return players

    def _add_depth_charts(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add depth chart information."""
        # Note: We don't have access to lg_id here, so we'll use a simpler approach
        # For current season, try to use current depth charts; otherwise use defaults

        current_year = datetime.datetime.now().year
        is_current_season = (season == current_year or
                           (season == current_year - 1 and datetime.datetime.now().month < 6))

        if is_current_season:
            # Use current depth charts from ESPN
            try:
                depth_charts = sr.get_all_depth_charts()
                depth_charts = depth_charts.rename(columns={
                    'player': 'name',
                    'pos': 'position',
                    'team': 'current_team'
                })

                players = pd.merge(
                    left=players,
                    right=depth_charts,
                    how="left",
                    on=["current_team", "name", 'position']
                )
            except Exception as e:
                logger.warning(f"Could not load depth charts: {e}")
                players['string'] = 2.0
        else:
            # Use historical data - would need to load stats
            players['string'] = 2.0  # Default value

        # Fill missing depth chart data
        players.loc[players.position == 'DEF', 'string'] = 1.0
        players.string = players.string.fillna(2.0)

        return players

    def _process_nfl_schedule(self, schedule: pd.DataFrame) -> pd.DataFrame:
        """Process NFL schedule data into format needed for analysis."""

        # Select and rename columns for consistency
        processed_schedule = schedule[[
            "season",
            "game_date",
            "week",
            "team1_abbrev",
            "team2_abbrev",
            "elo1_pre",
            "elo2_pre",
            "elo_diff",
        ]].rename(columns={
            "game_date": "date",
            "team1_abbrev": "home_team",
            "team2_abbrev": "away_team",
            "elo1_pre": "home_elo",
            "elo2_pre": "away_elo",
            "elo_diff": "home_elo_diff",
        })

        # Calculate away team elo difference (opposite of home)
        processed_schedule["away_elo_diff"] = -1 * processed_schedule["home_elo_diff"]

        # Create separate rows for home and away teams
        home_games = processed_schedule[[
            "season", "week", "date", "home_team", "home_elo_diff", "away_elo"
        ]].rename(columns={
            "home_team": "team",
            "home_elo_diff": "elo_diff",
            "away_elo": "opp_elo"
        })
        home_games["home_away"] = "Home"

        away_games = processed_schedule[[
            "season", "week", "date", "away_team", "away_elo_diff", "home_elo"
        ]].rename(columns={
            "away_team": "team",
            "away_elo_diff": "elo_diff",
            "home_elo": "opp_elo"
        })
        away_games["home_away"] = "Away"

        # Combine home and away games
        final_schedule = pd.concat([home_games, away_games], ignore_index=True)

        # Normalize elo values for easier analysis
        final_schedule.elo_diff = final_schedule.elo_diff / 1500
        final_schedule.opp_elo = 1500 / final_schedule.opp_elo

        # Handle date formatting (Yahoo API sometimes returns different formats)
        try:
            final_schedule.date = pd.to_datetime(final_schedule.date, format="%Y-%m-%d")
        except:
            try:
                # Handle manual Excel updates that change date format
                final_schedule.date = pd.to_datetime(final_schedule.date, format="%m/%d/%y")
            except:
                logger.warning("Could not parse dates in NFL schedule")
                final_schedule.date = pd.to_datetime(final_schedule.date, errors='coerce')

        # Sort by season and week for consistency
        final_schedule = final_schedule.sort_values(
            by=["season", "week"],
            ignore_index=True
        )

        return final_schedule
