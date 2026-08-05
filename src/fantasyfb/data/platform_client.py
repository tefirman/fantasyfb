"""
Fantasy platform client interface.

Defines the contract that every concrete fantasy-platform backend (Yahoo,
Sleeper, ...) must satisfy so that `League` is decoupled from any specific
platform. Both concrete clients are read-only: fantasyfb only analyzes
leagues, it never submits lineups or executes transactions on a user's
behalf, so no write-path methods belong on this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import pandas as pd


class FantasyPlatformClient(ABC):
    """Abstract base for fantasy platform backends."""

    @abstractmethod
    def get_current_week(self) -> int:
        """Current fantasy week for the connected league."""

    @abstractmethod
    def get_league_config(self) -> Dict:
        """League settings, scoring, and roster composition.

        Returns:
            Dict with keys:
                settings -- dict including at least playoff_start_week,
                    num_playoff_teams, end_week (all int)
                scoring -- dict of fantasyfb scoring category -> value
                roster_spots -- DataFrame with 'position'/'count' columns
        """

    @abstractmethod
    def get_fantasy_teams(self) -> List[Dict]:
        """All teams in the league.

        Returns:
            List of dicts with keys: team_key, name, manager.
        """

    @abstractmethod
    def get_all_players(self, injury_tries: int = 10) -> pd.DataFrame:
        """Full eligible player pool for the league."""

    @abstractmethod
    def get_team_rosters(self, teams: List[Dict], week: int) -> pd.DataFrame:
        """Rosters for all teams for the given week.

        Returns:
            DataFrame with columns: player_id, selected_position, fantasy_team.
        """

    @abstractmethod
    def get_schedule(
        self,
        teams: List[Dict],
        current_week: int,
        playoff_start_week: int,
        end_week: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fantasy schedule and scores through the given week.

        Returns:
            DataFrame with columns: week, team_1, team_2, score_1, score_2.
        """

    @abstractmethod
    def get_roster_percentages(
        self, players_df: pd.DataFrame, chunk_size: int = 25
    ) -> Optional[pd.DataFrame]:
        """Roster/ownership percentages for the given players.

        Returns:
            DataFrame with player_id/pct_rostered columns, or None for
            backends with no ownership-percentage concept (e.g. Sleeper).
        """

    @abstractmethod
    def get_my_team_key(self) -> Optional[str]:
        """team_key of the team this client is scoped to, if known."""

    def refresh_oauth(self, threshold: int = 59) -> None:
        """Refresh the auth token if it's near expiration.

        No-op by default; only Yahoo needs this (Sleeper's read API is
        unauthenticated). Kept on the interface so callers don't need to
        special-case which backend they're talking to.
        """
