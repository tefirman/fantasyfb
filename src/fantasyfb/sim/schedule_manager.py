"""
Fantasy league schedule management.

Handles fetching fantasy schedules and preparing schedule data for simulations.
"""

import pandas as pd


class ScheduleManager:
    """
    Manages fantasy league schedule operations including regular season and postseason.
    """
    
    def __init__(self, yahoo_client, teams, settings, lg_id, latest_season):
        """
        Initialize the schedule manager.
        
        Args:
            yahoo_client: YahooFantasyClient instance
            teams: List of team dictionaries
            settings: League settings dictionary
            lg_id: League ID
            latest_season: The most recent NFL season year
        """
        self.yahoo_client = yahoo_client
        self.teams = teams
        self.settings = settings
        self.lg_id = lg_id
        self.latest_season = latest_season
    
    def get_schedule(self, season, week, current_week, team_key=None):
        """
        Pulls the fantasy schedule for the season in question as well as
        scores for all matchups up to the week in question.

        Args:
            season: Season year
            week: Current week
            current_week: Retained for API compatibility; no longer used
                (schedule treats the as_of week as "start of week N" for any
                value of `week`).
            team_key: Team key for identifying "me" column

        Returns:
            DataFrame with fantasy schedule
        """
        as_of = season * 100 + week
        self.yahoo_client.refresh_oauth()

        schedule = self._pull_basic_schedule(as_of)
        schedule = self._clean_schedule(schedule, as_of, team_key)

        return schedule
    
    def _pull_basic_schedule(self, as_of):
        """Pull the basic fantasy schedule from Yahoo API."""
        schedule = pd.DataFrame()
        
        for team in self.teams:
            tm = self.yahoo_client.lg.to_team(team["team_key"])
            limit = (
                max(self.settings["playoff_start_week"], as_of % 100 + 1)
                if as_of
                else self.settings["playoff_start_week"]
            )
            # Cap at the league's end_week + 1 so --week N > end_week
            # doesn't infinite-retry pulling matchups for a week that
            # doesn't exist in Yahoo.
            limit = min(limit, self.settings["end_week"] + 1)
            
            for week in range(1, limit):
                while True:
                    try:
                        matchup = tm.yhandler.get_matchup_raw(tm.team_key, week)
                        matchup = matchup["fantasy_content"]["team"][1]["matchups"]
                        break
                    except:
                        print("Matchup query failed... Waiting 30 seconds and trying again...")
                        import time
                        time.sleep(30)
                
                if "0" in matchup.keys():
                    team_1 = matchup["0"]["matchup"]["0"]["teams"]["0"]["team"]
                    team_2 = matchup["0"]["matchup"]["0"]["teams"]["1"]["team"]
                    schedule = pd.concat([schedule,
                        pd.DataFrame({
                            "week": [week],
                            "team_1": [team_1[0][2]["name"]],
                            "team_2": [team_2[0][2]["name"]],
                            "score_1": [team_1[1]["team_points"]["total"]],
                            "score_2": [team_2[1]["team_points"]["total"]],
                        })],
                        ignore_index=True,
                    )
        
        schedule.score_1 = schedule.score_1.astype(float)
        schedule.score_2 = schedule.score_2.astype(float)
        
        return schedule
    
    def _clean_schedule(self, schedule, as_of, team_key):
        """Clean and format the schedule DataFrame."""
        # Standardize team order (alphabetical)
        switch = schedule.team_1 > schedule.team_2
        schedule.loc[switch, "temp"] = schedule.loc[switch, "team_1"]
        schedule.loc[switch, "team_1"] = schedule.loc[switch, "team_2"]
        schedule.loc[switch, "team_2"] = schedule.loc[switch, "temp"]
        schedule.loc[switch, "temp"] = schedule.loc[switch, "score_1"].astype(float)
        schedule.loc[switch, "score_1"] = schedule.loc[switch, "score_2"].astype(float)
        schedule.loc[switch, "score_2"] = schedule.loc[switch, "temp"].astype(float)
        
        # Remove duplicates and sort
        schedule = (
            schedule[["week", "team_1", "team_2", "score_1", "score_2"]]
            .drop_duplicates()
            .sort_values(by=["week", "team_1", "team_2"])
            .reset_index(drop=True)
        )
        
        # Add "me" column if team_key provided
        if team_key:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == team_key
            ]
            if team_name:
                team_name = team_name[0]
                schedule["me"] = (schedule["team_1"] == team_name) | (
                    schedule["team_2"] == team_name
                )
        
        # Treat the as_of week (and anything after) as not-yet-played.
        # `--week N` consistently means "start of week N"; the simulator
        # locks in any prior weeks' real scores. To see end-of-season
        # state, pass a week past the championship (e.g. --week 18).
        if as_of:
            schedule.loc[schedule.week >= as_of % 100, "score_1"] = 0.0
            schedule.loc[schedule.week >= as_of % 100, "score_2"] = 0.0

        return schedule
