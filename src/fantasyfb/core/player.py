# fantasyfb/core/player.py
"""
Player model - represents individual NFL players with their stats and projections.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class Player:
    """
    Represents an NFL player with fantasy-relevant information.
    
    This is a simple data class that can be used for type safety
    and cleaner code when working with individual players.
    """

    # Basic info
    name: str
    position: str
    team: str
    player_id_yahoo: Optional[int] = None
    player_id_sr: Optional[str] = None

    # Fantasy info
    fantasy_team: Optional[str] = None
    selected_position: Optional[str] = None
    starter: bool = False

    # Stats and projections
    points_avg: float = 0.0
    points_stdev: float = 0.0
    points_rate: float = 0.0
    war: float = 0.0

    # Situational factors
    bye_week: Optional[int] = None
    injury_status: Optional[str] = None
    until: Optional[int] = None  # Week injured until
    depth_chart_position: float = 1.0
    pct_rostered: float = 0.0

    # Game factors
    game_factor: float = 1.0
    opp_factor: float = 0.0
    string_factor: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check if player is available (not on any fantasy team)."""
        return self.fantasy_team is None

    @property
    def is_injured(self) -> bool:
        """Check if player is currently injured."""
        return self.injury_status in ["O", "D", "SUSP", "IR", "PUP-R", "PUP-P", "NFI-R", "NA"]

    @property
    def projected_points(self) -> float:
        """Get projected points for current week."""
        return self.points_avg * self.game_factor

    def __str__(self) -> str:
        """String representation of the player."""
        return f"{self.name} ({self.position}, {self.team})"

    def __repr__(self) -> str:
        """Detailed representation of the player."""
        return (f"Player(name='{self.name}', position='{self.position}', "
                f"team='{self.team}', war={self.war:.2f})")

    @classmethod
    def from_dataframe_row(cls, row: pd.Series) -> 'Player':
        """
        Create Player instance from a pandas DataFrame row.
        
        Args:
            row: pandas Series with player data
            
        Returns:
            Player instance
        """
        return cls(
            name=row.get('name', ''),
            position=row.get('position', ''),
            team=row.get('current_team', ''),
            player_id_yahoo=row.get('player_id'),
            player_id_sr=row.get('player_id_sr'),
            fantasy_team=row.get('fantasy_team'),
            selected_position=row.get('selected_position'),
            starter=row.get('starter', False),
            points_avg=row.get('points_avg', 0.0),
            points_stdev=row.get('points_stdev', 0.0),
            points_rate=row.get('points_rate', 0.0),
            war=row.get('WAR', 0.0),
            bye_week=row.get('bye_week'),
            injury_status=row.get('status'),
            until=row.get('until'),
            depth_chart_position=row.get('string', 1.0),
            pct_rostered=row.get('pct_rostered', 0.0),
            game_factor=row.get('game_factor', 1.0),
            opp_factor=row.get('opp_factor', 0.0),
            string_factor=row.get('string_factor', 0.0),
        )

    def to_dict(self) -> dict:
        """
        Convert Player to dictionary format.
        
        Returns:
            Dictionary representation of the player
        """
        return {
            'name': self.name,
            'position': self.position,
            'current_team': self.team,
            'player_id': self.player_id_yahoo,
            'player_id_sr': self.player_id_sr,
            'fantasy_team': self.fantasy_team,
            'selected_position': self.selected_position,
            'starter': self.starter,
            'points_avg': self.points_avg,
            'points_stdev': self.points_stdev,
            'points_rate': self.points_rate,
            'WAR': self.war,
            'bye_week': self.bye_week,
            'status': self.injury_status,
            'until': self.until,
            'string': self.depth_chart_position,
            'pct_rostered': self.pct_rostered,
            'game_factor': self.game_factor,
            'opp_factor': self.opp_factor,
            'string_factor': self.string_factor,
        }


def dataframe_to_players(df: pd.DataFrame) -> List[Player]:
    """
    Convert a DataFrame of player data to a list of Player objects.
    
    Args:
        df: DataFrame with player data
        
    Returns:
        List of Player instances
    """
    return [Player.from_dataframe_row(row) for _, row in df.iterrows()]


def players_to_dataframe(players: List[Player]) -> pd.DataFrame:
    """
    Convert a list of Player objects to a DataFrame.
    
    Args:
        players: List of Player instances
        
    Returns:
        DataFrame with player data
    """
    return pd.DataFrame([player.to_dict() for player in players])
