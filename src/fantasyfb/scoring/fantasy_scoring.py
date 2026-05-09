"""
Fantasy football scoring engine.

This module provides platform-agnostic fantasy point calculation
based on player statistics and configurable scoring settings.
"""

import pandas as pd
from typing import Dict, Union


class FantasyScorer:
    """
    Calculates fantasy points from player statistics using configurable scoring rules.
    
    This class extracts the core scoring logic to work with any fantasy platform
    that can provide player stats in the expected DataFrame format.
    """
    
    def __init__(self, scoring_settings: Dict[str, float]):
        """
        Initialize scorer with league-specific scoring settings.
        
        Args:
            scoring_settings: Dictionary mapping stat categories to point values.
                Expected keys include:
                - 'Rush Yds', 'Rush Att', 'Rush TD', 'Rush 1D'
                - 'Rec', 'Rec Yds', 'Rec TD', 'Rec 1D'  
                - 'Pass Yds', 'Pass Comp', 'Pass TD', 'Pass 1D'
                - 'Int Thrown', 'Fum Lost', 'Ret Yds', 'Ret TD'
                - 'PAT Made', 'FG 0-19', 'TE Rec Bonus', 'TE 1D Bonus'
                - 'Pass 300+', 'Rush 100+', 'Rec 100+'
                - 'Sack', 'Int', 'Fum Rec', 'Pts Allow 0', etc.
        """
        self.scoring = scoring_settings
        
        # Ensure all expected scoring categories exist with default 0.0
        self._set_default_scoring()
    
    def _set_default_scoring(self):
        """Set default values for any missing scoring categories."""
        default_categories = [
            'Rush Yds', 'Rush Att', 'Rush TD', 'Rush 1D',
            'Rec', 'Rec Yds', 'Rec TD', 'Rec 1D',
            'Pass Yds', 'Pass Comp', 'Pass TD', 'Pass 1D', 'Int Thrown',
            'Fum Lost', 'Ret Yds', 'Ret TD', 'PAT Made', 'FG 0-19',
            'TE Rec Bonus', 'TE 1D Bonus', 'Pass 300+', 'Rush 100+', 'Rec 100+',
            'Sack', 'Int', 'Fum Rec', 'Pts Allow 0', 'Pts Allow 1-6',
            'Pts Allow 7-13', 'Pts Allow 14-20', 'Pts Allow 21-27',
            'Pts Allow 28-34', 'Pts Allow 35+'
        ]
        
        for category in default_categories:
            if category not in self.scoring:
                self.scoring[category] = 0.0
    
    def calculate_points(self, stats_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate fantasy points for all players in the stats DataFrame.
        
        Args:
            stats_df: DataFrame with player statistics. Expected columns include:
                - position: Player position ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')
                - Standard stat columns like rush_yds, rec, pass_td, etc.
                - For DEF: points_allowed, sacks, def_int, etc.
        
        Returns:
            DataFrame with added 'points' column containing calculated fantasy points.
        """
        df = stats_df.copy()
        
        # Separate offensive players and defenses for different scoring logic
        offense_mask = df['position'] != 'DEF'
        defense_mask = df['position'] == 'DEF'
        
        # Calculate offensive points
        if offense_mask.any():
            df.loc[offense_mask, 'points'] = self._calculate_offensive_points(
                df.loc[offense_mask]
            )
        
        # Calculate defensive points  
        if defense_mask.any():
            df.loc[defense_mask, 'points'] = self._calculate_defensive_points(
                df.loc[defense_mask]
            )
        
        return df
    
    def _calculate_offensive_points(self, offense_df: pd.DataFrame) -> pd.Series:
        """Calculate fantasy points for offensive players (QB, RB, WR, TE, K)."""
        # Fill any missing stat columns with 0
        stat_columns = [
            'rush_yds', 'rush_att', 'rush_td', 'rush_first_down',
            'rec', 'rec_yds', 'rec_td', 'rec_first_down',
            'pass_yds', 'pass_cmp', 'pass_td', 'pass_first_down', 'pass_int',
            'fumbles_lost', 'kick_ret_yds', 'punt_ret_yds', 
            'kick_ret_td', 'punt_ret_td', 'xpm', 'fgm'
        ]
        
        for col in stat_columns:
            if col not in offense_df.columns:
                offense_df = offense_df.copy()
                offense_df[col] = 0
        
        # Base offensive scoring
        points = (
            offense_df['rush_yds'] * self.scoring['Rush Yds'] +
            offense_df['rush_att'] * self.scoring['Rush Att'] +
            offense_df['rush_td'] * self.scoring['Rush TD'] +
            offense_df['rush_first_down'] * self.scoring['Rush 1D'] +
            offense_df['rec'] * self.scoring['Rec'] +
            offense_df['rec_yds'] * self.scoring['Rec Yds'] +
            offense_df['rec_td'] * self.scoring['Rec TD'] +
            offense_df['rec_first_down'] * self.scoring['Rec 1D'] +
            offense_df['pass_yds'] * self.scoring['Pass Yds'] +
            offense_df['pass_cmp'] * self.scoring['Pass Comp'] +
            offense_df['pass_td'] * self.scoring['Pass TD'] +
            offense_df['pass_first_down'] * self.scoring['Pass 1D'] +
            offense_df['pass_int'] * self.scoring['Int Thrown'] +
            offense_df['fumbles_lost'] * self.scoring['Fum Lost'] +
            (offense_df['kick_ret_yds'] + offense_df['punt_ret_yds']) * self.scoring['Ret Yds'] +
            (offense_df['kick_ret_td'] + offense_df['punt_ret_td']) * self.scoring['Ret TD'] +
            offense_df['xpm'] * self.scoring['PAT Made'] +
            offense_df['fgm'] * self.scoring['FG 0-19']
        )
        
        # TE position bonuses
        te_mask = offense_df['position'] == 'TE'
        if te_mask.any():
            points.loc[te_mask] += (
                offense_df.loc[te_mask, 'rec'] * self.scoring['TE Rec Bonus'] +
                (offense_df.loc[te_mask, 'rush_first_down'] + 
                 offense_df.loc[te_mask, 'rec_first_down'] +
                 offense_df.loc[te_mask, 'pass_first_down']) * self.scoring['TE 1D Bonus']
            )
        
        # Yardage bonuses
        if 'pass_yds' in offense_df.columns:
            points.loc[offense_df['pass_yds'] >= 300] += self.scoring['Pass 300+']
        if 'rush_yds' in offense_df.columns:
            points.loc[offense_df['rush_yds'] >= 100] += self.scoring['Rush 100+']
        if 'rec_yds' in offense_df.columns:
            points.loc[offense_df['rec_yds'] >= 100] += self.scoring['Rec 100+']
        
        return points
    
    def _calculate_defensive_points(self, defense_df: pd.DataFrame) -> pd.Series:
        """Calculate fantasy points for team defenses."""
        # Fill any missing defensive stat columns with 0
        def_stat_columns = [
            'sacks', 'def_int', 'fumbles_rec', 'def_int_td', 'fumbles_rec_td',
            'kick_ret_td', 'punt_ret_td', 'points_allowed'
        ]
        
        for col in def_stat_columns:
            if col not in defense_df.columns:
                defense_df = defense_df.copy()
                defense_df[col] = 0
        
        # Base defensive scoring
        points = (
            defense_df['sacks'] * self.scoring['Sack'] +
            defense_df['def_int'] * self.scoring['Int'] +
            defense_df['fumbles_rec'] * self.scoring['Fum Rec'] +
            (defense_df['def_int_td'] + defense_df['fumbles_rec_td'] +
             defense_df['kick_ret_td'] + defense_df['punt_ret_td']) * self.scoring['Ret TD']
        )
        
        # Points allowed scoring (if points_allowed column exists)
        if 'points_allowed' in defense_df.columns:
            points.loc[defense_df['points_allowed'] == 0] += self.scoring['Pts Allow 0']
            points.loc[(defense_df['points_allowed'] >= 1) & 
                      (defense_df['points_allowed'] <= 6)] += self.scoring['Pts Allow 1-6']
            points.loc[(defense_df['points_allowed'] >= 7) & 
                      (defense_df['points_allowed'] <= 13)] += self.scoring['Pts Allow 7-13']
            points.loc[(defense_df['points_allowed'] >= 14) & 
                      (defense_df['points_allowed'] <= 20)] += self.scoring['Pts Allow 14-20']
            points.loc[(defense_df['points_allowed'] >= 21) & 
                      (defense_df['points_allowed'] <= 27)] += self.scoring['Pts Allow 21-27']
            points.loc[(defense_df['points_allowed'] >= 28) & 
                      (defense_df['points_allowed'] <= 34)] += self.scoring['Pts Allow 28-34']
            points.loc[defense_df['points_allowed'] >= 35] += self.scoring['Pts Allow 35+']
        
        return points


# Convenience function for quick scoring
def calculate_fantasy_points(stats_df: pd.DataFrame, 
                           scoring_settings: Dict[str, float]) -> pd.DataFrame:
    """
    Convenience function to calculate fantasy points in one call.
    
    Args:
        stats_df: DataFrame with player statistics
        scoring_settings: Dictionary of scoring rules
        
    Returns:
        DataFrame with added 'points' column
    """
    scorer = FantasyScorer(scoring_settings)
    return scorer.calculate_points(stats_df)
