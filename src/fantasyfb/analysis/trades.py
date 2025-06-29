# fantasyfb/analysis/trades.py
"""
Trade Analyzer - handles analysis of potential roster moves.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TradeAnalyzer:
    """
    Handles analysis of potential roster moves including:
    - Free agent additions
    - Player drops
    - Trades between teams
    - Add/drop combinations
    """

    def __init__(self, league, simulator):
        """
        Initialize TradeAnalyzer.

        Args:
            league: Parent League object
            simulator: SeasonSimulator instance for running scenarios
        """
        self.league = league
        self.simulator = simulator

    def possible_adds(
        self,
        focus_on: list[str] = None,
        exclude: list[str] = None,
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list[float] = None,
        bestball: bool = False,
        min_rostership: float = 0.05,
    ) -> pd.DataFrame:
        """
        Analyze potential free agent additions.

        Args:
            focus_on: Specific players to analyze
            exclude: Players to exclude from analysis
            limit_per: Max players per position to analyze
            team_name: Team to analyze for (defaults to user's team)
            postseason: Include playoff impact
            verbose: Print progress updates
            payouts: Prize structure
            bestball: Use best ball scoring
            min_rostership: Minimum roster percentage threshold

        Returns:
            DataFrame with analysis results
        """
        logger.info("Analyzing potential free agent additions...")

        if bestball:
            orig_standings = self.simulator.bestball_sims(
                payouts or self.league.config.default_payouts
            )
        else:
            _, orig_standings = self.simulator.season_sims(
                postseason, payouts or self.league.config.default_payouts
            )

        added_value = pd.DataFrame(columns=self._get_result_columns(postseason))

        if not team_name:
            team_name = self.league.get_team_name()

        # Get available players
        players = self.league.load_players()
        available = players.loc[
            players.fantasy_team.isnull()
            & (players.until.isnull() | (players.until < 17))
            & (players.pct_rostered >= min_rostership)
        ].reset_index(drop=True)

        # Filter available players
        possible = available.loc[~available.name.str.contains("Average_")]

        if focus_on:
            possible = possible.loc[possible.name.isin(focus_on)]

        if exclude:
            possible = possible.loc[~possible.name.isin(exclude)]

        possible = possible.groupby("position").head(limit_per)

        # Analyze each potential addition
        for _, player in possible.iterrows():
            if verbose:
                logger.info(f"Analyzing: {player['name']}")

            # Temporarily add player to team
            original_team = players.loc[
                players.name == player["name"], "fantasy_team"
            ].iloc[0]
            players.loc[players.name == player["name"], "fantasy_team"] = team_name

            # Run simulation with the addition
            if bestball:
                new_standings = self.simulator.bestball_sims(
                    payouts or self.league.config.default_payouts
                )
            else:
                _, new_standings = self.simulator.season_sims(
                    postseason, payouts or self.league.config.default_payouts
                )

            # Calculate impact
            impact = self._calculate_impact(orig_standings, new_standings, team_name)
            impact["player_to_add"] = player["name"]
            impact["position"] = player["position"]
            impact["current_team"] = player["current_team"]

            added_value = pd.concat(
                [added_value, pd.DataFrame([impact])], ignore_index=True
            )

            # Restore original state
            players.loc[players.name == player["name"], "fantasy_team"] = original_team

        # Sort by impact
        sort_col = "winner" if postseason else "playoffs"
        added_value = added_value.sort_values(by=sort_col, ascending=False)

        if verbose and len(added_value) > 0:
            top_adds = added_value[["player_to_add", "earnings"]].head()
            logger.info(f"Top additions:\n{top_adds.to_string(index=False)}")

        return added_value

    def possible_drops(
        self,
        focus_on: list[str] = None,
        exclude: list[str] = None,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list[float] = None,
        bestball: bool = False,
    ) -> pd.DataFrame:
        """
        Analyze potential player drops.

        Args:
            focus_on: Specific players to analyze
            exclude: Players to exclude
            team_name: Team to analyze
            postseason: Include playoff impact
            verbose: Print progress
            payouts: Prize structure
            bestball: Use best ball scoring

        Returns:
            DataFrame with drop analysis results
        """
        logger.info("Analyzing potential drops...")

        if bestball:
            orig_standings = self.simulator.bestball_sims(
                payouts or self.league.config.default_payouts
            )
        else:
            _, orig_standings = self.simulator.season_sims(
                postseason, payouts or self.league.config.default_payouts
            )

        reduced_value = pd.DataFrame(columns=self._get_result_columns(postseason))

        if not team_name:
            team_name = self.league.get_team_name()

        # Get current roster
        players = self.league.load_players()
        my_players = players.loc[players.fantasy_team == team_name]

        if focus_on:
            my_players = my_players.loc[my_players.name.isin(focus_on)]

        if exclude:
            my_players = my_players.loc[~my_players.name.isin(exclude)]

        # Analyze each potential drop
        for _, player in my_players.iterrows():
            if verbose:
                logger.info(f"Analyzing drop: {player['name']}")

            # Temporarily remove player
            players.loc[players.name == player["name"], "fantasy_team"] = None

            # Run simulation without the player
            if bestball:
                new_standings = self.simulator.bestball_sims(
                    payouts or self.league.config.default_payouts
                )
            else:
                _, new_standings = self.simulator.season_sims(
                    postseason, payouts or self.league.config.default_payouts
                )

            # Calculate impact (negative impact = loss from dropping)
            impact = self._calculate_impact(orig_standings, new_standings, team_name)
            impact["player_to_drop"] = player["name"]

            reduced_value = pd.concat(
                [reduced_value, pd.DataFrame([impact])], ignore_index=True
            )

            # Restore player
            players.loc[players.name == player["name"], "fantasy_team"] = team_name

        # Sort by impact (ascending since we want to see least impactful drops first)
        sort_col = "winner" if postseason else "playoffs"
        reduced_value = reduced_value.sort_values(by=sort_col, ascending=True)

        return reduced_value

    def possible_trades(
        self,
        focus_on: list[str] = None,
        exclude: list[str] = None,
        given: list[str] = None,
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list[float] = None,
        bestball: bool = False,
    ) -> pd.DataFrame:
        """
        Analyze potential trades.

        Args:
            focus_on: Specific players to include
            exclude: Players to exclude
            given: Players to include in background of trade
            limit_per: Max players per position
            team_name: Team to analyze
            postseason: Include playoff impact
            verbose: Print progress
            payouts: Prize structure
            bestball: Use best ball scoring

        Returns:
            DataFrame with trade analysis results
        """
        logger.info("Analyzing potential trades...")

        if bestball:
            orig_standings = self.simulator.bestball_sims(
                payouts or self.league.config.default_payouts
            )
        else:
            _, orig_standings = self.simulator.season_sims(
                postseason, payouts or self.league.config.default_payouts
            )

        if not team_name:
            team_name = self.league.get_team_name()

        players = self.league.load_players()

        # Get tradeable players
        my_players = players.loc[
            (players.fantasy_team == team_name) & ~players.position.isin(["K", "DEF"])
        ]

        their_players = players.loc[
            (players.fantasy_team != team_name) & ~players.position.isin(["K", "DEF"])
        ]

        # Apply filters
        if focus_on:
            my_players = my_players.loc[my_players.name.isin(focus_on)]
            their_players = their_players.loc[their_players.name.isin(focus_on)]

        if exclude:
            my_players = my_players.loc[~my_players.name.isin(exclude)]
            their_players = their_players.loc[~their_players.name.isin(exclude)]

        # Handle given players (background trade)
        if given:
            mine_given = [p for p in given if p in my_players.name.values]
            theirs_given = [p for p in given if p in their_players.name.values]

            if mine_given and theirs_given:
                # Execute background trade
                their_team = players.loc[
                    players.name.isin(theirs_given), "fantasy_team"
                ].iloc[0]

                players.loc[players.name.isin(mine_given), "fantasy_team"] = their_team
                players.loc[players.name.isin(theirs_given), "fantasy_team"] = team_name

                # Remove given players from analysis
                my_players = my_players.loc[~my_players.name.isin(given)]
                their_players = their_players.loc[
                    (their_players.fantasy_team == their_team)
                    & ~their_players.name.isin(given)
                ]

        trade_results = []

        # Analyze trades
        for _, my_player in my_players.head(20).iterrows():  # Limit for performance
            if verbose:
                logger.info(f"Analyzing trades for: {my_player['name']}")

            # Find comparable players
            comparable = (
                their_players.loc[abs(their_players.WAR - my_player["WAR"]) <= 0.5]
                .groupby("position")
                .head(limit_per)
            )

            for _, their_player in comparable.iterrows():
                # Execute trade
                their_team = their_player["fantasy_team"]

                players.loc[players.name == my_player["name"], "fantasy_team"] = (
                    their_team
                )
                players.loc[players.name == their_player["name"], "fantasy_team"] = (
                    team_name
                )

                # Simulate results
                if bestball:
                    new_standings = self.simulator.bestball_sims(
                        payouts or self.league.config.default_payouts
                    )
                else:
                    _, new_standings = self.simulator.season_sims(
                        postseason, payouts or self.league.config.default_payouts
                    )

                # Calculate impact for both teams
                my_impact = self._calculate_impact(
                    orig_standings, new_standings, team_name
                )
                their_impact = self._calculate_impact(
                    orig_standings, new_standings, their_team
                )

                # Combine results
                trade_result = {
                    "player_to_trade_away": my_player["name"],
                    "player_to_trade_for": their_player["name"],
                    "their_team": their_team,
                }

                # Add my impact with prefix
                for key, value in my_impact.items():
                    trade_result[f"my_{key}"] = value

                # Add their impact with prefix
                for key, value in their_impact.items():
                    trade_result[f"their_{key}"] = value

                trade_results.append(trade_result)

                # Reverse trade
                players.loc[players.name == my_player["name"], "fantasy_team"] = (
                    team_name
                )
                players.loc[players.name == their_player["name"], "fantasy_team"] = (
                    their_team
                )

        trade_df = pd.DataFrame(trade_results)

        if len(trade_df) > 0:
            sort_col = "my_winner" if postseason else "my_playoffs"
            trade_df = trade_df.sort_values(by=sort_col, ascending=False)

        return trade_df

    def possible_pickups(
        self,
        focus_on: list[str] = None,
        exclude: list[str] = None,
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list[float] = None,
        bestball: bool = False,
        min_rostership: float = 0.05,
    ) -> pd.DataFrame:
        """
        Analyze add/drop combinations.

        Args:
            focus_on: Specific players to analyze
            exclude: Players to exclude
            limit_per: Max players per position
            team_name: Team to analyze
            postseason: Include playoff impact
            verbose: Print progress
            payouts: Prize structure
            bestball: Use best ball scoring
            min_rostership: Minimum roster percentage

        Returns:
            DataFrame with pickup analysis results
        """
        logger.info("Analyzing potential pickups (add/drop combinations)...")

        if bestball:
            orig_standings = self.simulator.bestball_sims(
                payouts or self.league.config.default_payouts
            )
        else:
            _, orig_standings = self.simulator.season_sims(
                postseason, payouts or self.league.config.default_payouts
            )

        pickup_results = []

        if not team_name:
            team_name = self.league.get_team_name()

        players = self.league.load_players()

        # Get droppable players
        my_players = players.loc[players.fantasy_team == team_name]
        if focus_on:
            my_players = my_players.loc[my_players.name.isin(focus_on)]
        if exclude:
            my_players = my_players.loc[~my_players.name.isin(exclude)]

        # Get available players
        available = players.loc[
            players.fantasy_team.isnull()
            & (players.until.isnull() | (players.until < 17))
            & (players.pct_rostered >= min_rostership)
        ]

        if focus_on:
            available = available.loc[available.name.isin(focus_on)]
        if exclude:
            available = available.loc[~available.name.isin(exclude)]

        available = available.groupby("position").head(limit_per)

        # Analyze each combination
        for _, drop_player in my_players.iterrows():
            if verbose:
                logger.info(f"Analyzing drops for: {drop_player['name']}")

            # Find suitable replacements
            suitable = available.loc[available.WAR >= drop_player["WAR"] - 0.5]

            for _, add_player in suitable.iterrows():
                # Execute pickup
                players.loc[players.name == drop_player["name"], "fantasy_team"] = None
                players.loc[players.name == add_player["name"], "fantasy_team"] = (
                    team_name
                )

                # Simulate
                if bestball:
                    new_standings = self.simulator.bestball_sims(
                        payouts or self.league.config.default_payouts
                    )
                else:
                    _, new_standings = self.simulator.season_sims(
                        postseason, payouts or self.league.config.default_payouts
                    )

                # Calculate impact
                impact = self._calculate_impact(
                    orig_standings, new_standings, team_name
                )
                impact["player_to_drop"] = drop_player["name"]
                impact["player_to_add"] = add_player["name"]

                pickup_results.append(impact)

                # Reverse pickup
                players.loc[players.name == drop_player["name"], "fantasy_team"] = (
                    team_name
                )
                players.loc[players.name == add_player["name"], "fantasy_team"] = None

        pickup_df = pd.DataFrame(pickup_results)

        if len(pickup_df) > 0:
            sort_col = "winner" if postseason else "playoffs"
            pickup_df = pickup_df.sort_values(by=sort_col, ascending=False)

        return pickup_df

    def _calculate_impact(
        self, orig_standings: pd.DataFrame, new_standings: pd.DataFrame, team_name: str
    ) -> dict:
        """Calculate the impact of a roster move."""
        orig_team = orig_standings.loc[orig_standings.team == team_name].iloc[0]
        new_team = new_standings.loc[new_standings.team == team_name].iloc[0]

        impact = {}
        for col in [
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "playoffs",
            "playoff_bye",
        ]:
            if col in orig_team.index and col in new_team.index:
                impact[col] = round(new_team[col] - orig_team[col], 4)

        # Handle postseason columns if they exist
        for col in ["winner", "runner_up", "third", "earnings"]:
            if col in orig_team.index and col in new_team.index:
                impact[col] = round(new_team[col] - orig_team[col], 4)

        return impact

    def _get_result_columns(self, postseason: bool) -> list[str]:
        """Get the appropriate result columns based on analysis type."""
        base_cols = [
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "playoffs",
            "playoff_bye",
        ]

        if postseason:
            base_cols.extend(["winner", "runner_up", "third", "earnings"])

        return base_cols
