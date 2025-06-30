# fantasyfb/analysis/player_analyzer.py
"""
Player Analyzer - handles player statistics, projections, and WAR calculations.
"""

import datetime
import logging

import numpy as np
import pandas as pd

from ..utils import sportsref_nfl as sr
from ..utils.config import PlayerConfig

logger = logging.getLogger(__name__)


class PlayerAnalyzer:
    """
    Handles all player-related analysis including:
    - Statistical rate calculations
    - WAR (Wins Above Replacement) calculations
    - Player projections
    - Injury and availability tracking
    """

    def __init__(self, league, config: PlayerConfig = None):
        """
        Initialize PlayerAnalyzer.

        Args:
            league: Parent League object
            config: Player analysis configuration
        """
        self.league = league
        self.config = config or PlayerConfig()
        self.stats = None

    def process_players(self, players: pd.DataFrame) -> pd.DataFrame:
        """
        Main method to process player data for advanced analysis.

        Args:
            players: DataFrame with basic player data already processed by DataManager

        Returns:
            Enhanced player DataFrame with rates, projections, WAR, etc.
        """
        logger.info("Processing player data for advanced analysis...")

        # Apply name corrections first
        players = self._apply_name_corrections(players)
        
        # Calculate player rates (points_rate, points_stdev)
        players = self._calculate_player_rates(players)
        
        # Calculate WAR values
        players = self._calculate_war(players)
        
        # Add game factors for current week
        players = self._add_game_factors(players)

        logger.info(f"Advanced processing completed for {len(players)} players")
        return players

    def _apply_name_corrections(self, players: pd.DataFrame) -> pd.DataFrame:
        """Apply name corrections between Yahoo and Pro Football Reference."""
        logger.debug("Applying name corrections...")

        try:
            corrections = pd.read_csv(
                "https://raw.githubusercontent.com/"
                + "tefirman/fantasy-data/main/fantasyfb/name_corrections.csv"
            )
            
            players = pd.merge(left=players, right=corrections, how="left", on="name")
            to_fix = ~players.new_name.isnull()
            players.loc[to_fix, "name"] = players.loc[to_fix, "new_name"]
            
            return players.drop(columns=["new_name"], errors="ignore")
        
        except Exception as e:
            logger.warning(f"Could not load name corrections: {e}")
            return players

    def _load_stats_if_needed(self, start: int, finish: int):
        """Load game-by-game stats if not already loaded."""
        if self.stats is None:
            logger.info(f"Loading stats from {start} to {finish}")
            self.stats = sr.get_bulk_stats(
                start // 100, start % 100, 
                finish // 100, finish % 100, 
                False, "GameByGameFantasyFootballStats.csv"
            )
            
            # Add fantasy points calculation
            self._add_fantasy_points()
            
            # Merge with NFL schedule for elo data
            self.stats = pd.merge(
                left=self.stats,
                right=self.league.nfl_schedule,
                how="left",
                on=["season", "week", "team"],
            )

    def _add_fantasy_points(self):
        """Calculate fantasy points based on league scoring settings."""
        logger.debug("Calculating fantasy points...")
        
        scoring = self.league.scoring
        
        # Separate offense and defense
        offense = self.stats.loc[self.stats.position != "DEF"].copy()
        defense = self.stats.loc[self.stats.position == "DEF"].copy()
        
        # Calculate offensive points
        offense["points"] = (
            offense["rush_yds"] * scoring.get("Rush Yds", 0)
            + offense["rush_att"] * scoring.get("Rush Att", 0)
            + offense["rush_td"] * scoring.get("Rush TD", 0)
            + offense["rush_first_down"] * scoring.get("Rush 1D", 0)
            + offense["rec"] * scoring.get("Rec", 0)
            + offense["rec_yds"] * scoring.get("Rec Yds", 0)
            + offense["rec_td"] * scoring.get("Rec TD", 0)
            + offense["rec_first_down"] * scoring.get("Rec 1D", 0)
            + offense["pass_yds"] * scoring.get("Pass Yds", 0)
            + offense["pass_cmp"] * scoring.get("Pass Comp", 0)
            + offense["pass_td"] * scoring.get("Pass TD", 0)
            + offense["pass_first_down"] * scoring.get("Pass 1D", 0)
            + offense["pass_int"] * scoring.get("Int Thrown", 0)
            + offense["fumbles_lost"] * scoring.get("Fum Lost", 0)
            + (offense["kick_ret_yds"] + offense["punt_ret_yds"]) * scoring.get("Ret Yds", 0)
            + (offense["kick_ret_td"] + offense["punt_ret_td"]) * scoring.get("Ret TD", 0)
            + offense["xpm"] * scoring.get("PAT Made", 0)
            + offense["fgm"] * scoring.get("FG 0-19", 0)  # Simplified FG scoring
        )
        
        # Add TE bonuses
        tes = offense.position == 'TE'
        offense.loc[tes, 'points'] += (
            offense.loc[tes, 'rec'] * scoring.get('TE Rec Bonus', 0) +
            (offense.loc[tes, 'rush_first_down'] + offense.loc[tes, 'rec_first_down'] + 
             offense.loc[tes, 'pass_first_down']) * scoring.get('TE 1D Bonus', 0)
        )
        
        # Add yardage bonuses
        offense.loc[offense.pass_yds >= 300, 'points'] += scoring.get('Pass 300+', 0)
        offense.loc[offense.rush_yds >= 100, 'points'] += scoring.get('Rush 100+', 0)
        offense.loc[offense.rec_yds >= 100, 'points'] += scoring.get('Rec 100+', 0)
        
        # Calculate defensive points
        defense["points"] = (
            defense["sacks"] * scoring.get("Sack", 0)
            + defense["def_int"] * scoring.get("Int", 0)
            + defense["fumbles_rec"] * scoring.get("Fum Rec", 0)
            + (defense["def_int_td"] + defense['fumbles_rec_td'] 
               + defense["kick_ret_td"] + defense["punt_ret_td"]) * scoring.get("TD", 0)
        )
        
        # Add points allowed scoring for defenses
        defense.loc[defense.points_allowed == 0, "points"] += scoring.get("Pts Allow 0", 0)
        defense.loc[(defense.points_allowed >= 1) & (defense.points_allowed <= 6), "points"] += scoring.get("Pts Allow 1-6", 0)
        defense.loc[(defense.points_allowed >= 7) & (defense.points_allowed <= 13), "points"] += scoring.get("Pts Allow 7-13", 0)
        defense.loc[(defense.points_allowed >= 14) & (defense.points_allowed <= 20), "points"] += scoring.get("Pts Allow 14-20", 0)
        defense.loc[(defense.points_allowed >= 21) & (defense.points_allowed <= 27), "points"] += scoring.get("Pts Allow 21-27", 0)
        defense.loc[(defense.points_allowed >= 28) & (defense.points_allowed <= 34), "points"] += scoring.get("Pts Allow 28-34", 0)
        defense.loc[defense.points_allowed >= 35, "points"] += scoring.get("Pts Allow 35+", 0)
        
        self.stats = pd.concat([offense, defense], ignore_index=True)

    def _calculate_player_rates(self, players: pd.DataFrame) -> pd.DataFrame:
        """Calculate player rates and projections."""
        logger.debug("Calculating player rates...")

        as_of = self.league.season * 100 + self.league.week
        self._load_stats_if_needed(
            min(getattr(self.config, 'earliest', {}).values()) or (as_of - 200), 
            as_of - 1
        )

        # Get weighting factors (using defaults if config doesn't have them)
        weighting_factors = getattr(self.config, 'weighting_factors', None)
        if weighting_factors is None:
            # Default weighting factors by position
            weighting_factors = pd.DataFrame({
                'position': ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'],
                'basal': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                'opp_elo_weight': [0.3, 0.3, 0.3, 0.3, 0.1, 0.4],
                'string_weight': [0.2, 0.4, 0.4, 0.3, 0.1, 0.1],
                'time_scale': [0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
            })

        # Filter stats to relevant timeframe
        rel_stats = self.stats.copy()
        
        # Merge weighting factors
        rel_stats = pd.merge(
            left=rel_stats,
            right=weighting_factors,
            how="left",
            on="position",
        )

        # Calculate game factors and relative points
        rel_stats["game_factor"] = (
            rel_stats["basal"]
            + rel_stats["opp_elo_weight"] * rel_stats["elo_diff"].fillna(0)
            + rel_stats["string_weight"] * (1 - rel_stats["string"].fillna(1))
        )
        rel_stats.loc[rel_stats.game_factor < 0.25, "game_factor"] = 0.25
        rel_stats["rel_points"] = rel_stats.points / rel_stats.game_factor

        # Calculate positional averages
        by_pos = pd.merge(
            left=rel_stats.groupby("position")
            .rel_points.mean()
            .reset_index()
            .rename(columns={"rel_points": "points_rate"}),
            right=rel_stats.groupby("position")
            .rel_points.std()
            .reset_index()
            .rename(columns={"rel_points": "points_stdev"}),
            how="inner",
            on="position",
        )
        by_pos["player_id_sr"] = "avg_" + by_pos["position"]

        # Apply time weighting
        rel_stats["weeks_ago"] = (
            17 * (as_of // 100 - rel_stats.season) + as_of % 100 - rel_stats.week
        )
        rel_stats["time_factor"] = 1 - rel_stats.weeks_ago * rel_stats.time_scale.fillna(0.05)
        rel_stats = rel_stats.loc[rel_stats.time_factor > 0].reset_index(drop=True)

        # Calculate time-weighted averages by player
        rel_stats = pd.merge(
            left=rel_stats,
            right=rel_stats.groupby(["player_id_sr", "position"])
            .agg({"time_factor": "sum", "name": "count"})
            .rename(columns={"name": "num_games", "time_factor": "time_factor_sum"})
            .reset_index(),
            how="inner",
            on=["player_id_sr", "position"],
        )
        
        rel_stats.time_factor = (
            rel_stats.time_factor * rel_stats.num_games / rel_stats.time_factor_sum
        )
        rel_stats["weighted_points"] = rel_stats.rel_points * rel_stats.time_factor

        # Calculate player-specific rates
        by_player = pd.merge(
            left=rel_stats.groupby(["player_id_sr", "position"])
            .weighted_points.mean()
            .reset_index()
            .rename(columns={"weighted_points": "points_rate"}),
            right=rel_stats.groupby(["player_id_sr", "position"])
            .weighted_points.std()
            .reset_index()
            .rename(columns={"weighted_points": "points_stdev"}),
            how="inner",
            on=["player_id_sr", "position"],
        )
        
        by_player = pd.merge(
            left=by_player,
            right=rel_stats.groupby(["player_id_sr", "position"])
            .size()
            .to_frame("num_games")
            .reset_index(),
            how="inner",
            on=["player_id_sr", "position"],
        )

        # Combine player and positional averages
        by_player = pd.concat([
            by_player,
            by_pos[["player_id_sr", "position", "points_rate", "points_stdev"]]
        ], ignore_index=True)
        
        by_player.points_stdev = by_player.points_stdev.fillna(0.0)

        # Apply Bayesian priors for players with limited games
        reference_games = getattr(self.config, 'reference_games', {})
        default_ref_games = 8  # Default reference games
        
        by_player = pd.merge(
            left=by_player,
            right=by_pos[["position", "points_rate", "points_stdev"]].rename(
                columns={"points_rate": "pos_avg", "points_stdev": "pos_stdev"}
            ),
            how="inner",
            on="position",
        )

        for pos in by_player.position.unique():
            ref_games = reference_games.get(pos, default_ref_games)
            pos_mask = by_player.position == pos
            games_mask = by_player.num_games < ref_games
            inds = pos_mask & games_mask
            
            if inds.any():
                by_player.loc[inds, "points_squared"] = (
                    by_player.loc[inds, "num_games"]
                    * (by_player.loc[inds, "points_stdev"] ** 2 + by_player.loc[inds, "points_rate"] ** 2)
                    + (ref_games - by_player.loc[inds, "num_games"])
                    * (by_player.loc[inds, "pos_stdev"] ** 2 + by_player.loc[inds, "pos_avg"] ** 2)
                ) / ref_games
                
                by_player.loc[inds, "points_rate"] = (
                    by_player.loc[inds, "num_games"] * by_player.loc[inds, "points_rate"]
                    + (ref_games - by_player.loc[inds, "num_games"]) * by_player.loc[inds, "pos_avg"]
                ) / ref_games
                
                by_player.loc[inds, "points_stdev"] = (
                    (by_player.loc[inds, "points_squared"] - by_player.loc[inds, "points_rate"] ** 2) ** 0.5
                ).astype(float)

        # Merge back with players
        players = pd.merge(
            left=by_player.drop_duplicates(subset=['player_id_sr'], keep='first'),
            right=players,
            how="right",
            on=["player_id_sr", "position"],
        )
        
        # Fill missing values with positional averages
        for pos in players.position.unique():
            pos_data = by_pos[by_pos.position == pos]
            if len(pos_data) > 0:
                pos_avg = pos_data.iloc[0]
                mask = (players.position == pos) & players.points_rate.isnull()
                players.loc[mask, 'points_rate'] = pos_avg['points_rate']
                players.loc[mask, 'points_stdev'] = pos_avg['points_stdev']

        return players

    def _calculate_war(self, players: pd.DataFrame) -> pd.DataFrame:
        """Calculate Wins Above Replacement for each player."""
        logger.debug("Calculating WAR...")

        as_of = self.league.season * 100 + self.league.week
        self._load_stats_if_needed(as_of - 100, as_of - 1)

        # Create positional histograms from historical data
        pos_hists = {"points": np.arange(-10, 50.1, 0.1)}
        
        for pos in self.stats.position.unique():
            pos_points = self.stats.loc[self.stats.position == pos, "points"]
            if len(pos_points) > 0:
                pos_hists[pos] = np.histogram(pos_points, bins=pos_hists["points"])[0]
                pos_hists[pos] = pos_hists[pos] / sum(pos_hists[pos])
            else:
                # Default distribution if no data
                pos_hists[pos] = np.ones(len(pos_hists["points"]) - 1)
                pos_hists[pos] = pos_hists[pos] / sum(pos_hists[pos])

        # Create FLEX histogram
        flex_positions = ["RB", "WR", "TE"]
        flex_data = self.stats.loc[self.stats.position.isin(flex_positions), "points"]
        if len(flex_data) > 0:
            pos_hists["FLEX"] = np.histogram(flex_data, bins=pos_hists["points"])[0]
            pos_hists["FLEX"] = pos_hists["FLEX"] / sum(pos_hists["FLEX"])
        else:
            pos_hists["FLEX"] = np.ones(len(pos_hists["points"]) - 1)
            pos_hists["FLEX"] = pos_hists["FLEX"] / sum(pos_hists["FLEX"])

        # Simulate average team performance
        num_sims = getattr(self.config, 'war_simulations', 10000)
        sim_scores = self._simulate_average_team(pos_hists, num_sims)

        # Calculate WAR for each player
        players = self._calculate_player_war(players, pos_hists, sim_scores)

        return players

    def _simulate_average_team(self, pos_hists: dict, num_sims: int) -> pd.DataFrame:
        """Simulate average team performance."""
        
        sim_scores = pd.DataFrame({
            "QB": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["QB"], size=num_sims
            ),
            "RB1": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["RB"], size=num_sims
            ),
            "RB2": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["RB"], size=num_sims
            ),
            "WR1": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["WR"], size=num_sims
            ),
            "WR2": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["WR"], size=num_sims
            ),
            "TE": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["TE"], size=num_sims
            ),
            "FLEX": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["FLEX"], size=num_sims
            ),
            "K": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["K"], size=num_sims
            ),
            "DEF": np.random.choice(
                pos_hists["points"][:-1], p=pos_hists["DEF"], size=num_sims
            ),
        })
        
        sim_scores["Total"] = (
            sim_scores.QB + sim_scores.RB1 + sim_scores.RB2 + 
            sim_scores.WR1 + sim_scores.WR2 + sim_scores.TE + 
            sim_scores.FLEX + sim_scores.K + sim_scores.DEF
        )
        
        return sim_scores

    def _calculate_player_war(
        self, players: pd.DataFrame, pos_hists: dict, sim_scores: pd.DataFrame
    ) -> pd.DataFrame:
        """Calculate WAR for each player."""
        
        # Create player simulations
        player_sims = {}
        for idx, player in players.iterrows():
            if pd.notnull(player.get('name')) and pd.notnull(player.get('points_rate')):
                player_sims[player['name']] = np.round(
                    np.random.normal(
                        loc=player['points_rate'], 
                        scale=player.get('points_stdev', 5.0),
                        size=sim_scores.shape[0]
                    )
                )
        
        if not player_sims:
            # No valid players, set default WAR
            players['WAR'] = 0.0
            return players
            
        player_sims_df = pd.DataFrame(player_sims)
        sim_scores = pd.merge(
            left=sim_scores, right=player_sims_df, left_index=True, right_index=True
        )

        # Calculate WAR for each player
        for player_name in player_sims.keys():
            if player_name in sim_scores.columns:
                try:
                    # Find player's position
                    player_pos = players.loc[players.name == player_name, 'position'].iloc[0]
                    
                    # Create alternative lineup with this player
                    cols = sim_scores.columns[:9].tolist()  # Standard lineup positions
                    
                    # Handle position mapping
                    if player_pos in ["RB", "WR"]:
                        lineup_pos = player_pos + "1"  # Use first slot
                    else:
                        lineup_pos = player_pos
                    
                    if lineup_pos in cols:
                        cols.remove(lineup_pos)
                        cols.append(player_name)
                        
                        sim_scores["Alt_Total"] = sim_scores[cols].sum(axis=1)
                        
                        # Calculate win percentage vs average teams
                        war_value = (
                            sum(
                                sim_scores.loc[:sim_scores.shape[0]//2-1, "Alt_Total"].values
                                > sim_scores.loc[sim_scores.shape[0]//2:, "Total"].values
                            ) / (sim_scores.shape[0] // 2) - 0.5
                        ) * 14  # Scale to 14-game season
                        
                        players.loc[players.name == player_name, "WAR"] = war_value
                        del sim_scores["Alt_Total"]
                    
                except Exception as e:
                    logger.warning(f"Could not calculate WAR for {player_name}: {e}")
                    players.loc[players.name == player_name, "WAR"] = 0.0

        # Fill any missing WAR values
        players['WAR'] = players['WAR'].fillna(0.0)
        
        return players

    def _add_game_factors(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add game situation factors for current week projections."""
        logger.debug("Adding game factors...")

        # Merge with current week NFL schedule
        current_week_schedule = self.league.nfl_schedule.loc[
            (self.league.nfl_schedule.season == self.league.season)
            & (self.league.nfl_schedule.week == self.league.week),
            ["team", "elo_diff"]
        ]
        
        players = pd.merge(
            left=players,
            right=current_week_schedule,
            how="left",
            left_on="current_team",
            right_on="team",
        )

        players['elo_diff'] = players['elo_diff'].fillna(0.0)

        # Get weighting factors
        weighting_factors = getattr(self.config, 'weighting_factors', None)
        if weighting_factors is None:
            # Default weighting factors
            weighting_factors = pd.DataFrame({
                'position': ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'],
                'basal': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                'opp_elo_weight': [0.3, 0.3, 0.3, 0.3, 0.1, 0.4],
                'string_weight': [0.2, 0.4, 0.4, 0.3, 0.1, 0.1]
            })

        # Merge weighting factors if not already present
        if "opp_elo_weight" not in players.columns:
            players = pd.merge(
                left=players, right=weighting_factors, how="left", on="position"
            )

        # Calculate factors
        players["opp_factor"] = players["opp_elo_weight"].fillna(0.3) * players["elo_diff"]
        players["string_factor"] = players["string_weight"].fillna(0.3) * (1 - players["string"].fillna(1))
        players["game_factor"] = (
            players["basal"].fillna(1.0) + players["opp_factor"] + players["string_factor"]
        )
        players["points_avg"] = players["points_rate"].fillna(10.0) * players["game_factor"]

        return players.drop(columns=["team", "elo_diff"], errors="ignore")
