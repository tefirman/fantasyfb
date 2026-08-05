"""
Fantasy league schedule management.

Handles fetching fantasy schedules and preparing schedule data for simulations.
"""

from ..data.platform_client import FantasyPlatformClient


class ScheduleManager:
    """
    Manages fantasy league schedule operations including regular season and postseason.
    """

    def __init__(self, client: FantasyPlatformClient, teams, settings, lg_id, latest_season):
        """
        Initialize the schedule manager.

        Args:
            client: FantasyPlatformClient instance
            teams: List of team dictionaries
            settings: League settings dictionary
            lg_id: League ID
            latest_season: The most recent NFL season year
        """
        self.client = client
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
        self.client.refresh_oauth()

        schedule = self._pull_basic_schedule(as_of)
        schedule = self._clean_schedule(schedule, as_of, team_key)

        return schedule

    def _pull_basic_schedule(self, as_of):
        """Pull the basic fantasy schedule from the active platform client."""
        limit_week = (
            max(self.settings["playoff_start_week"], as_of % 100 + 1)
            if as_of
            else self.settings["playoff_start_week"]
        )
        # client.get_schedule computes its own limit as
        # max(playoff_start_week, current_week + 1); passing limit_week - 1
        # as current_week reproduces limit_week exactly.
        return self.client.get_schedule(
            self.teams,
            limit_week - 1,
            self.settings["playoff_start_week"],
            end_week=self.settings["end_week"],
        )

    def _clean_schedule(self, schedule, as_of, team_key):
        """Clean and format the schedule DataFrame."""
        # Standardize team order (alphabetical)
        switch = schedule.team_1 > schedule.team_2
        # .values below must be copied: since score_1/score_2 are adjacent
        # same-dtype columns, pandas' block manager can return a view into
        # the same underlying block being assigned into, so an uncopied
        # .values silently aliases source and destination mid-assignment
        # (observed: both score_1 and score_2 end up with score_2's value).
        schedule.loc[switch, ["team_1", "team_2"]] = (
            schedule.loc[switch, ["team_2", "team_1"]].values.copy()
        )
        schedule.loc[switch, ["score_1", "score_2"]] = (
            schedule.loc[switch, ["score_2", "score_1"]].values.copy()
        )
        
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
