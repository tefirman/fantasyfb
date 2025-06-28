# fantasyfb/analysis/simulator.py
"""
Season Simulator - handles Monte Carlo simulations for fantasy seasons.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from ..utils.config import SimulationConfig

logger = logging.getLogger(__name__)


class SeasonSimulator:
    """
    Handles fantasy season simulations using Monte Carlo methods.
    
    Responsibilities:
    - Regular season simulations
    - Playoff simulations  
    - Best ball simulations
    - Starter optimization
    """

    def __init__(self, league, config: SimulationConfig = None):
        """
        Initialize SeasonSimulator.
        
        Args:
            league: Parent League object
            config: Simulation configuration
        """
        self.league = league
        self.config = config or SimulationConfig()

    def season_sims(
        self,
        postseason: bool = True,
        payouts: List[float] = None,
        fixed_winner: Optional[List] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Run full season Monte Carlo simulations.
        
        Args:
            postseason: Include playoff simulations
            payouts: Prize structure [1st, 2nd, 3rd]
            fixed_winner: [week, team_name] to fix a specific result
            
        Returns:
            Tuple of (schedule_results, standings_results)
        """
        logger.info(f"Running {self.config.num_sims} season simulations...")

        # Ensure we have player data
        players = self.league.load_players()
        schedule = self.league.get_schedule()

        # Get weekly projections for all teams
        projections = self._generate_weekly_projections(players, schedule)

        # Merge projections with schedule
        schedule_with_projections = self._merge_schedule_projections(schedule, projections)

        # Run Monte Carlo simulations
        schedule_sims = self._simulate_games(schedule_with_projections, fixed_winner)

        # Calculate standings from game results
        standings_sims = self._calculate_standings(schedule_sims, postseason, payouts)

        # Aggregate results
        schedule_results = self._aggregate_schedule_results(schedule_sims)
        standings_results = self._aggregate_standings_results(standings_sims, postseason)

        logger.info("Season simulations completed")
        return schedule_results, standings_results

    def bestball_sims(self, payouts: List[float] = None) -> pd.DataFrame:
        """
        Run best ball simulations where optimal lineups are set automatically.
        
        Args:
            payouts: Prize structure
            
        Returns:
            Final standings with best ball optimization
        """
        logger.info(f"Running {self.config.num_sims} best ball simulations...")

        players = self.league.load_players()

        # Generate projections for remaining weeks
        projections = self._generate_bestball_projections(players)

        # Run simulations with optimal lineup setting
        standings = self._simulate_bestball_season(projections, payouts)

        logger.info("Best ball simulations completed")
        return standings

    def _generate_weekly_projections(self, players: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
        """Generate weekly scoring projections for all teams."""
        logger.debug("Generating weekly projections...")

        projections = pd.DataFrame({
            "fantasy_team": pd.Series(dtype='str'),
            "week": pd.Series(dtype='int'),
            "points_avg": pd.Series(dtype='float'),
            "points_var": pd.Series(dtype='float')
        })

        # For each week in the season
        for week in range(1, 18):  # NFL weeks 1-17
            # Set starters for this week
            week_starters = self._set_starters(players, week)

            # Calculate team totals
            team_projections = (
                week_starters.loc[week_starters.starter]
                .groupby("fantasy_team")[["points_avg", "points_stdev"]]
                .agg({
                    "points_avg": "sum",
                    "points_stdev": lambda x: np.sqrt(np.sum(x**2))  # Combine standard deviations
                })
                .reset_index()
            )

            team_projections["week"] = week
            team_projections["points_var"] = team_projections["points_stdev"] ** 2

            if not team_projections.empty:
                if projections.empty:
                    projections = team_projections.copy()
                else:
                    projections = pd.concat([projections, team_projections], ignore_index=True)

        return projections

    def _generate_bestball_projections(self, players: pd.DataFrame) -> pd.DataFrame:
        """Generate projections for best ball (optimal lineup setting)."""
        logger.debug("Generating best ball projections...")

        projections = pd.DataFrame()

        for week in range(self.league.week, self.league.settings['playoff_start_week']):
            # For best ball, we simulate all players and then optimize lineups
            week_projections = players.loc[
                ~players.fantasy_team.isnull(),
                ['player_id_sr', 'name', 'position', 'fantasy_team', 'points_avg', 'points_stdev']
            ].copy()

            week_projections['week'] = week

            # Add injury and bye week considerations
            week_projections['available'] = (
                (players.until.isnull() | (players.until < week)) &
                (players.bye_week != week)
            )

            projections = pd.concat([projections, week_projections], ignore_index=True)

        return projections

    def _set_starters(self, players: pd.DataFrame, week: int) -> pd.DataFrame:
        """Set optimal starters for each team for a given week."""
        # This implements your existing starters() logic
        players = players.copy()
        players["starter"] = False
        players["injured"] = (players.until >= week) | (players.bye_week == week)

        # Sort by projected points (descending)
        players = players.sort_values(by="points_avg", ascending=False)

        # Set starters for each position
        roster_spots = self.league.roster_spots
        position_requirements = roster_spots.loc[
            ~roster_spots.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])
        ].set_index('position').to_dict()['count']

        # Regular positions first
        for pos in position_requirements:
            for team in self.league.teams:
                team_name = team['name']
                available_players = players.loc[
                    (players.fantasy_team == team_name) &
                    ~players.starter &
                    ~players.injured &
                    (players.position == pos)
                ].head(int(position_requirements[pos]))

                players.loc[available_players.index, "starter"] = True

        # Flex positions
        flex_positions = {
            "W/T": ['WR', 'TE'],
            "W/R/T": ['WR', 'RB', 'TE'],
            "Q/W/R/T": ['QB', 'WR', 'RB', 'TE']
        }

        for flex_pos in flex_positions:
            if flex_pos in roster_spots.position.values:
                num_flex = int(roster_spots.loc[roster_spots.position == flex_pos, 'count'].sum())
                eligible_positions = flex_positions[flex_pos]

                for team in self.league.teams:
                    team_name = team['name']
                    available_players = players.loc[
                        (players.fantasy_team == team_name) &
                        ~players.starter &
                        ~players.injured &
                        players.position.isin(eligible_positions)
                    ].head(num_flex)

                    players.loc[available_players.index, "starter"] = True

        return players

    def _merge_schedule_projections(self, schedule: pd.DataFrame, projections: pd.DataFrame) -> pd.DataFrame:
        """Merge schedule with team projections."""
        # Merge team 1 projections
        schedule = pd.merge(
            left=schedule,
            right=projections.rename(columns={
                "fantasy_team": "team_1",
                "points_avg": "points_avg_1",
                "points_var": "points_var_1"
            }),
            how="left",
            on=["week", "team_1"]
        )

        # Merge team 2 projections
        schedule = pd.merge(
            left=schedule,
            right=projections.rename(columns={
                "fantasy_team": "team_2",
                "points_avg": "points_avg_2",
                "points_var": "points_var_2"
            }),
            how="left",
            on=["week", "team_2"]
        )

        # Fill in actual scores for completed games
        schedule["points_avg_1"] = schedule["points_avg_1"].fillna(0.0) + schedule["score_1"].fillna(0.0)
        schedule["points_avg_2"] = schedule["points_avg_2"].fillna(0.0) + schedule["score_2"].fillna(0.0)
        schedule["points_var_1"] = schedule["points_var_1"].fillna(0.0)
        schedule["points_var_2"] = schedule["points_var_2"].fillna(0.0)

        return schedule

    def _simulate_games(self, schedule: pd.DataFrame, fixed_winner: Optional[List] = None) -> pd.DataFrame:
        """Run Monte Carlo simulation of all games."""
        # Replicate schedule for all simulations
        schedule_sims = pd.concat([schedule] * self.config.num_sims, ignore_index=True)
        schedule_sims["sim_num"] = schedule_sims.index // len(schedule)

        # Handle fixed winner if specified
        if fixed_winner:
            week, team_name = fixed_winner
            mask = (schedule_sims.week == week)

            # Determine which team position the fixed winner is in
            winner_is_team1 = (schedule_sims.team_1 == team_name)
            winner_is_team2 = (schedule_sims.team_2 == team_name)

            # Set fixed scores for this matchup
            schedule_sims.loc[mask & winner_is_team1, "points_avg_1"] = 100.1
            schedule_sims.loc[mask & winner_is_team1, "points_avg_2"] = 100.0
            schedule_sims.loc[mask & winner_is_team2, "points_avg_1"] = 100.0
            schedule_sims.loc[mask & winner_is_team2, "points_avg_2"] = 100.1
            schedule_sims.loc[mask, "points_var_1"] = 0.0
            schedule_sims.loc[mask, "points_var_2"] = 0.0

        # Generate random scores
        schedule_sims["sim_1"] = np.random.normal(
            schedule_sims["points_avg_1"],
            np.sqrt(schedule_sims["points_var_1"])
        )
        schedule_sims["sim_2"] = np.random.normal(
            schedule_sims["points_avg_2"],
            np.sqrt(schedule_sims["points_var_2"])
        )

        # Determine winners
        schedule_sims["win_1"] = (schedule_sims.sim_1 > schedule_sims.sim_2).astype(int)
        schedule_sims["win_2"] = 1 - schedule_sims["win_1"]

        return schedule_sims

    def _calculate_standings(self, schedule_sims: pd.DataFrame, postseason: bool, payouts: List[float]) -> pd.DataFrame:
        """Calculate season standings from game simulations."""
        # Convert to team-centric view
        team1_results = schedule_sims[["sim_num", "week", "team_1", "sim_1", "win_1"]].rename(columns={
            "team_1": "team", "sim_1": "points", "win_1": "wins"
        })
        team2_results = schedule_sims[["sim_num", "week", "team_2", "sim_2", "win_2"]].rename(columns={
            "team_2": "team", "sim_2": "points", "win_2": "wins"
        })

        all_results = pd.concat([team1_results, team2_results], ignore_index=True)

        # Calculate regular season standings
        regular_season = all_results.loc[
            all_results.week < self.league.settings["playoff_start_week"]
        ]

        standings = (
            regular_season.groupby(["sim_num", "team"])
            .agg({"wins": "sum", "points": "sum"})
            .reset_index()
            .sort_values(["sim_num", "wins", "points"], ascending=[True, False, False])
        )

        # Add playoff qualification
        standings["playoffs"] = 0
        standings["playoff_bye"] = 0

        for sim in range(self.config.num_sims):
            sim_standings = standings.loc[standings.sim_num == sim]
            playoff_teams = self.league.settings["num_playoff_teams"]

            # Mark playoff teams
            playoff_indices = sim_standings.head(playoff_teams).index
            standings.loc[playoff_indices, "playoffs"] = 1

            # Mark bye week teams (top 2 if 6-team playoffs)
            if playoff_teams == 6:
                bye_indices = sim_standings.head(2).index
                standings.loc[bye_indices, "playoff_bye"] = 1

        # Add playoff results if requested
        if postseason:
            standings = self._simulate_playoffs(standings, schedule_sims, payouts)

        return standings

    def _simulate_playoffs(self, standings: pd.DataFrame, schedule_sims: pd.DataFrame, payouts: List[float]) -> pd.DataFrame:
        """Simulate playoff outcomes."""
        # This would implement your existing playoff simulation logic
        # For now, just add placeholder columns
        standings["winner"] = 0.0
        standings["runner_up"] = 0.0
        standings["third"] = 0.0
        standings["earnings"] = 0.0

        return standings

    def _simulate_bestball_season(self, projections: pd.DataFrame, payouts: List[float]) -> pd.DataFrame:
        """Simulate best ball season with optimal lineup setting."""
        # Replicate projections for all simulations
        season_sims = pd.concat([projections] * self.config.num_sims, ignore_index=True)
        season_sims["sim_num"] = season_sims.index // len(projections)

        # Generate random scores
        season_sims["points_sim"] = np.random.normal(
            season_sims["points_avg"],
            season_sims["points_stdev"]
        )

        # Add injury randomness
        season_sims['injured'] = np.random.rand(len(season_sims)) < 0.1

        # Set optimal lineups for each sim/week/team
        season_sims = self._set_bestball_lineups(season_sims)

        # Calculate team scores
        team_scores = (
            season_sims.loc[season_sims.starter]
            .groupby(['sim_num', 'fantasy_team'])
            .points_sim.sum()
            .reset_index()
        )

        # Determine final standings
        standings = (
            team_scores
            .sort_values(['sim_num', 'points_sim'], ascending=[True, False])
            .reset_index(drop=True)
        )

        standings['place'] = standings.groupby('sim_num').cumcount() + 1
        standings["playoffs"] = (standings['place'] <= self.league.settings["num_playoff_teams"]).astype(float)
        standings["winner"] = (standings['place'] == 1).astype(float)
        standings["runner_up"] = (standings['place'] == 2).astype(float)
        standings["third"] = (standings['place'] == 3).astype(float)

        # Calculate earnings
        if payouts:
            payouts += [0] * (len(self.league.teams) - len(payouts))  # Pad with zeros
            standings['earnings'] = [payouts[place-1] for place in standings['place']]
        else:
            standings['earnings'] = 0.0

        # Aggregate results
        final_standings = (
            standings.groupby('fantasy_team')
            .agg({
                'points_sim': ['mean', 'std'],
                'place': 'mean',
                'playoffs': 'mean',
                'winner': 'mean',
                'runner_up': 'mean',
                'third': 'mean',
                'earnings': 'mean'
            })
            .reset_index()
        )

        # Flatten column names
        final_standings.columns = [
            'team', 'points_avg', 'points_stdev', 'avg_place',
            'playoffs', 'winner', 'runner_up', 'third', 'earnings'
        ]

        # Add missing columns for consistency
        final_standings[["wins_avg", "wins_stdev", "playoff_bye"]] = 0.0

        return final_standings.sort_values('playoffs', ascending=False).reset_index(drop=True)

    def _set_bestball_lineups(self, season_sims: pd.DataFrame) -> pd.DataFrame:
        """Set optimal lineups for best ball format."""
        season_sims = season_sims.copy()
        season_sims['starter'] = False

        # Sort by points (descending) within each sim/week/team
        season_sims = season_sims.sort_values(
            ['sim_num', 'week', 'fantasy_team', 'points_sim'],
            ascending=[True, True, True, False]
        )

        roster_spots = self.league.roster_spots

        # Regular positions
        position_requirements = roster_spots.loc[
            ~roster_spots.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])
        ].set_index('position').to_dict()['count']

        for pos in position_requirements:
            if int(position_requirements[pos]) > 0:
                mask = (
                    (season_sims.position == pos) &
                    season_sims.available &
                    ~season_sims.injured &
                    ~season_sims.starter
                )

                # Set starters for each sim/week/team combination
                starter_indices = (
                    season_sims.loc[mask]
                    .groupby(['sim_num', 'week', 'fantasy_team'])
                    .head(int(position_requirements[pos]))
                    .index
                )

                season_sims.loc[starter_indices, 'starter'] = True

        # Flex positions
        flex_positions = {
            "W/T": ['WR', 'TE'],
            "W/R/T": ['WR', 'RB', 'TE'],
            "Q/W/R/T": ['QB', 'WR', 'RB', 'TE']
        }

        for flex_pos in flex_positions:
            if flex_pos in roster_spots.position.values:
                num_flex = int(roster_spots.loc[roster_spots.position == flex_pos, 'count'].sum())
                eligible_positions = flex_positions[flex_pos]

                if num_flex > 0:
                    mask = (
                        season_sims.position.isin(eligible_positions) &
                        season_sims.available &
                        ~season_sims.injured &
                        ~season_sims.starter
                    )

                    starter_indices = (
                        season_sims.loc[mask]
                        .groupby(['sim_num', 'week', 'fantasy_team'])
                        .head(num_flex)
                        .index
                    )

                    season_sims.loc[starter_indices, 'starter'] = True

        return season_sims

    def _aggregate_schedule_results(self, schedule_sims: pd.DataFrame) -> pd.DataFrame:
        """Aggregate schedule simulation results."""
        schedule_results = (
            schedule_sims.groupby(["week", "team_1", "team_2"])
            .agg({
                "points_avg_1": "mean",
                "points_avg_2": "mean",
                "points_var_1": "mean",
                "points_var_2": "mean",
                "win_1": "mean",
                "win_2": "mean"
            })
            .reset_index()
        )

        # Round for readability
        for col in ["points_avg_1", "points_avg_2", "points_var_1", "points_var_2"]:
            schedule_results[col] = schedule_results[col].round(1)

        return schedule_results.sort_values(["week", "team_1", "team_2"]).reset_index(drop=True)

    def _aggregate_standings_results(self, standings_sims: pd.DataFrame, postseason: bool) -> pd.DataFrame:
        """Aggregate standings simulation results."""
        # Calculate means and standard deviations
        standings_agg = (
            standings_sims.groupby("team")
            .agg({
                "wins": ["mean", "std"],
                "points": ["mean", "std"],
                "playoffs": "mean",
                "playoff_bye": "mean"
            })
            .reset_index()
        )

        # Flatten column names
        standings_agg.columns = [
            "team", "wins_avg", "wins_stdev",
            "points_avg", "points_stdev", "playoffs", "playoff_bye"
        ]

        # Add postseason results if available
        if postseason and "winner" in standings_sims.columns:
            postseason_agg = (
                standings_sims.groupby("team")
                .agg({
                    "winner": "mean",
                    "runner_up": "mean",
                    "third": "mean",
                    "earnings": "mean"
                })
                .reset_index()
            )

            standings_agg = pd.merge(standings_agg, postseason_agg, on="team")

        # Calculate per-game averages
        all_scores = pd.concat([
            standings_sims[["team", "points"]],
            standings_sims[["team", "points"]].rename(columns={"team": "team"})
        ])

        per_game_stats = (
            all_scores.groupby("team")
            .agg({
                "points": ["mean", "std"]
            })
            .reset_index()
        )
        per_game_stats.columns = ["team", "per_game_avg", "per_game_stdev"]
        per_game_stats["per_game_fano"] = per_game_stats["per_game_stdev"] / per_game_stats["per_game_avg"]

        standings_agg = pd.merge(standings_agg, per_game_stats, on="team")

        # Round for readability
        numeric_columns = [
            "wins_avg", "wins_stdev", "points_avg", "points_stdev",
            "per_game_avg", "per_game_stdev", "per_game_fano"
        ]
        for col in numeric_columns:
            if col in standings_agg.columns:
                standings_agg[col] = standings_agg[col].round(3)

        # Sort by primary success metric
        sort_col = "winner" if postseason and "winner" in standings_agg.columns else "playoffs"
        standings_agg = standings_agg.sort_values(sort_col, ascending=False).reset_index(drop=True)

        return standings_agg
