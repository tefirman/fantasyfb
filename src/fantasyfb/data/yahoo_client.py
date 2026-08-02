"""
Yahoo Fantasy API client.

This module provides a clean interface for interacting with Yahoo's Fantasy API,
handling authentication, rate limiting, and common API operations.
"""

import datetime
import json
import os
import time
import traceback
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yahoo_fantasy_api as yfa
from dotenv import load_dotenv
from pytz import timezone
from yahoo_oauth import OAuth2

from .platform_client import FantasyPlatformClient


class YahooFantasyClient(FantasyPlatformClient):
    """
    Client for interacting with Yahoo Fantasy API.

    Handles OAuth authentication, rate limiting, and provides clean methods
    for common fantasy football operations.
    """

    def __init__(self):
        """Initialize the Yahoo client with credentials and OAuth."""
        self.oauth = None
        self.gm = None
        self.lg = None
        self.lg_id = None
        self._my_team_key = None

        self._load_credentials()
        self._load_oauth()
    
    def _load_credentials(self):
        """Load user credentials from .env file."""
        load_dotenv()
        if "CONSUMER_KEY" not in os.environ or "CONSUMER_SECRET" not in os.environ:
            print("No valid .env file present, copying from .env.example")
            import shutil
            shutil.copyfile(".env.example", ".env")
        
        # Update .env file if default values are still present
        if (
            os.environ["CONSUMER_KEY"] == "updatekey"
            and os.environ["CONSUMER_SECRET"] == "updatesecret"
        ):
            print("It appears you haven't updated your Yahoo OAuth credentials...")
            print("To get credentials: https://developer.yahoo.com/apps/create/")
            consumer_key = input("Yahoo OAuth Key: ")
            os.system("sed -i 's/updatekey/{}/g' .env".format(consumer_key))
            consumer_secret = input("Yahoo OAuth Secret: ")
            os.system("sed -i 's/updatesecret/{}/g' .env".format(consumer_secret))
            load_dotenv()
            # Previous oauth file is probably bad if it exists
            if os.path.exists("oauth2.json"):
                os.remove("oauth2.json")
    
    def _load_oauth(self):
        """Initialize OAuth2 authentication object."""
        # Create oauth file from credentials if it doesn't exist
        if not os.path.exists("oauth2.json"):
            creds = {
                "consumer_key": os.environ["CONSUMER_KEY"],
                "consumer_secret": os.environ["CONSUMER_SECRET"],
            }
            with open("oauth2.json", "w") as f:
                f.write(json.dumps(creds))
        
        self.oauth = OAuth2(None, None, from_file="oauth2.json")
    
    def refresh_oauth(self, threshold: int = 59):
        """
        Check auth token status and refresh if expired.
        
        Args:
            threshold: Minutes before expiration to refresh token
        """
        if not self.oauth:
            return
            
        diff = (
            datetime.datetime.now(timezone("GMT"))
            - datetime.datetime(1970, 1, 1, 0, 0, 0, 0, timezone("GMT"))
        ).total_seconds() - self.oauth.token_time
        
        if diff >= threshold * 60:
            time.sleep(max(3600 - diff + 5, 0))
            self.oauth = OAuth2(None, None, from_file="oauth2.json")
            self.gm = yfa.Game(self.oauth, "nfl")
            if self.lg_id:
                self.lg = self.gm.to_league(self.lg_id)
    
    def _find_nfl_league_teams(self, season: int) -> Dict[str, str]:
        """
        Locate the user's NFL fantasy team(s) for ``season`` and each one's
        own league id.

        Shared by :meth:`connect_to_league` (which goes on to pick one team
        and open its league) and :meth:`list_team_names` (which only needs
        the names -- e.g. to populate a UI picker before a team is chosen).

        A season's "teams" here can span *multiple distinct leagues* --
        Yahoo groups a user's teams for a season under one ``game`` entry
        even when each team belongs to a different league (observed: two
        teams, two different ``team_key`` league-id segments, i.e. two
        separate leagues that both happen to be for the same season). So
        each team's league id must be read from *that team's own*
        ``team_key`` -- reading it from an arbitrary team (e.g. the first)
        and applying it to whichever team the user actually picked
        connects to the wrong league.

        Returns:
            Dict mapping team name -> that team's league id (its ``team_key``
            with the trailing ``.t.<team_id>`` dropped). Empty if no NFL
            entry is found for that season.
        """
        self.gm = yfa.Game(self.oauth, "nfl")

        # Get user's fantasy teams
        while True:
            try:
                profile = self.gm.yhandler.get_teams_raw()["fantasy_content"]
                leagues = profile["users"]["0"]["user"][1]["games"]
                break
            except Exception as e:
                print("Teams query failed... Waiting 30 seconds and trying again...")
                print(e)
                time.sleep(30)

        # Find NFL league(s) for the specified season
        for ind in range(leagues["count"] - 1, -1, -1):
            game = leagues[str(ind)]["game"]
            if type(game) == dict:
                continue
            if game[0]["code"] == "nfl" and game[0]["season"] == str(season):
                teams = game[1]["teams"]
                details = [teams[str(ind)]["team"][0] for ind in range(teams["count"])]
                out: Dict[str, str] = {}
                for team in details:
                    name = [val["name"] for val in team if "name" in val][0]
                    team_key = [val["team_key"] for val in team if "team_key" in val][0]
                    out[name] = ".".join(team_key.split(".")[:3])
                return out

        return {}

    def list_team_names(self, season: int) -> List[str]:
        """
        List the user's fantasy team name(s) for ``season``, without
        connecting to any league or picking one -- e.g. to populate a
        dropdown before calling :meth:`connect_to_league`.

        Returns:
            Team names in Yahoo's own order (empty if no NFL entry is found
            for that season). Note distinct names can belong to entirely
            different leagues (see :meth:`_find_nfl_league_teams`).
        """
        return list(self._find_nfl_league_teams(season).keys())

    def connect_to_league(self, season: int, team_name: Optional[str] = None) -> Tuple[str, str]:
        """
        Connect to a fantasy league for the specified season.

        Args:
            season: NFL season year
            team_name: Specific team name if user has multiple teams

        Returns:
            Tuple of (team_name, league_id)
        """
        name_to_lg_id = self._find_nfl_league_teams(season)
        if not name_to_lg_id:
            raise ValueError(f"No NFL fantasy league found for season {season}.")

        names = list(name_to_lg_id.keys())
        if len(names) > 1:
            # Multiple teams (possibly in different leagues) - use provided
            # name or prompt user
            while team_name not in names:
                print("Found multiple fantasy teams: " + ", ".join(names))
                team_name = input("Which team would you like to analyze? ")
        else:
            # Single team
            team_name = names[0]

        # Each team's league id comes from ITS OWN team_key, not an arbitrary
        # one -- see _find_nfl_league_teams docstring for why that matters.
        self.lg_id = name_to_lg_id[team_name]
        # Create league object
        self.lg = self.gm.to_league(self.lg_id)
        self._my_team_key = self.lg.team_key()
        return team_name, self.lg_id

    def get_current_week(self) -> int:
        """
        Get the current fantasy week.

        Returns:
            The league's current week, per Yahoo.
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        return self.lg.current_week()

    def get_my_team_key(self) -> Optional[str]:
        """
        Get the team_key of the team this client is connected as.

        Returns:
            The team_key resolved during connect_to_league(), or None if
            not yet connected.
        """
        return self._my_team_key

    def get_league_config(self) -> Dict:
        """
        Get league settings, scoring, and roster composition in the shape
        FantasyPlatformClient callers expect.

        Returns:
            Dict with 'settings' (including playoff_start_week,
            num_playoff_teams, end_week), 'scoring', and 'roster_spots' keys.
        """
        settings, roster_spots, scoring = self.get_league_settings()
        if "end_week" in settings:
            settings["end_week"] = int(settings["end_week"])
        else:
            settings["end_week"] = settings["playoff_start_week"] + (
                2 if settings["num_playoff_teams"] == 6 else 1
            )
        return {"settings": settings, "scoring": scoring, "roster_spots": roster_spots}

    def get_league_settings(self) -> Tuple[Dict, pd.DataFrame, Dict]:
        """
        Get league settings including roster spots and scoring.
        
        Returns:
            Tuple of (settings_dict, roster_spots_df, scoring_dict)
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        
        settings_json = self.lg.yhandler.get_settings_raw(self.lg_id)
        settings = settings_json["fantasy_content"]["league"][1]["settings"][0]
        settings["playoff_start_week"] = int(settings["playoff_start_week"])
        settings["num_playoff_teams"] = int(settings["num_playoff_teams"])
        
        # Parse roster spots
        roster_spots = pd.DataFrame([
            pos["roster_position"] for pos in settings["roster_positions"]
        ])
        roster_spots['count'] = roster_spots['count'].astype(int)
        
        # Parse scoring
        categories = pd.DataFrame([
            stat["stat"] for stat in settings["stat_categories"]["stats"]
        ])
        modifiers = pd.DataFrame([
            stat["stat"] for stat in settings["stat_modifiers"]["stats"]
        ])
        scoring_df = pd.merge(
            left=categories,
            right=modifiers,
            how="inner",
            on="stat_id",
        )[["display_name", "value"]].astype({"value": float})
        scoring_df.loc[
            (scoring_df.display_name == "Int") & (scoring_df.value <= 0),
            "display_name"
        ] = "Int Thrown"
        scoring = scoring_df.drop_duplicates(subset=["display_name"]).set_index("display_name")['value'].to_dict()
        
        return settings, roster_spots, scoring
    
    def get_fantasy_teams(self) -> List[Dict]:
        """
        Get list of all teams in the league.
        
        Returns:
            List of team dictionaries with keys: team_key, name, manager
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        
        league_info = self.lg.yhandler.get_standings_raw(self.lg_id)["fantasy_content"]
        teams_info = league_info["league"][1]["standings"][0]["teams"]
        
        return [
            {
                "team_key": teams_info[str(ind)]["team"][0][0]["team_key"],
                "name": teams_info[str(ind)]["team"][0][2]["name"],
                "manager": teams_info[str(ind)]["team"][0][-1]['managers'][0]['manager']['nickname'],
            }
            for ind in range(teams_info["count"])
        ]
    
    def get_all_players(self, injury_tries: int = 10) -> pd.DataFrame:
        """
        Get all eligible players with roster percentages and injury status.
        
        Args:
            injury_tries: Number of attempts to get injury statuses
            
        Returns:
            DataFrame with player information
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        
        self.refresh_oauth()
        tries = 0
        
        while tries < injury_tries:
            tries += 1
            players = []
            
            # Get rostered players
            for page_ind in range(100):
                while True:
                    try:
                        page = self.lg.yhandler.get_players_raw(self.lg_id, page_ind * 25, "T")
                        page = page["fantasy_content"]["league"][1]["players"]
                        break
                    except:
                        print("Players query failed... Waiting 30 seconds and trying again...")
                        time.sleep(30)
                
                if page == []:
                    break
                
                for player_ind in range(page["count"]):
                    player = [
                        field for field in page[str(player_ind)]["player"][0]
                        if type(field) == dict
                    ]
                    vals = {}
                    for field in player:
                        vals.update(field)
                    vals["name"] = vals["name"]["full"]
                    vals["eligible_positions"] = [
                        pos["position"] for pos in vals["eligible_positions"]
                    ]
                    vals["bye_weeks"] = vals["bye_weeks"]["week"]
                    players.append(vals)
            
            # Get available players
            for page_ind in range(100):
                while True:
                    try:
                        page = self.lg.yhandler.get_players_raw(self.lg_id, page_ind * 25, "A")
                        page = page["fantasy_content"]["league"][1]["players"]
                        break
                    except:
                        print("Players query failed... Waiting 30 seconds and trying again...")
                        time.sleep(30)
                
                if page == []:
                    break
                
                for player_ind in range(page["count"]):
                    player = [
                        field for field in page[str(player_ind)]["player"][0]
                        if type(field) == dict
                    ]
                    vals = {}
                    for field in player:
                        vals.update(field)
                    vals["name"] = vals["name"]["full"]
                    vals["eligible_positions"] = [
                        pos["position"] for pos in vals["eligible_positions"]
                    ]
                    vals["bye_weeks"] = vals["bye_weeks"]["week"]
                    players.append(vals)
            
            players_df = pd.DataFrame(players)
            players_df.player_id = players_df.player_id.astype(int)
            
            # Check if we got injury statuses
            if not players_df.status.isnull().all():
                break
        
        # Extracting primary position
        players_df["position"] = players_df.display_position.apply(
            lambda x: [pos for pos in x.split(',') if pos in ['QB','WR','TE','K','RB','DEF']][0]
        )

        return players_df
    
    def get_team_rosters(self, teams: List[Dict], week: int) -> pd.DataFrame:
        """
        Get current rosters for all teams.
        
        Args:
            teams: List of team dictionaries from get_fantasy_teams()
            week: Week number to get rosters for
            
        Returns:
            DataFrame with player rosters
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        
        self.refresh_oauth()
        selected = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])
        
        for team in teams:
            while True:
                try:
                    tm = self.lg.to_team(team["team_key"])
                    players = pd.DataFrame(tm.roster(week))
                    break
                except:
                    print("Team roster query failed... Waiting 30 seconds and trying again...")
                    time.sleep(30)
            
            if players.shape[0] == 0:
                continue
            
            players["fantasy_team"] = team["name"]
            selected = pd.concat([
                selected,
                players[["player_id", "selected_position", "fantasy_team"]]
            ], ignore_index=True, sort=False)
        
        return selected
    
    def get_roster_percentages(self, players_df: pd.DataFrame, chunk_size: int = 25) -> pd.DataFrame:
        """
        Get roster percentages for players.
        
        Args:
            players_df: DataFrame with player_id column
            chunk_size: Number of players to query per API call
            
        Returns:
            DataFrame with player_id and pct_rostered columns
        """
        if not self.lg:
            raise ValueError("Must connect to league first")
        
        self.refresh_oauth()
        roster_pcts = pd.DataFrame()
        
        for ind in range(players_df.shape[0] // chunk_size + 1):
            while True:
                try:
                    self.refresh_oauth()
                    chunk = players_df.iloc[chunk_size * ind : chunk_size * (ind + 1)]
                    
                    if chunk.shape[0] == 0:
                        pcts = {"count": 0}
                        break
                    
                    player_ids = chunk.player_id.astype(str).tolist()
                    player_ids = [val.split(".")[0] for val in player_ids if val != "nan"]
                    
                    if len(player_ids) > 0:
                        pcts = self.lg.yhandler.get(
                            "league/{}/players;player_keys={}.p.{}/percent_owned".format(
                                self.lg_id,
                                self.lg_id.split('.')[0],
                                ",{}.p.".format(self.lg_id.split('.')[0]).join(player_ids)
                            )
                        )["fantasy_content"]["league"][1]["players"]
                    else:
                        pcts = {"count": 0}
                    break
                except:
                    err_message = traceback.format_exc()
                    print(err_message)
                    print("Roster percentage query failed... Waiting 30 seconds and trying again...")
                    time.sleep(30)
            
            for player_ind in range(pcts["count"]):
                player = pcts[str(player_ind)]["player"]
                player_id = [int(val["player_id"]) for val in player[0] if "player_id" in val]
                pct_owned = [
                    float(val["value"]) / 100.0
                    for val in player[1]["percent_owned"]
                    if "value" in val
                ]
                if len(pct_owned) == 0:
                    pct_owned = [0.0]
                
                roster_pcts = pd.concat([
                    roster_pcts,
                    pd.DataFrame({
                        "player_id": player_id,
                        "pct_rostered": pct_owned,
                    })
                ], ignore_index=True, sort=False)
        
        return roster_pcts
    
    def get_schedule(
        self,
        teams: List[Dict],
        current_week: int,
        playoff_start_week: int,
        end_week: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Get fantasy league schedule.

        Args:
            teams: List of team dictionaries
            current_week: Current week number
            playoff_start_week: Week when playoffs start
            end_week: Last playable week of the season, if known. Caps the
                query range so requesting a schedule past the end of the
                season doesn't retry against nonexistent weeks.

        Returns:
            DataFrame with schedule information
        """
        if not self.lg:
            raise ValueError("Must connect to league first")

        self.refresh_oauth()
        schedule = pd.DataFrame()

        for team in teams:
            tm = self.lg.to_team(team["team_key"])
            limit = max(playoff_start_week, current_week + 1)
            if end_week:
                limit = min(limit, end_week + 1)

            for week in range(1, limit):
                while True:
                    try:
                        matchup = tm.yhandler.get_matchup_raw(tm.team_key, week)
                        matchup = matchup["fantasy_content"]["team"][1]["matchups"]
                        break
                    except:
                        print("Matchup query failed... Waiting 30 seconds and trying again...")
                        time.sleep(30)
                
                if "0" in matchup.keys():
                    team_1 = matchup["0"]["matchup"]["0"]["teams"]["0"]["team"]
                    team_2 = matchup["0"]["matchup"]["0"]["teams"]["1"]["team"]
                    schedule = pd.concat([
                        schedule,
                        pd.DataFrame({
                            "week": [week],
                            "team_1": [team_1[0][2]["name"]],
                            "team_2": [team_2[0][2]["name"]],
                            "score_1": [team_1[1]["team_points"]["total"]],
                            "score_2": [team_2[1]["team_points"]["total"]],
                        })
                    ], ignore_index=True)
        
        schedule.score_1 = schedule.score_1.astype(float)
        schedule.score_2 = schedule.score_2.astype(float)
        
        return schedule
