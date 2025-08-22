"""
Fantasy football season simulation engine with debug prints.

This module provides Monte Carlo simulation of fantasy football seasons,
including regular season standings, playoff brackets, and payout calculations.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple


class SeasonSimulator:
    """
    Simulates fantasy football seasons using Monte Carlo methods.
    
    Handles regular season play, playoff brackets, and outcome probabilities
    for any fantasy football league structure.
    """
    
    def __init__(self, league_settings: Dict):
        """
        Initialize simulator with league-specific settings.
        
        Args:
            league_settings: Dictionary containing:
                - playoff_start_week: Week when playoffs begin
                - num_playoff_teams: Number of teams making playoffs
                - uses_playoff_reseeding: Whether to reseed after each round
                - num_teams: Total teams in league
        """
        self.settings = league_settings
        
        # Validate required settings
        required_keys = ['playoff_start_week', 'num_playoff_teams']
        if not all(key in league_settings for key in required_keys):
            raise ValueError(f"league_settings must contain: {required_keys}")
    
    def simulate_season(self, 
                       player_projections: pd.DataFrame,
                       schedule_df: pd.DataFrame,
                       num_sims: int = 10000,
                       include_playoffs: bool = True,
                       payouts: List[float] = [800, 300, 100],
                       fixed_winner: Optional[List] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Simulate a complete fantasy season with playoffs.
        
        Args:
            player_projections: DataFrame with columns [fantasy_team, week, points_avg, points_stdev]
            schedule_df: DataFrame with columns [week, team_1, team_2, score_1, score_2]
            num_sims: Number of Monte Carlo simulations
            include_playoffs: Whether to simulate playoffs
            payouts: Prize amounts for [1st, 2nd, 3rd, ...]
            fixed_winner: Optional [week, team_name] to force a specific outcome
            
        Returns:
            Tuple of (schedule_results, standings_results) DataFrames
        """
        # Merge projections with schedule
        schedule_with_projections = self._merge_schedule_projections(schedule_df, player_projections)
        
        # Apply fixed winner if specified
        if fixed_winner:
            schedule_with_projections = self._apply_fixed_winner(schedule_with_projections, fixed_winner)
        
        # Run Monte Carlo simulations
        schedule_sims = self._simulate_all_matchups(schedule_with_projections, num_sims)
        
        # Calculate regular season standings
        standings_sims = self._calculate_regular_season_standings(schedule_sims)
        
        # Simulate playoffs if requested
        final_results = None
        if include_playoffs:
            final_results = self._simulate_playoffs(
                standings_sims, schedule_with_projections, player_projections, payouts
            )
        
        # Aggregate results
        schedule_results = self._aggregate_schedule_results(schedule_sims)
        standings_results = self._aggregate_standings_results(standings_sims, final_results, payouts)
        
        return schedule_results, standings_results
    
    def _simulate_playoffs(self, standings_df: pd.DataFrame,
                          schedule_df: pd.DataFrame, 
                          projections_df: pd.DataFrame,
                          payouts: List[float]) -> Dict[str, pd.DataFrame]:
        """Simulate playoff brackets and determine final rankings."""
        # Get playoff teams for each simulation (0-based indexing: 0-5)
        playoff_teams = standings_df[standings_df['playoffs'] == 1].copy()
        playoff_teams['seed'] = playoff_teams.index % self.settings['num_playoff_teams']
        
        # Get consolation teams (0-based indexing: 6-11 for Many Mile)
        consolation_teams = standings_df[standings_df['playoffs'] == 0].copy()
        total_teams = self.settings.get('num_teams', 12)
        consolation_teams['seed'] = consolation_teams.index % total_teams
        
        # Check first simulation to see actual team distribution
        first_sim = standings_df['num_sim'].iloc[0]
        first_sim_playoff = playoff_teams[playoff_teams['num_sim'] == first_sim]
        first_sim_consolation = consolation_teams[consolation_teams['num_sim'] == first_sim]
        
        # Simulate main playoffs
        if self.settings['num_playoff_teams'] == 6:
            # Wild card round (week 1)
            wild_card_week = self.settings['playoff_start_week']
            semifinalists = self._simulate_6_team_wildcard(
                playoff_teams, projections_df, wild_card_week
            )
            
            # Semifinals (week 2) 
            semifinal_week = self.settings['playoff_start_week'] + 1
            finalists = self._simulate_6_team_semifinals(
                semifinalists, projections_df, semifinal_week
            )
            
            # Championship (week 3)
            championship_week = self.settings['playoff_start_week'] + 2
            winners = self._simulate_championship(finalists, projections_df, championship_week)
            
            # Get runners-up (finalists who didn't win)
            runners_up = finalists[~finalists.index.isin(winners.index)]
            
        else:
            # 4-team playoff: Semifinals -> Championship
            semifinal_week = self.settings['playoff_start_week']
            finalists = self._simulate_4_team_semifinals(
                playoff_teams, projections_df, semifinal_week
            )
            
            championship_week = self.settings['playoff_start_week'] + 1
            winners = self._simulate_championship(finalists, projections_df, championship_week)
            
            runners_up = finalists[~finalists.index.isin(winners.index)]
        
        # Simulate Many Mile consolation bracket (for non-playoff teams)
        many_mile_losers = self._simulate_many_mile_bracket(
            consolation_teams, projections_df
        )
        
        # Calculate probabilities
        total_sims = len(standings_df['num_sim'].unique())
        many_mile_probs = {}
        if len(many_mile_losers) > 0:
            many_mile_probs = many_mile_losers.groupby('team').size() / total_sims
        
        results = {
            'winners': winners.groupby('team').size() / total_sims,
            'runners_up': runners_up.groupby('team').size() / total_sims,
            'many_mile_losers': many_mile_probs
        }
        
        return results
    
    def _simulate_many_mile_bracket(self, consolation_teams: pd.DataFrame,
                                   projections_df: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate the Many Mile consolation bracket where you advance by LOSING.
        0-based seeds 6-11 (fantasy seeds 7-12) compete to avoid being the ultimate loser.
        """
        many_mile_losers = []
        total_sims = len(consolation_teams['num_sim'].unique())
        
        for sim_idx, sim_num in enumerate(consolation_teams['num_sim'].unique()):
            sim_teams = consolation_teams[consolation_teams['num_sim'] == sim_num].copy()
            
            # Only include 0-based seeds 6-11 (fantasy seeds 7-12, the 6 non-playoff teams)
            sim_teams = sim_teams[sim_teams['seed'].isin([6, 7, 8, 9, 10, 11])]
            sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)
            
            try:
                # Week 1: First round of Many Mile
                week1 = self.settings['playoff_start_week']
                week1_projections = projections_df[projections_df['week'] == week1]
                
                # Byes advance automatically (worst teams get advantage)
                byes = sim_teams[sim_teams['seed'].isin([10, 11])]
                
                # Matchups: 6v9, 7v8 - losers advance
                matchup1 = sim_teams[sim_teams['seed'].isin([6, 9])]
                matchup2 = sim_teams[sim_teams['seed'].isin([7, 8])]
                loser1 = self._simulate_many_mile_matchup(matchup1, week1_projections)
                loser2 = self._simulate_many_mile_matchup(matchup2, week1_projections)
                
                # Week 2: Semifinals
                week2 = self.settings['playoff_start_week'] + 1
                week2_projections = projections_df[projections_df['week'] == week2]
                bye1 = byes[byes['seed'] == 10].iloc[0].to_dict()
                bye2 = byes[byes['seed'] == 11].iloc[0].to_dict()
                
                semi1_teams = pd.DataFrame([bye1, loser1])
                semi2_teams = pd.DataFrame([bye2, loser2])
                
                semi_loser1 = self._simulate_many_mile_matchup(semi1_teams, week2_projections)
                semi_loser2 = self._simulate_many_mile_matchup(semi2_teams, week2_projections)
                
                # Week 3: Championship
                week3 = self.settings['playoff_start_week'] + 2
                week3_projections = projections_df[projections_df['week'] == week3]
                
                final_teams = pd.DataFrame([semi_loser1, semi_loser2])
                ultimate_loser = self._simulate_many_mile_matchup(final_teams, week3_projections)
                
                many_mile_losers.append(ultimate_loser)
                
            except Exception as e:
                continue
        
        return pd.DataFrame(many_mile_losers)
    
    def _simulate_many_mile_matchup(self, teams_df: pd.DataFrame,
                                   week_projections: pd.DataFrame) -> Dict:
        """
        Simulate a Many Mile matchup where the LOSER advances.
        Returns the team that scored LOWER (the loser who advances).
        """
        teams = teams_df.copy()
        
        # Drop any existing projection columns to avoid conflicts
        projection_cols = ['points_avg', 'points_stdev', 'fantasy_team']
        for col in projection_cols:
            if col in teams.columns:
                teams = teams.drop(columns=[col])
        
        # Merge with projections for this week
        teams = pd.merge(teams, week_projections, 
                        left_on='team', right_on='fantasy_team', how='left')
        
        # Use default projections if no data available
        teams['points_avg'] = teams['points_avg'].fillna(100.0)
        teams['points_stdev'] = teams['points_stdev'].fillna(10.0)
        
        # Generate random scores
        teams['sim_score'] = (
            np.random.normal(0, 1, len(teams)) * teams['points_stdev'] + teams['points_avg']
        )
        
        # Return LOSER (lowest score) - they advance in Many Mile
        loser_idx = teams['sim_score'].idxmin()
        return teams.loc[loser_idx].to_dict()
    
    # ... (rest of the methods remain the same as in the original)
    
    def _merge_schedule_projections(self, schedule_df: pd.DataFrame, 
                                  projections_df: pd.DataFrame) -> pd.DataFrame:
        """Merge schedule with team projections for each week."""
        schedule = schedule_df.copy()
        
        # Merge team 1 projections
        schedule = pd.merge(
            left=schedule,
            right=projections_df.rename(columns={
                'fantasy_team': 'team_1',
                'points_avg': 'points_avg_1',
                'points_stdev': 'points_stdev_1'
            }),
            how='left',
            on=['week', 'team_1']
        )
        
        # Merge team 2 projections  
        schedule = pd.merge(
            left=schedule,
            right=projections_df.rename(columns={
                'fantasy_team': 'team_2', 
                'points_avg': 'points_avg_2',
                'points_stdev': 'points_stdev_2'
            }),
            how='left',
            on=['week', 'team_2']
        )
        
        # Fill missing projections with 0
        proj_cols = ['points_avg_1', 'points_avg_2', 'points_stdev_1', 'points_stdev_2']
        for col in proj_cols:
            schedule[col] = schedule[col].fillna(0.0)
        
        # Add existing scores to projections (for completed weeks)
        schedule['points_avg_1'] += schedule['score_1'].astype(float)
        schedule['points_avg_2'] += schedule['score_2'].astype(float)
        
        return schedule
    
    def _apply_fixed_winner(self, schedule_df: pd.DataFrame, 
                           fixed_winner: List) -> pd.DataFrame:
        """Apply a fixed winner for a specific week/team."""
        week, team_name = fixed_winner
        schedule = schedule_df.copy()
        
        # Find the matchup
        matchup_mask = (
            (schedule['week'] == week) & 
            ((schedule['team_1'] == team_name) | (schedule['team_2'] == team_name))
        )
        
        if matchup_mask.any():
            # Determine which team is the fixed winner
            if (schedule.loc[matchup_mask, 'team_1'] == team_name).any():
                winner_col, loser_col = 'points_avg_1', 'points_avg_2'
                winner_std, loser_std = 'points_stdev_1', 'points_stdev_2'
            else:
                winner_col, loser_col = 'points_avg_2', 'points_avg_1'  
                winner_std, loser_std = 'points_stdev_2', 'points_stdev_1'
            
            # Set fixed outcome (winner gets 100.1, loser gets 100.0, no variance)
            schedule.loc[matchup_mask, winner_col] = 100.1
            schedule.loc[matchup_mask, loser_col] = 100.0
            schedule.loc[matchup_mask, winner_std] = 0.0
            schedule.loc[matchup_mask, loser_std] = 0.0
        
        return schedule
    
    def _simulate_all_matchups(self, schedule_df: pd.DataFrame, 
                              num_sims: int) -> pd.DataFrame:
        """Run Monte Carlo simulation for all matchups."""
        # Replicate schedule for all simulations
        schedule_sims = pd.concat([schedule_df] * num_sims, ignore_index=True)
        schedule_sims['num_sim'] = schedule_sims.index // len(schedule_df)
        
        # Generate random scores
        schedule_sims['sim_1'] = (
            np.random.normal(loc=0, scale=1, size=len(schedule_sims)) * 
            schedule_sims['points_stdev_1'] + schedule_sims['points_avg_1']
        ).astype(float)
        
        schedule_sims['sim_2'] = (
            np.random.normal(loc=0, scale=1, size=len(schedule_sims)) * 
            schedule_sims['points_stdev_2'] + schedule_sims['points_avg_2']
        ).astype(float)
        
        # Determine winners
        schedule_sims['win_1'] = (schedule_sims['sim_1'] > schedule_sims['sim_2']).astype(int)
        schedule_sims['win_2'] = 1 - schedule_sims['win_1']
        
        return schedule_sims
    
    def _calculate_regular_season_standings(self, schedule_sims: pd.DataFrame) -> pd.DataFrame:
        """Calculate regular season win/loss records from simulated games."""
        # Convert to team-level records
        team1_records = schedule_sims[['num_sim', 'week', 'team_1', 'sim_1', 'win_1']].rename(
            columns={'team_1': 'team', 'sim_1': 'points', 'win_1': 'wins'}
        )
        team2_records = schedule_sims[['num_sim', 'week', 'team_2', 'sim_2', 'win_2']].rename(
            columns={'team_2': 'team', 'sim_2': 'points', 'win_2': 'wins'}
        )
        
        standings = pd.concat([team1_records, team2_records], ignore_index=True)
        
        # Filter to regular season games only
        standings = standings[standings['week'] < self.settings['playoff_start_week']]
        
        # Calculate season totals
        standings = (
            standings.groupby(['num_sim', 'team'])
            .agg({'wins': 'sum', 'points': 'sum'})
            .sort_values(['num_sim', 'wins', 'points'], ascending=[True, False, False])
            .reset_index()
        )
        
        # Determine playoff teams
        standings['playoffs'] = 0
        standings.loc[
            standings.index % self.settings.get('num_teams', 12) < self.settings['num_playoff_teams'],
            'playoffs'
        ] = 1
        
        # Determine playoff byes (if applicable)
        standings['playoff_bye'] = 0
        if self.settings['num_playoff_teams'] == 6:
            standings.loc[
                standings.index % self.settings.get('num_teams', 12) < 2,
                'playoff_bye'
            ] = 1
        
        return standings
    
    def _simulate_6_team_wildcard(self, playoff_teams: pd.DataFrame, 
                                 projections_df: pd.DataFrame, week: int) -> pd.DataFrame:
        """Simulate 6-team playoff wild card round (0-based seeds 2v5, 3v4, 0&1 get byes)."""
        winners = []
        
        for sim_num in playoff_teams['num_sim'].unique():
            sim_teams = playoff_teams[playoff_teams['num_sim'] == sim_num].copy()
            sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)
            
            # Get projections for this week
            week_projections = projections_df[projections_df['week'] == week]
            
            # 0-based seeds 0 and 1 get byes
            if len(sim_teams) >= 2:
                byes = sim_teams[sim_teams['seed'].isin([0, 1])]
                winners.extend(byes.to_dict('records'))
            
            # Wild card games: 0-based 2v5, 3v4
            if len(sim_teams) >= 6:
                matchup1 = sim_teams[sim_teams['seed'].isin([2, 5])]
                matchup2 = sim_teams[sim_teams['seed'].isin([3, 4])]
                
                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)
                
                winners.extend([winner1, winner2])
        
        return pd.DataFrame(winners)
    
    def _simulate_6_team_semifinals(self, teams_df: pd.DataFrame,
                                   projections_df: pd.DataFrame, week: int) -> pd.DataFrame:
        """Simulate 6-team playoff semifinals."""
        winners = []
        
        for sim_num in teams_df['num_sim'].unique():
            sim_teams = teams_df[teams_df['num_sim'] == sim_num].copy()
            
            # Reseed if configured
            if self.settings.get('uses_playoff_reseeding', False):
                sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)
            
            week_projections = projections_df[projections_df['week'] == week]
            
            # Create semifinals matchups (assuming 4 teams: 2 bye teams + 2 wild card winners)
            if len(sim_teams) >= 4:
                sim_teams = sim_teams.reset_index(drop=True)
                matchup1 = sim_teams.iloc[[0, 3]]  # Best vs worst remaining
                matchup2 = sim_teams.iloc[[1, 2]]  # Second vs third remaining
                
                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)
                
                winners.extend([winner1, winner2])
        
        return pd.DataFrame(winners)
    
    def _simulate_4_team_semifinals(self, playoff_teams: pd.DataFrame,
                                   projections_df: pd.DataFrame, week: int) -> pd.DataFrame:
        """Simulate 4-team playoff semifinals."""
        winners = []
        
        for sim_num in playoff_teams['num_sim'].unique():
            sim_teams = playoff_teams[playoff_teams['num_sim'] == sim_num].copy()
            sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)
            
            week_projections = projections_df[projections_df['week'] == week]
            
            # Semifinals: 1v4, 2v3
            if len(sim_teams) >= 4:
                matchup1 = sim_teams.iloc[[0, 3]]
                matchup2 = sim_teams.iloc[[1, 2]]
                
                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)
                
                winners.extend([winner1, winner2])
        
        return pd.DataFrame(winners)
    
    def _simulate_championship(self, finalists: pd.DataFrame,
                              projections_df: pd.DataFrame, week: int) -> pd.DataFrame:
        """Simulate championship round."""
        winners = []
        
        for sim_num in finalists['num_sim'].unique():
            sim_teams = finalists[finalists['num_sim'] == sim_num]
            
            if len(sim_teams) >= 2:
                week_projections = projections_df[projections_df['week'] == week]
                winner = self._simulate_matchup_with_projections(sim_teams, week_projections)
                winners.append(winner)
        
        return pd.DataFrame(winners)
    
    def _simulate_matchup_with_projections(self, teams_df: pd.DataFrame, 
                                         week_projections: pd.DataFrame) -> Dict:
        """Simulate a matchup between teams using week projections."""
        teams = teams_df.copy()
        
        # Drop any existing projection columns to avoid conflicts
        projection_cols = ['points_avg', 'points_stdev', 'fantasy_team']
        for col in projection_cols:
            if col in teams.columns:
                teams = teams.drop(columns=[col])
        
        # Merge with projections for this week
        teams = pd.merge(teams, week_projections, 
                        left_on='team', right_on='fantasy_team', how='left')
        
        # Use default projections if no data available
        teams['points_avg'] = teams['points_avg'].fillna(100.0)
        teams['points_stdev'] = teams['points_stdev'].fillna(10.0)
        
        # Generate random scores
        teams['sim_score'] = (
            np.random.normal(0, 1, len(teams)) * teams['points_stdev'] + teams['points_avg']
        )
        
        # Return winner (highest score)
        winner_idx = teams['sim_score'].idxmax()
        return teams.loc[winner_idx].to_dict()
    
    def _aggregate_schedule_results(self, schedule_sims: pd.DataFrame) -> pd.DataFrame:
        """Aggregate simulated schedule results."""
        return schedule_sims.groupby(['week', 'team_1', 'team_2']).agg({
            'points_avg_1': 'mean',
            'points_stdev_1': 'mean', 
            'points_avg_2': 'mean',
            'points_stdev_2': 'mean',
            'sim_1': 'mean',
            'sim_2': 'mean',
            'win_1': 'mean',
            'win_2': 'mean'
        }).round(3).reset_index()
    
    def _aggregate_standings_results(self, standings_sims: pd.DataFrame,
                                   playoff_results: Optional[Dict],
                                   payouts: List[float]) -> pd.DataFrame:
        """Aggregate simulated standings results."""
        # Calculate basic stats
        standings = standings_sims.groupby('team').agg({
            'wins': ['mean', 'std'],
            'points': ['mean', 'std'],
            'playoffs': 'mean',
            'playoff_bye': 'mean'
        }).round(3).reset_index()
        
        # Flatten column names
        standings.columns = [
            'team', 'wins_avg', 'wins_stdev', 'points_avg', 'points_stdev',
            'playoffs', 'playoff_bye'
        ]
        
        # Always add playoff result columns (even if playoffs weren't simulated)
        if playoff_results:
            standings['winner'] = standings['team'].map(playoff_results.get('winners', {})).fillna(0.0)
            standings['runner_up'] = standings['team'].map(playoff_results.get('runners_up', {})).fillna(0.0)
            standings['third'] = 0.0  # Would need third place game simulation
            
            # Convert many_mile_losers to dict if it's a pandas Series
            many_mile_dict = playoff_results.get('many_mile_losers', {})
            if hasattr(many_mile_dict, 'to_dict'):
                many_mile_dict = many_mile_dict.to_dict()
            standings['many_mile'] = standings['team'].map(many_mile_dict).fillna(0.0)
            
            # Calculate earnings
            earnings = (
                standings['winner'] * payouts[0] +
                standings['runner_up'] * payouts[1] +
                standings['third'] * payouts[2] if len(payouts) > 2 else 0
            )
            standings['earnings'] = earnings.round(2)
        else:
            # Add empty playoff columns when playoffs weren't simulated
            standings['winner'] = 0.0
            standings['runner_up'] = 0.0
            standings['third'] = 0.0
            standings['many_mile'] = 0.0
            standings['earnings'] = 0.0
        
        # Sort by championship probability (or playoff probability if no playoffs)
        sort_col = 'winner' if playoff_results else 'playoffs'
        standings = standings.sort_values(sort_col, ascending=False)
        
        return standings


# Convenience function for quick simulation
def simulate_season(player_projections: pd.DataFrame,
                   schedule_df: pd.DataFrame, 
                   league_settings: Dict,
                   num_sims: int = 10000,
                   payouts: List[float] = [800, 300, 100]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convenience function to simulate a season in one call.
    
    Args:
        player_projections: Team projections by week
        schedule_df: League schedule
        league_settings: League configuration
        num_sims: Number of simulations
        payouts: Prize distribution
        
    Returns:
        Tuple of (schedule_results, standings_results)
    """
    simulator = SeasonSimulator(league_settings)
    return simulator.simulate_season(player_projections, schedule_df, num_sims, True, payouts)
