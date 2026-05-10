"""
Fantasy football season simulation engine.

Monte Carlo simulation of fantasy football seasons, including regular season
standings, playoff brackets, and payout calculations. Completed games are
locked to their real scores so historical results aren't re-randomized;
only future weeks contribute variance.
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
        # Lock in real scores for completed games before any simulation runs.
        # Both the regular-season Monte Carlo and the playoff bracket then
        # inherit deterministic outcomes for anything already played.
        locked_projections = self._lock_completed_weeks(player_projections, schedule_df)

        schedule_with_projections = self._merge_schedule_projections(schedule_df, locked_projections)

        if fixed_winner:
            schedule_with_projections = self._apply_fixed_winner(schedule_with_projections, fixed_winner)

        schedule_sims = self._simulate_all_matchups(schedule_with_projections, num_sims)

        standings_sims = self._calculate_regular_season_standings(schedule_sims)

        final_results = None
        if include_playoffs:
            final_results = self._simulate_playoffs(
                standings_sims, schedule_with_projections, locked_projections, payouts
            )

        schedule_results = self._aggregate_schedule_results(schedule_sims)
        standings_results = self._aggregate_standings_results(standings_sims, final_results, payouts)

        return schedule_results, standings_results

    def _lock_completed_weeks(self, projections_df: pd.DataFrame,
                              schedule_df: pd.DataFrame) -> pd.DataFrame:
        """Override projections with real scores for completed games.

        For any (fantasy_team, week) where the team played in a game that
        already has a non-zero score, set points_avg to the real score and
        points_stdev to 0. Downstream Monte Carlo then produces a
        deterministic outcome for that matchup. Future weeks are untouched.
        """
        team1 = schedule_df[['week', 'team_1', 'score_1']].rename(
            columns={'team_1': 'fantasy_team', 'score_1': 'real_score'}
        )
        team2 = schedule_df[['week', 'team_2', 'score_2']].rename(
            columns={'team_2': 'fantasy_team', 'score_2': 'real_score'}
        )
        team_scores = pd.concat([team1, team2], ignore_index=True)
        # _clean_schedule zeros out scores for unplayed weeks, so a positive
        # real_score is the marker that the game is in the books.
        team_scores = team_scores[team_scores['real_score'].astype(float) > 0]

        if team_scores.empty:
            return projections_df.copy()

        locked = projections_df.merge(
            team_scores, on=['week', 'fantasy_team'], how='left'
        )
        completed = locked['real_score'].notna()
        locked.loc[completed, 'points_avg'] = locked.loc[completed, 'real_score'].astype(float)
        locked.loc[completed, 'points_stdev'] = 0.0
        return locked.drop(columns=['real_score'])

    def _simulate_playoffs(self, standings_df: pd.DataFrame,
                          schedule_df: pd.DataFrame,
                          projections_df: pd.DataFrame,
                          payouts: List[float]) -> Dict[str, pd.DataFrame]:
        """Simulate playoff brackets and determine final rankings."""
        playoff_teams = standings_df[standings_df['playoffs'] == 1].copy()
        playoff_teams['seed'] = playoff_teams.index % self.settings['num_playoff_teams']

        if self.settings['num_playoff_teams'] == 6:
            wild_card_week = self.settings['playoff_start_week']
            semifinalists = self._simulate_6_team_wildcard(
                playoff_teams, projections_df, wild_card_week
            )

            semifinal_week = self.settings['playoff_start_week'] + 1
            finalists, semifinal_losers = self._simulate_6_team_semifinals(
                semifinalists, projections_df, semifinal_week
            )

            championship_week = self.settings['playoff_start_week'] + 2
            winners, runners_up = self._simulate_championship(finalists, projections_df, championship_week)

            third_place_winners = self._simulate_third_place_game(
                semifinal_losers, projections_df, championship_week
            )

        else:
            semifinal_week = self.settings['playoff_start_week']
            finalists, semifinal_losers = self._simulate_4_team_semifinals(
                playoff_teams, projections_df, semifinal_week
            )

            championship_week = self.settings['playoff_start_week'] + 1
            winners, runners_up = self._simulate_championship(finalists, projections_df, championship_week)

            third_place_winners = self._simulate_third_place_game(
                semifinal_losers, projections_df, championship_week
            )

        total_sims = len(standings_df['num_sim'].unique())

        return {
            'winners': winners.groupby('team').size() / total_sims,
            'runners_up': runners_up.groupby('team').size() / total_sims,
            'third_place': third_place_winners.groupby('team').size() / total_sims,
        }

    def _merge_schedule_projections(self, schedule_df: pd.DataFrame,
                                  projections_df: pd.DataFrame) -> pd.DataFrame:
        """Merge schedule with team projections for each week."""
        schedule = schedule_df.copy()

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

        proj_cols = ['points_avg_1', 'points_avg_2', 'points_stdev_1', 'points_stdev_2']
        for col in proj_cols:
            schedule[col] = schedule[col].fillna(0.0)

        return schedule

    def _apply_fixed_winner(self, schedule_df: pd.DataFrame,
                           fixed_winner: List) -> pd.DataFrame:
        """Apply a fixed winner for a specific week/team."""
        week, team_name = fixed_winner
        schedule = schedule_df.copy()

        matchup_mask = (
            (schedule['week'] == week) &
            ((schedule['team_1'] == team_name) | (schedule['team_2'] == team_name))
        )

        if matchup_mask.any():
            if (schedule.loc[matchup_mask, 'team_1'] == team_name).any():
                winner_col, loser_col = 'points_avg_1', 'points_avg_2'
                winner_std, loser_std = 'points_stdev_1', 'points_stdev_2'
            else:
                winner_col, loser_col = 'points_avg_2', 'points_avg_1'
                winner_std, loser_std = 'points_stdev_2', 'points_stdev_1'

            schedule.loc[matchup_mask, winner_col] = 100.1
            schedule.loc[matchup_mask, loser_col] = 100.0
            schedule.loc[matchup_mask, winner_std] = 0.0
            schedule.loc[matchup_mask, loser_std] = 0.0

        return schedule

    def _simulate_all_matchups(self, schedule_df: pd.DataFrame,
                              num_sims: int) -> pd.DataFrame:
        """Run Monte Carlo simulation for all matchups."""
        schedule_sims = pd.concat([schedule_df] * num_sims, ignore_index=True)
        schedule_sims['num_sim'] = schedule_sims.index // len(schedule_df)

        schedule_sims['sim_1'] = (
            np.random.normal(loc=0, scale=1, size=len(schedule_sims)) *
            schedule_sims['points_stdev_1'] + schedule_sims['points_avg_1']
        ).astype(float)

        schedule_sims['sim_2'] = (
            np.random.normal(loc=0, scale=1, size=len(schedule_sims)) *
            schedule_sims['points_stdev_2'] + schedule_sims['points_avg_2']
        ).astype(float)

        schedule_sims['win_1'] = (schedule_sims['sim_1'] > schedule_sims['sim_2']).astype(int)
        schedule_sims['win_2'] = 1 - schedule_sims['win_1']

        return schedule_sims

    def _calculate_regular_season_standings(self, schedule_sims: pd.DataFrame) -> pd.DataFrame:
        """Calculate regular season win/loss records from simulated games."""
        team1_records = schedule_sims[['num_sim', 'week', 'team_1', 'sim_1', 'win_1']].rename(
            columns={'team_1': 'team', 'sim_1': 'points', 'win_1': 'wins'}
        )
        team2_records = schedule_sims[['num_sim', 'week', 'team_2', 'sim_2', 'win_2']].rename(
            columns={'team_2': 'team', 'sim_2': 'points', 'win_2': 'wins'}
        )

        standings = pd.concat([team1_records, team2_records], ignore_index=True)

        standings = standings[standings['week'] < self.settings['playoff_start_week']]

        standings = (
            standings.groupby(['num_sim', 'team'])
            .agg({'wins': 'sum', 'points': 'sum'})
            .sort_values(['num_sim', 'wins', 'points'], ascending=[True, False, False])
            .reset_index()
        )

        standings['playoffs'] = 0
        standings.loc[
            standings.index % self.settings.get('num_teams', 12) < self.settings['num_playoff_teams'],
            'playoffs'
        ] = 1

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

            week_projections = projections_df[projections_df['week'] == week]

            if len(sim_teams) >= 2:
                byes = sim_teams[sim_teams['seed'].isin([0, 1])]
                winners.extend(byes.to_dict('records'))

            if len(sim_teams) >= 6:
                matchup1 = sim_teams[sim_teams['seed'].isin([2, 5])]
                matchup2 = sim_teams[sim_teams['seed'].isin([3, 4])]

                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)

                winners.extend([winner1, winner2])

        return pd.DataFrame(winners)

    def _simulate_6_team_semifinals(self, teams_df: pd.DataFrame,
                                   projections_df: pd.DataFrame, week: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Simulate 6-team playoff semifinals."""
        winners = []
        losers = []

        for sim_num in teams_df['num_sim'].unique():
            sim_teams = teams_df[teams_df['num_sim'] == sim_num].copy()

            if self.settings.get('uses_playoff_reseeding', False):
                sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)

            week_projections = projections_df[projections_df['week'] == week]

            if len(sim_teams) >= 4:
                sim_teams = sim_teams.reset_index(drop=True)
                matchup1 = sim_teams.iloc[[0, 3]]
                matchup2 = sim_teams.iloc[[1, 2]]

                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)

                loser1 = matchup1[~matchup1.index.isin([matchup1[matchup1['team'] == winner1['team']].index[0]])].iloc[0].to_dict()
                loser2 = matchup2[~matchup2.index.isin([matchup2[matchup2['team'] == winner2['team']].index[0]])].iloc[0].to_dict()

                winners.extend([winner1, winner2])
                losers.extend([loser1, loser2])

        return pd.DataFrame(winners), pd.DataFrame(losers)

    def _simulate_4_team_semifinals(self, playoff_teams: pd.DataFrame,
                                   projections_df: pd.DataFrame, week: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Simulate 4-team playoff semifinals."""
        winners = []
        losers = []

        for sim_num in playoff_teams['num_sim'].unique():
            sim_teams = playoff_teams[playoff_teams['num_sim'] == sim_num].copy()
            sim_teams = sim_teams.sort_values('seed').reset_index(drop=True)

            week_projections = projections_df[projections_df['week'] == week]

            if len(sim_teams) >= 4:
                matchup1 = sim_teams.iloc[[0, 3]]
                matchup2 = sim_teams.iloc[[1, 2]]

                winner1 = self._simulate_matchup_with_projections(matchup1, week_projections)
                winner2 = self._simulate_matchup_with_projections(matchup2, week_projections)

                loser1 = matchup1[~matchup1.index.isin([matchup1[matchup1['team'] == winner1['team']].index[0]])].iloc[0].to_dict()
                loser2 = matchup2[~matchup2.index.isin([matchup2[matchup2['team'] == winner2['team']].index[0]])].iloc[0].to_dict()

                winners.extend([winner1, winner2])
                losers.extend([loser1, loser2])

        return pd.DataFrame(winners), pd.DataFrame(losers)

    def _simulate_championship(self, finalists: pd.DataFrame,
                              projections_df: pd.DataFrame, week: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Simulate championship round, returning (winners, runners_up) per sim."""
        winners = []
        runners_up = []

        for sim_num in finalists['num_sim'].unique():
            sim_teams = finalists[finalists['num_sim'] == sim_num]

            if len(sim_teams) >= 2:
                week_projections = projections_df[projections_df['week'] == week]
                winner = self._simulate_matchup_with_projections(sim_teams, week_projections)
                runner_up = sim_teams[sim_teams['team'] != winner['team']].iloc[0].to_dict()
                winners.append(winner)
                runners_up.append(runner_up)

        return pd.DataFrame(winners), pd.DataFrame(runners_up)

    def _simulate_third_place_game(self, semifinal_losers: pd.DataFrame,
                                   projections_df: pd.DataFrame, week: int) -> pd.DataFrame:
        """Simulate third place game between semifinal losers."""
        third_place_winners = []

        for sim_num in semifinal_losers['num_sim'].unique():
            sim_teams = semifinal_losers[semifinal_losers['num_sim'] == sim_num]

            if len(sim_teams) >= 2:
                week_projections = projections_df[projections_df['week'] == week]
                winner = self._simulate_matchup_with_projections(sim_teams, week_projections)
                third_place_winners.append(winner)

        return pd.DataFrame(third_place_winners)

    def _simulate_matchup_with_projections(self, teams_df: pd.DataFrame,
                                         week_projections: pd.DataFrame) -> Dict:
        """Simulate a matchup between teams using week projections."""
        teams = teams_df.copy()

        projection_cols = ['points_avg', 'points_stdev', 'fantasy_team']
        for col in projection_cols:
            if col in teams.columns:
                teams = teams.drop(columns=[col])

        teams = pd.merge(teams, week_projections,
                        left_on='team', right_on='fantasy_team', how='left')

        teams['points_avg'] = teams['points_avg'].fillna(100.0)
        teams['points_stdev'] = teams['points_stdev'].fillna(10.0)

        teams['sim_score'] = (
            np.random.normal(0, 1, len(teams)) * teams['points_stdev'] + teams['points_avg']
        )

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
        standings = standings_sims.groupby('team').agg({
            'wins': ['mean', 'std'],
            'points': ['mean', 'std'],
            'playoffs': 'mean',
            'playoff_bye': 'mean'
        }).round(3).reset_index()

        standings.columns = [
            'team', 'wins_avg', 'wins_stdev', 'points_avg', 'points_stdev',
            'playoffs', 'playoff_bye'
        ]

        if playoff_results:
            standings['winner'] = standings['team'].map(playoff_results.get('winners', {})).fillna(0.0)
            standings['runner_up'] = standings['team'].map(playoff_results.get('runners_up', {})).fillna(0.0)
            standings['third'] = standings['team'].map(playoff_results.get('third_place', {})).fillna(0.0)

            earnings = (
                standings['winner'] * payouts[0] +
                standings['runner_up'] * payouts[1] +
                standings['third'] * payouts[2] if len(payouts) > 2 else 0
            )
            standings['earnings'] = earnings.round(2)
        else:
            standings['winner'] = 0.0
            standings['runner_up'] = 0.0
            standings['third'] = 0.0
            standings['earnings'] = 0.0

        sort_col = 'winner' if playoff_results else 'playoffs'
        standings = standings.sort_values(sort_col, ascending=False)

        return standings


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
