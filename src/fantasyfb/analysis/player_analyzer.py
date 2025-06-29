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

        # For now, just add the basic columns that the system expects
        # TODO: Implement full statistical analysis

        # Add basic statistical columns
        if "points_rate" not in players.columns:
            players["points_rate"] = 10.0  # Default points per game

        if "points_stdev" not in players.columns:
            players["points_stdev"] = 5.0  # Default standard deviation

        if "WAR" not in players.columns:
            players["WAR"] = 1.0  # Default WAR

        if "game_factor" not in players.columns:
            players["game_factor"] = 1.0

        if "points_avg" not in players.columns:
            players["points_avg"] = players["points_rate"] * players["game_factor"]

        logger.info(f"Advanced processing completed for {len(players)} players")
        return players

    def _apply_name_corrections(self, players: pd.DataFrame) -> pd.DataFrame:
        """Apply name corrections between Yahoo and Pro Football Reference."""
        logger.debug("Applying name corrections...")

        corrections = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/name_corrections.csv"
        )

        players = pd.merge(left=players, right=corrections, how="left", on="name")
        to_fix = ~players.new_name.isnull()
        players.loc[to_fix, "name"] = players.loc[to_fix, "new_name"]

        return players.drop(columns=["new_name"], errors="ignore")

    def _map_player_ids(self, players: pd.DataFrame) -> pd.DataFrame:
        """Map between Yahoo player IDs and SportsRef player IDs."""
        logger.debug("Mapping player IDs...")

        # Load NFL rosters for ID mapping
        self.nfl_rosters = sr.get_bulk_rosters(
            self.league.season - 1, self.league.season, "NFLRosters.csv"
        )
        self.nfl_rosters = self.nfl_rosters.rename(
            columns={
                "player": "name",
                "player_id": "player_id_sr",
                "team": "current_team",
            }
        )

        # Merge team abbreviations
        players = pd.merge(
            left=players,
            right=self.league.nfl_teams[["real_abbrev", "yahoo"]].rename(
                columns={"yahoo": "editorial_team_abbr", "real_abbrev": "current_team"}
            ),
            how="inner",
            on="editorial_team_abbr",
        )

        # Map IDs based on name and team
        players = pd.merge(
            left=players,
            right=self.nfl_rosters[
                ["name", "current_team", "player_id_sr"]
            ].drop_duplicates(),
            how="left",
            on=["name", "current_team"],
        )

        # Handle special cases (defenses, missing players, etc.)
        defenses = players.position.isin(["DEF"])
        players.loc[defenses, "player_id_sr"] = players.loc[defenses, "name"]

        # Use Yahoo ID as fallback
        missing = players.player_id_sr.isnull()
        players.loc[missing, "player_id_sr"] = players.loc[missing, "player_id"]

        return players

    def _add_injury_data(self, players: pd.DataFrame, season: int) -> pd.DataFrame:
        """Add injury projections and status."""
        # Initialize with proper dtype to avoid FutureWarning
        players["until"] = pd.Series(dtype="float64", index=players.index)

        # Load injury projections for current season
        try:
            inj_proj = pd.read_csv(
                "https://raw.githubusercontent.com/"
                + "tefirman/fantasy-data/main/fantasyfb/injured_list.csv"
            )

            # Use current week - we'll estimate it from the season
            current_week = 1  # Default fallback
            try:
                current_year = datetime.datetime.now().year
                if season == current_year or (
                    season == current_year - 1 and datetime.datetime.now().month < 6
                ):
                    # It's the current season, estimate week from date
                    current_week = min(
                        max(
                            1,
                            (
                                datetime.datetime.now()
                                - datetime.datetime(current_year, 9, 1)
                            ).days
                            // 7,
                        ),
                        18,
                    )
            except (ValueError, TypeError, AttributeError):
                current_week = 1

            inj_proj = inj_proj.loc[inj_proj.until >= current_week]

            players = pd.merge(
                left=players,
                right=inj_proj,
                how="left",
                on=["player_id_sr", "name", "position"],
                suffixes=("", "_proj"),
            )

            # Use projection where available - with proper type handling
            has_proj = ~players.until_proj.isnull()
            if has_proj.any():
                # Convert to numeric, handling any problematic values
                proj_values = pd.to_numeric(
                    players.loc[has_proj, "until_proj"], errors="coerce"
                )
                players.loc[has_proj, "until"] = proj_values

            players = players.drop(columns=["until_proj"], errors="ignore")

        except Exception as e:
            logger.warning(f"Could not load injury projections: {e}")

        return players

    def _add_bye_weeks(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add bye week information."""
        logger.debug("Adding bye weeks...")

        # Calculate bye weeks from NFL schedule
        byes = pd.DataFrame()
        for team in self.league.nfl_schedule.team.unique():
            bye_week = 1
            while (
                (self.league.nfl_schedule.team == team)
                & (self.league.nfl_schedule.season == self.league.season)
                & (self.league.nfl_schedule.week == bye_week)
            ).any():
                bye_week += 1

            byes = pd.concat(
                [byes, pd.DataFrame({"current_team": [team], "bye_week": [bye_week]})],
                ignore_index=True,
            )

        players = pd.merge(left=players, right=byes, how="left", on="current_team")
        return players

    def _add_roster_percentages(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add roster percentage data from Yahoo."""
        logger.debug("Adding roster percentages...")

        # This would use your existing roster percentage logic
        # For now, just add a placeholder
        players["pct_rostered"] = 0.0

        # TODO: Implement actual roster percentage fetching
        # This involves paginated API calls to Yahoo with player IDs

        return players

    def _add_depth_charts(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add depth chart information."""
        logger.debug("Adding depth charts...")

        if (
            self.league.season == self.league.latest_season
            and self.league.week == self.league.current_week
        ):
            # Use current depth charts from ESPN
            try:
                depth_charts = sr.get_all_depth_charts()
                depth_charts = depth_charts.rename(
                    columns={
                        "player": "name",
                        "pos": "position",
                        "team": "current_team",
                    }
                )

                players = pd.merge(
                    left=players,
                    right=depth_charts,
                    how="left",
                    on=["current_team", "name", "position"],
                )
            except Exception as e:
                logger.warning(f"Could not load depth charts: {e}")
                players["string"] = 2.0
        else:
            # Use historical snap counts
            self._load_stats_if_needed(
                self.league.season * 100 + 1, self.league.season * 100 + 17
            )

            strings = (
                self.stats.loc[
                    self.stats.season * 100 + self.stats.week
                    >= self.league.season * 100 + self.league.week
                ]
                .sort_values(by=["season", "week"], ascending=True)[
                    ["player_id_sr", "string"]
                ]
                .drop_duplicates(subset=["player_id_sr"], keep="first")
            )

            players = pd.merge(
                left=players, right=strings, how="left", on=["player_id_sr"]
            )

        # Fill missing depth chart data
        players.loc[players.position == "DEF", "string"] = 1.0
        players.string = players.string.fillna(2.0)

        return players

    def _calculate_rates(self, players: pd.DataFrame) -> pd.DataFrame:
        """Calculate statistical rates for each player."""
        logger.debug("Calculating player rates...")

        as_of = self.league.season * 100 + self.league.week
        self._load_stats_if_needed(min(self.config.earliest.values()), as_of - 1)

        # Filter stats to relevant timeframe
        rel_stats = self.stats.copy()
        for pos in self.config.earliest:
            rel_stats = rel_stats.loc[
                (rel_stats["position"] != pos)
                | (
                    (rel_stats.season * 100 + rel_stats.week <= as_of - 1)
                    & (
                        rel_stats.season * 100 + rel_stats.week
                        >= self.config.earliest[pos]
                    )
                )
            ].reset_index(drop=True)

        # Merge weighting factors
        rel_stats = pd.merge(
            left=rel_stats,
            right=self.config.weighting_factors,
            how="left",
            on="position",
        )

        # Calculate game factors and relative points
        rel_stats["game_factor"] = (
            rel_stats["basal"]
            + rel_stats["opp_elo_weight"] * rel_stats["elo_diff"]
            + rel_stats["string_weight"] * (1 - rel_stats["string"])
        )
        rel_stats.loc[rel_stats.game_factor < 0.25, "game_factor"] = 0.25
        rel_stats["rel_points"] = rel_stats.points / rel_stats.game_factor

        # Calculate positional averages
        by_pos = self._apply_positional_averages(rel_stats)

        # Limit games per position
        for pos in self.config.reference_games:
            rel_stats = pd.concat(
                [
                    rel_stats.loc[rel_stats.position != pos],
                    rel_stats.loc[rel_stats.position == pos]
                    .groupby(["player_id_sr", "position"])
                    .head(self.config.reference_games[pos]),
                ],
                ignore_index=True,
            )

        # Apply time weighting
        rel_stats = self._apply_time_weighting(rel_stats, as_of)

        # Calculate player-specific rates
        by_player = self._calculate_player_rates(rel_stats, by_pos)

        # Merge with player data
        players = pd.merge(
            left=by_player,
            right=players,
            how="right",
            on=["player_id_sr", "position"],
        )

        return players

    def _calculate_war(self, players: pd.DataFrame) -> pd.DataFrame:
        """Calculate Wins Above Replacement for each player."""
        logger.debug("Calculating WAR...")

        as_of = self.league.season * 100 + self.league.week
        self._load_stats_if_needed(as_of - 100, as_of - 1)

        # Create positional histograms
        pos_hists = {"points": np.arange(-10, 50.1, 0.1)}
        for pos in self.stats.position.unique():
            pos_hists[pos] = np.histogram(
                self.stats.loc[self.stats.position == pos, "points"],
                bins=pos_hists["points"],
            )[0]
            pos_hists[pos] = pos_hists[pos] / sum(pos_hists[pos])

        pos_hists["FLEX"] = np.histogram(
            self.stats.loc[self.stats.position.isin(["RB", "WR", "TE"]), "points"],
            bins=pos_hists["points"],
        )[0]
        pos_hists["FLEX"] = pos_hists["FLEX"] / sum(pos_hists["FLEX"])

        # Simulate average team performance
        num_sims = self.config.war_simulations
        sim_scores = self._simulate_average_team(pos_hists, num_sims)

        # Calculate WAR for each player
        players = self._calculate_player_war(players, pos_hists, sim_scores)

        return players

    def _add_game_factors(self, players: pd.DataFrame) -> pd.DataFrame:
        """Add game situation factors for current week projections."""
        logger.debug("Adding game factors...")

        # Merge with current week NFL schedule
        players = pd.merge(
            left=players,
            right=self.league.nfl_schedule.loc[
                (self.league.nfl_schedule.season == self.league.season)
                & (self.league.nfl_schedule.week == self.league.week),
                ["team", "elo_diff"],
            ],
            how="left",
            left_on="current_team",
            right_on="team",
        )

        players.elo_diff = players.elo_diff.fillna(0.0)

        # Merge weighting factors if not already present
        if "opp_elo_weight" not in players.columns:
            players = pd.merge(
                left=players,
                right=self.config.weighting_factors,
                how="left",
                on="position",
            )

        # Calculate factors
        players["opp_factor"] = players["opp_elo_weight"] * players["elo_diff"]
        players["string_factor"] = players["string_weight"] * (1 - players["string"])
        players["game_factor"] = (
            players["basal"] + players["opp_factor"] + players["string_factor"]
        )
        players["points_avg"] = players["points_rate"] * players["game_factor"]

        return players.drop(columns=["team", "elo_diff"], errors="ignore")

    def _load_stats_if_needed(self, start: int, finish: int):
        """Load game-by-game stats if not already loaded."""
        if self.stats is None:
            logger.info(f"Loading stats from {start} to {finish}...")
            self.stats = sr.get_bulk_stats(
                start // 100,
                start % 100,
                finish // 100,
                finish % 100,
                False,
                "GameByGameFantasyFootballStats.csv",
            )

            # Add fantasy points based on league scoring
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
        # This is your existing add_points logic
        offense = self.stats.loc[self.stats.position != "DEF"].reset_index(drop=True)

        offense["points"] = (
            offense["rush_yds"] * self.league.scoring["Rush Yds"]
            + offense["rush_att"] * self.league.scoring["Rush Att"]
            + offense["rush_td"] * self.league.scoring["Rush TD"]
            + offense["rush_first_down"] * self.league.scoring["Rush 1D"]
            + offense["rec"] * self.league.scoring["Rec"]
            + offense["rec_yds"] * self.league.scoring["Rec Yds"]
            + offense["rec_td"] * self.league.scoring["Rec TD"]
            + offense["rec_first_down"] * self.league.scoring["Rec 1D"]
            + offense["pass_yds"] * self.league.scoring["Pass Yds"]
            + offense["pass_cmp"] * self.league.scoring["Pass Comp"]
            + offense["pass_td"] * self.league.scoring["Pass TD"]
            + offense["pass_first_down"] * self.league.scoring["Pass 1D"]
            + offense["pass_int"] * self.league.scoring["Int Thrown"]
            + offense["fumbles_lost"] * self.league.scoring["Fum Lost"]
            + (offense["kick_ret_yds"] + offense["punt_ret_yds"])
            * self.league.scoring["Ret Yds"]
            + (offense["kick_ret_td"] + offense["punt_ret_td"])
            * self.league.scoring["Ret TD"]
            + offense["xpm"] * self.league.scoring["PAT Made"]
            + offense["fgm"] * self.league.scoring["FG 0-19"]
        )

        # Add TE bonuses
        tes = offense.position == "TE"
        offense.loc[tes, "points"] += (
            offense.loc[tes, "rec"] * self.league.scoring["TE Rec Bonus"]
            + (
                offense.loc[tes, "rush_first_down"]
                + offense.loc[tes, "rec_first_down"]
                + offense.loc[tes, "pass_first_down"]
            )
            * self.league.scoring["TE 1D Bonus"]
        )

        # Add yardage bonuses
        offense.loc[offense.pass_yds >= 300, "points"] += self.league.scoring[
            "Pass 300+"
        ]
        offense.loc[offense.rush_yds >= 100, "points"] += self.league.scoring[
            "Rush 100+"
        ]
        offense.loc[offense.rec_yds >= 100, "points"] += self.league.scoring["Rec 100+"]

        # Defense scoring
        defense = self.stats.loc[self.stats.position == "DEF"].reset_index(drop=True)
        defense["points"] = (
            defense["sacks"] * self.league.scoring["Sack"]
            + defense["def_int"] * self.league.scoring["Int"]
            + defense["fumbles_rec"] * self.league.scoring["Fum Rec"]
            + (
                defense["def_int_td"]
                + defense["fumbles_rec_td"]
                + defense["kick_ret_td"]
                + defense["punt_ret_td"]
            )
            * self.league.scoring["Ret TD"]
        )

        # Points allowed scoring
        defense.loc[defense.points_allowed == 0, "points"] += self.league.scoring[
            "Pts Allow 0"
        ]
        defense.loc[
            (defense.points_allowed >= 1) & (defense.points_allowed <= 6), "points"
        ] += self.league.scoring["Pts Allow 1-6"]
        defense.loc[
            (defense.points_allowed >= 7) & (defense.points_allowed <= 13), "points"
        ] += self.league.scoring["Pts Allow 7-13"]
        defense.loc[
            (defense.points_allowed >= 14) & (defense.points_allowed <= 20), "points"
        ] += self.league.scoring["Pts Allow 14-20"]
        defense.loc[
            (defense.points_allowed >= 21) & (defense.points_allowed <= 27), "points"
        ] += self.league.scoring["Pts Allow 21-27"]
        defense.loc[
            (defense.points_allowed >= 28) & (defense.points_allowed <= 34), "points"
        ] += self.league.scoring["Pts Allow 28-34"]
        defense.loc[(defense.points_allowed >= 35), "points"] += self.league.scoring[
            "Pts Allow 35+"
        ]

        self.stats = pd.concat([offense, defense], ignore_index=True, sort=False)

    def _apply_positional_averages(self, rel_stats: pd.DataFrame) -> pd.DataFrame:
        """Calculate positional averages for rate calculations."""
        by_pos = pd.merge(
            left=rel_stats.groupby("position")
            .rel_points.mean()
            .reset_index()
            .rename(index=str, columns={"rel_points": "points_rate"}),
            right=rel_stats.groupby("position")
            .rel_points.std()
            .reset_index()
            .rename(index=str, columns={"rel_points": "points_stdev"}),
            how="inner",
            on="position",
        )
        by_pos["player_id_sr"] = "avg_" + by_pos["position"]
        return by_pos

    def _apply_time_weighting(
        self, rel_stats: pd.DataFrame, as_of: int
    ) -> pd.DataFrame:
        """Apply time-based weighting to statistics."""
        rel_stats["weeks_ago"] = (
            17 * (as_of // 100 - rel_stats.season) + as_of % 100 - rel_stats.week
        )
        rel_stats["time_factor"] = 1 - rel_stats.weeks_ago * rel_stats.time_scale
        rel_stats = rel_stats.loc[rel_stats.time_factor > 0].reset_index(drop=True)

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
        return rel_stats

    def _calculate_player_rates(
        self, rel_stats: pd.DataFrame, by_pos: pd.DataFrame
    ) -> pd.DataFrame:
        """Calculate player-specific rates with positional priors."""
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

        by_player = pd.concat(
            [
                by_player,
                by_pos[["player_id_sr", "position", "points_rate", "points_stdev"]],
            ],
            ignore_index=True,
            sort=False,
        )

        by_player.points_stdev = by_player.points_stdev.fillna(0.0)

        by_player = pd.merge(
            left=by_player,
            right=by_pos[["position", "points_rate", "points_stdev"]].rename(
                columns={"points_rate": "pos_avg", "points_stdev": "pos_stdev"}
            ),
            how="inner",
            on="position",
        )

        # Apply reference games adjustment
        for pos in self.config.reference_games:
            by_player.loc[by_player.position == pos, "ref_games"] = (
                self.config.reference_games[pos]
            )

        inds = by_player.num_games < by_player.ref_games
        by_player.loc[inds, "points_squared"] = (
            by_player.loc[inds, "num_games"]
            * (
                by_player.loc[inds, "points_stdev"] ** 2
                + by_player.loc[inds, "points_rate"] ** 2
            )
            + (by_player.loc[inds, "ref_games"] - by_player.loc[inds, "num_games"])
            * (
                by_player.loc[inds, "pos_stdev"] ** 2
                + by_player.loc[inds, "pos_avg"] ** 2
            )
        ) / by_player.loc[inds, "ref_games"]

        by_player.loc[inds, "points_rate"] = (
            by_player.loc[inds, "num_games"] * by_player.loc[inds, "points_rate"]
            + (by_player.loc[inds, "ref_games"] - by_player.loc[inds, "num_games"])
            * by_player.loc[inds, "pos_avg"]
        ) / by_player.loc[inds, "ref_games"]

        by_player.loc[inds, "points_stdev"] = (
            (
                by_player.loc[inds, "points_squared"]
                - by_player.loc[inds, "points_rate"] ** 2
            )
            ** 0.5
        ).astype(float)

        return by_player

    def _simulate_average_team(self, pos_hists: dict, num_sims: int) -> pd.DataFrame:
        """Simulate performance of average replacement-level team."""
        sim_scores = pd.DataFrame(
            {
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
            }
        )
        sim_scores["Total"] = (
            sim_scores.QB
            + sim_scores.RB1
            + sim_scores.RB2
            + sim_scores.WR1
            + sim_scores.WR2
            + sim_scores.TE
            + sim_scores.FLEX
            + sim_scores.K
            + sim_scores.DEF
        )
        return sim_scores

    def _calculate_player_war(
        self, players: pd.DataFrame, pos_hists: dict, sim_scores: pd.DataFrame
    ) -> pd.DataFrame:
        """Calculate WAR for each player."""
        player_sims = pd.DataFrame(
            {
                players.loc[ind, "name"]: np.round(
                    np.random.normal(
                        loc=players.loc[ind, "points_rate"],
                        scale=players.loc[ind, "points_stdev"],
                        size=sim_scores.shape[0],
                    )
                )
                for ind in range(players.shape[0])
            }
        )

        sim_scores = pd.merge(
            left=sim_scores, right=player_sims, left_index=True, right_index=True
        )

        # Calculate WAR for each player
        for player in sim_scores.columns[10:]:
            if pd.isnull(player):
                continue

            cols = sim_scores.columns[:9].tolist()
            pos = players.loc[players.name == player, "position"].values[0]
            if pos in ["RB", "WR"]:
                pos += "1"
            cols.pop(cols.index(pos))
            cols.append(player)
            sim_scores["Alt_Total"] = sim_scores[cols].sum(axis=1)

            war_value = (
                sum(
                    sim_scores.loc[: sim_scores.shape[0] // 2 - 1, "Alt_Total"].values
                    > sim_scores.loc[sim_scores.shape[0] // 2 :, "Total"].values
                )
                / (sim_scores.shape[0] // 2)
                - 0.5
            ) * 14

            players.loc[players.name == player, "WAR"] = war_value
            del sim_scores["Alt_Total"]

        return players
