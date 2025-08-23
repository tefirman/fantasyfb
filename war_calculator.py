"""
WAR (Wins Above Replacement) calculation for fantasy football players.

This module calculates how many more wins a player would contribute
compared to an average replacement player at their position.
"""

import pandas as pd
import numpy as np


class WARCalculator:
    """
    Calculates Wins Above Replacement (WAR) for fantasy football players.
    
    WAR represents how many more wins per season a player would contribute
    compared to an average replacement player at their position.
    """
    
    def __init__(self, num_sims: int = 10000):
        """
        Initialize WAR calculator.
        
        Args:
            num_sims: Number of Monte Carlo simulations to run
        """
        self.num_sims = num_sims
    
    def calculate_war(self, players_df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate WAR for all players based on historical performance.
        
        Args:
            players_df: DataFrame with player information including points_rate, points_stdev
            stats_df: DataFrame with historical game statistics
            
        Returns:
            DataFrame with WAR values added to player data
        """
        # Create position histograms from historical data
        pos_hists = self._create_position_histograms(stats_df)
        
        # Simulate average team performance
        sim_scores = self._simulate_average_teams(pos_hists)
        
        # Create player simulation data
        player_sims = self._simulate_player_performance(players_df, sim_scores.shape[0])
        
        # Merge simulations
        sim_scores = pd.merge(
            left=sim_scores, right=player_sims, left_index=True, right_index=True
        )
        
        # Calculate WAR for each player
        players_with_war = players_df.copy()
        for player in player_sims.columns:
            if pd.isnull(player):
                print("Null player name for some reason... Skipping...")
                continue
            
            war_value = self._calculate_individual_war(sim_scores, player, players_df)
            players_with_war.loc[players_with_war.name == player, "WAR"] = war_value
        
        return players_with_war
    
    def _create_position_histograms(self, stats_df: pd.DataFrame) -> dict:
        """Create probability histograms for each position based on historical points."""
        pos_hists = {"points": np.arange(-10, 50.1, 0.1)}
        
        for pos in stats_df.position.unique():
            pos_hists[pos] = np.histogram(
                stats_df.loc[stats_df.position == pos, "points"],
                bins=pos_hists["points"],
            )[0]
            pos_hists[pos] = pos_hists[pos] / sum(pos_hists[pos])
        
        # Create FLEX histogram (RB + WR + TE)
        pos_hists["FLEX"] = np.histogram(
            stats_df.loc[stats_df.position.isin(["RB", "WR", "TE"]), "points"],
            bins=pos_hists["points"],
        )[0]
        pos_hists["FLEX"] = pos_hists["FLEX"] / sum(pos_hists["FLEX"])
        
        return pos_hists
    
    def _simulate_average_teams(self, pos_hists: dict) -> pd.DataFrame:
        """Simulate team performance using average players at each position."""
        return pd.DataFrame({
            "QB": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["QB"], size=self.num_sims
            ),
            "RB1": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["RB"], size=self.num_sims
            ),
            "RB2": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["RB"], size=self.num_sims
            ),
            "WR1": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["WR"], size=self.num_sims
            ),
            "WR2": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["WR"], size=self.num_sims
            ),
            "TE": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["TE"], size=self.num_sims
            ),
            "FLEX": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["FLEX"], size=self.num_sims
            ),
            "K": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["K"], size=self.num_sims
            ),
            "DEF": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["DEF"], size=self.num_sims
            ),
        })
    
    def _simulate_player_performance(self, players_df: pd.DataFrame, num_sims: int) -> pd.DataFrame:
        """Generate simulated performance for all players."""
        return pd.DataFrame({
            players_df.loc[ind, "name"]: np.round(
                np.random.normal(
                    loc=players_df.loc[ind, "points_rate"],
                    scale=players_df.loc[ind, "points_stdev"],
                    size=num_sims,
                )
            )
            for ind in range(players_df.shape[0])
        })
    
    def _calculate_individual_war(self, sim_scores: pd.DataFrame, player_name: str, 
                                 players_df: pd.DataFrame) -> float:
        """Calculate WAR for a single player."""
        # Get player position
        pos = players_df.loc[players_df.name == player_name, "position"].values[0]
        
        # Determine roster position for comparison
        if pos in ["RB", "WR"]:
            comparison_pos = pos + "1"
        else:
            comparison_pos = pos
        
        # Create alternative lineup with this player
        baseline_cols = sim_scores.columns[:9].tolist()  # Standard positions
        baseline_cols.remove(comparison_pos)
        baseline_cols.append(player_name)
        
        # Calculate total scores
        sim_scores["Total"] = sim_scores.iloc[:, :9].sum(axis=1)
        sim_scores["Alt_Total"] = sim_scores[baseline_cols].sum(axis=1)
        
        # Calculate win rate difference
        half_sims = sim_scores.shape[0] // 2
        wins_above_replacement = sum(
            sim_scores.loc[:half_sims - 1, "Alt_Total"].values >
            sim_scores.loc[half_sims:, "Total"].values
        ) / half_sims
        
        # Convert to WAR (14 games per season, centered at 0.5)
        war_value = (wins_above_replacement - 0.5) * 14
        
        # Clean up temporary columns
        del sim_scores["Alt_Total"]
        
        return war_value
