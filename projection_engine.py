"""
Fantasy football projection engine.

This module provides sophisticated player projection algorithms using
weighted historical performance with opponent, depth chart, and time factors.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple


class ProjectionEngine:
    """
    Calculates player fantasy point projections using weighted historical performance.
    
    This engine implements sophisticated weighting factors for:
    - Opponent strength (ELO-based)
    - Depth chart position 
    - Time decay of historical games
    - Position-specific priors
    """
    
    def __init__(self, weighting_factors: pd.DataFrame, reference_games: Dict[str, int]):
        """
        Initialize projection engine with position-specific weighting factors.
        
        Args:
            weighting_factors: DataFrame with columns ['position', 'basal', 'opp_elo_weight', 
                              'string_weight', 'time_scale'] defining how to weight factors
                              for each position
            reference_games: Dict mapping position -> number of games to use as prior
                           e.g. {'QB': 10, 'RB': 8, 'WR': 6, 'TE': 8, 'K': 5, 'DEF': 10}
        """
        self.weighting_factors = weighting_factors
        self.reference_games = reference_games
        
        # Validate required columns
        required_cols = ['position', 'basal', 'opp_elo_weight', 'string_weight', 'time_scale']
        if not all(col in weighting_factors.columns for col in required_cols):
            raise ValueError(f"weighting_factors must have columns: {required_cols}")
    
    def calculate_projections(self, 
                            stats_df: pd.DataFrame,
                            earliest_weeks: Dict[str, int],
                            current_week: int,
                            nfl_schedule: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Calculate player projections using weighted historical performance.
        
        Args:
            stats_df: DataFrame with historical game stats including:
                     - player_id_sr: Player identifier
                     - position: Player position
                     - points: Fantasy points per game
                     - season, week: Game identifiers
                     - elo_diff: Team ELO differential for game context
                     - string: Depth chart position (1.0 = starter, 2.0 = backup, etc.)
            earliest_weeks: Dict mapping position -> earliest week to consider (YYYYWW format)
            current_week: Current week in YYYYWW format
            nfl_schedule: Optional DataFrame with ELO data for game context
            
        Returns:
            DataFrame with player projections including:
            - points_rate: Expected fantasy points per game
            - points_stdev: Standard deviation of fantasy points
            - num_games: Number of games used in calculation
        """
        # Filter stats to relevant time periods per position
        filtered_stats = self._filter_stats_by_position(stats_df, earliest_weeks, current_week)
        
        # Merge weighting factors
        filtered_stats = pd.merge(filtered_stats, self.weighting_factors, 
                                on='position', how='left')
        
        # Calculate game context factors
        filtered_stats = self._calculate_game_factors(filtered_stats)
        
        # Calculate relative points (normalized by game factors)
        filtered_stats['rel_points'] = filtered_stats['points'] / filtered_stats['game_factor']
        
        # Calculate position averages for priors
        position_priors = self._calculate_position_priors(filtered_stats)
        
        # Limit games per player per position
        filtered_stats = self._limit_games_per_player(filtered_stats)
        
        # Calculate time-weighted projections
        player_projections = self._calculate_player_projections(filtered_stats, current_week)
        
        # Apply Bayesian updating with position priors
        final_projections = self._apply_bayesian_updating(player_projections, position_priors)

        # Append position priors as average players
        final_projections = pd.concat([final_projections, position_priors], ignore_index=True, sort=False)
        
        return final_projections
    
    def _filter_stats_by_position(self, stats_df: pd.DataFrame, 
                                earliest_weeks: Dict[str, int],
                                current_week: int) -> pd.DataFrame:
        """Filter stats to relevant time periods for each position."""
        filtered_dfs = []
        
        for position in earliest_weeks:
            pos_mask = stats_df['position'] == position
            week_mask = (
                (stats_df['season'] * 100 + stats_df['week'] <= current_week - 1) &
                (stats_df['season'] * 100 + stats_df['week'] >= earliest_weeks[position])
            )
            
            pos_stats = stats_df[pos_mask & week_mask].copy()
            filtered_dfs.append(pos_stats)
        
        return pd.concat(filtered_dfs, ignore_index=True) if filtered_dfs else pd.DataFrame()
    
    def _calculate_game_factors(self, stats_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate game context factors based on opponent, depth chart, etc."""
        df = stats_df.copy()
        
        # Ensure required columns exist
        if 'elo_diff' not in df.columns:
            df['elo_diff'] = 0.0
        if 'string' not in df.columns:
            df['string'] = 1.0
        
        # Calculate game factor: basal + opponent_strength + depth_chart_factor
        df['game_factor'] = (
            df['basal'] + 
            df['opp_elo_weight'] * df['elo_diff'] +
            df['string_weight'] * (1 - df['string'])
        )
        
        # Set minimum game factor to prevent division by very small numbers
        df.loc[df['game_factor'] < 0.25, 'game_factor'] = 0.25
        
        return df
    
    def _calculate_position_priors(self, stats_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate position-level averages to use as priors."""
        position_priors = stats_df.groupby('position').agg({
            'rel_points': ['mean', 'std']
        }).reset_index()
        
        # Flatten column names
        position_priors.columns = ['position', 'points_rate', 'points_stdev']
        position_priors['points_stdev'] = position_priors['points_stdev'].fillna(0.0)
        
        # Create average player entries for each position
        position_priors['player_id_sr'] = 'avg_' + position_priors['position']
        
        return position_priors
    
    def _limit_games_per_player(self, stats_df: pd.DataFrame) -> pd.DataFrame:
        """Limit number of games per player based on reference_games settings."""
        limited_dfs = []
        
        for position in self.reference_games:
            pos_stats = stats_df[stats_df['position'] == position].copy()
            if pos_stats.empty:
                continue
                
            # Take most recent games up to reference limit
            limited_pos = pos_stats.groupby('player_id_sr').head(
                self.reference_games[position]
            )
            limited_dfs.append(limited_pos)
        
        return pd.concat(limited_dfs, ignore_index=True) if limited_dfs else pd.DataFrame()
    
    def _calculate_player_projections(self, stats_df: pd.DataFrame, 
                                    current_week: int) -> pd.DataFrame:
        """Calculate time-weighted projections for each player."""
        df = stats_df.copy()
        
        # Calculate weeks ago
        df['weeks_ago'] = (
            17 * (current_week // 100 - df['season']) + 
            current_week % 100 - df['week']
        )
        
        # Calculate time decay factor
        df['time_factor'] = 1 - df['weeks_ago'] * df['time_scale']
        
        # Filter out games that are too old (time_factor <= 0)
        df = df[df['time_factor'] > 0].copy()
        
        if df.empty:
            return pd.DataFrame()
        
        # Calculate weighted projections per player
        player_stats = df.groupby(['player_id_sr', 'position']).apply(
            self._calculate_weighted_stats, include_groups=False
        ).reset_index()
        
        return player_stats
    
    def _calculate_weighted_stats(self, player_df: pd.DataFrame) -> pd.Series:
        """Calculate weighted mean and std for a single player."""
        if player_df.empty:
            return pd.Series({
                'points_rate': 0.0,
                'points_stdev': 0.0,
                'num_games': 0
            })
        
        # Normalize time factors to sum to num_games
        time_factor_sum = player_df['time_factor'].sum()
        num_games = len(player_df)
        normalized_time_factors = (
            player_df['time_factor'] * num_games / time_factor_sum
        )
        
        # Calculate weighted statistics
        weighted_points = player_df['rel_points'] * normalized_time_factors
        points_rate = weighted_points.mean()
        points_stdev = weighted_points.std() if len(weighted_points) > 1 else 0.0
        
        return pd.Series({
            'points_rate': points_rate,
            'points_stdev': points_stdev if not pd.isna(points_stdev) else 0.0,
            'num_games': num_games
        })
    
    def _apply_bayesian_updating(self, player_projections: pd.DataFrame,
                               position_priors: pd.DataFrame) -> pd.DataFrame:
        """Apply Bayesian updating using position priors for players with limited data."""
        # Merge position priors
        projections = pd.merge(
            player_projections,
            position_priors[['position', 'points_rate', 'points_stdev']].rename(
                columns={'points_rate': 'pos_avg', 'points_stdev': 'pos_stdev'}
            ),
            on='position',
            how='left'
        )
        
        # Apply Bayesian updating for players with insufficient data
        for position in self.reference_games:
            pos_mask = projections['position'] == position
            ref_games = self.reference_games[position]
            insufficient_data = projections['num_games'] < ref_games
            
            update_mask = pos_mask & insufficient_data
            
            if update_mask.any():
                # Bayesian update: blend player data with position prior
                player_games = projections.loc[update_mask, 'num_games']
                prior_games = ref_games - player_games
                
                # Update variance (more complex calculation)
                projections.loc[update_mask, 'points_squared'] = (
                    player_games * (
                        projections.loc[update_mask, 'points_stdev'] ** 2 +
                        projections.loc[update_mask, 'points_rate'] ** 2
                    ) +
                    prior_games * (
                        projections.loc[update_mask, 'pos_stdev'] ** 2 +
                        projections.loc[update_mask, 'pos_avg'] ** 2
                    )
                ) / ref_games
                
                # Update mean
                projections.loc[update_mask, 'points_rate'] = (
                    player_games * projections.loc[update_mask, 'points_rate'] +
                    prior_games * projections.loc[update_mask, 'pos_avg']
                ) / ref_games
                
                # Update standard deviation
                variance = (
                    projections.loc[update_mask, 'points_squared'] -
                    projections.loc[update_mask, 'points_rate'] ** 2
                )
                projections.loc[update_mask, 'points_stdev'] = np.sqrt(variance.clip(lower=0))
        
        # Clean up temporary columns
        if 'points_squared' in projections.columns:
            projections = projections.drop(['points_squared', 'pos_avg', 'pos_stdev'], axis=1)
        
        return projections[['player_id_sr', 'position', 'points_rate', 'points_stdev', 'num_games']]


# Convenience function for quick projections
def calculate_projections(stats_df: pd.DataFrame,
                        weighting_factors: pd.DataFrame,
                        reference_games: Dict[str, int],
                        earliest_weeks: Dict[str, int],
                        current_week: int) -> pd.DataFrame:
    """
    Convenience function to calculate projections in one call.
    
    Args:
        stats_df: Historical game statistics
        weighting_factors: Position-specific weighting parameters
        reference_games: Number of games to use as prior per position
        earliest_weeks: Earliest week to consider per position (YYYYWW)
        current_week: Current week (YYYYWW)
        
    Returns:
        DataFrame with player projections
    """
    engine = ProjectionEngine(weighting_factors, reference_games)
    return engine.calculate_projections(stats_df, earliest_weeks, current_week)
