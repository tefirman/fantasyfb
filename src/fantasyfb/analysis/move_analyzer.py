"""
Fantasy football roster move analysis.

This module analyzes the impact of potential roster moves including
pickups, adds, drops, and trades on team performance.
"""

import datetime
import pandas as pd


class MoveAnalyzer:
    """
    Analyzes the impact of potential roster moves on team performance.
    """
    
    def __init__(self, league):
        """
        Initialize the move analyzer.
        
        Args:
            league: League instance with all the data and simulation methods
        """
        self.league = league
    
    def possible_pickups(
        self,
        focus_on: list = [],
        exclude: list = [],
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list = [800, 300, 100],
        bestball: bool = False,
        min_rostership: float = 0.05,
    ):
        """
        Simulates the remainder of the season with the current roster and compares it to 
        a simulation of the roster after a series of potential add & drop transactions.

        Args:
            focus_on (list, optional): list of players to include in every potential trade, defaults to [].  
            exclude (list, optional): list of players to exclude from every potential trade, defaults to [].  
            limit_per (int, optional): number of players per position to analyze, defaults to 10.  
            team_name (str, optional): name of team to analyze trades for, defaults to None (and therefore team of interest).  
            postseason (bool, optional): whether to analyze postseason gains or just regular season, defaults to True.  
            verbose (bool, optional): whether to print out a status report as the code runs, defaults to True.  
            payouts (list, optional): list of payout amounts for top three finishers, defaults to [800, 300, 100].  
            bestball (bool, optional): whether to use best ball settings during simulation, defaults to False.

        Returns:
            pd.DataFrame: dataframe containing the impact and value of every add & drop combination analyzed.
        """
        as_of = self.league.season * 100 + self.league.week
        self.league.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.league.bestball_sims(payouts)
        else:
            orig_standings = self.league.season_sims(postseason, payouts)[1]
        base_cols = [
            "player_to_drop",
            "player_to_add",
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "per_game_avg",
            "per_game_stdev",
            "per_game_fano",
            "playoffs",
            "playoff_bye",
        ] + (
            ["winner", "runner_up", "third", "earnings"]
            if postseason
            else []
        )
        rows = []
        if not team_name:
            team_name = [
                team["name"]
                for team in self.league.teams
                if team["team_key"] == self.league.lg.team_key()
            ][0]
        players_to_drop = self.league.players.loc[self.league.players.fantasy_team == team_name]
        if players_to_drop.name.isin(focus_on).sum() > 0:
            players_to_drop = players_to_drop.loc[players_to_drop.name.isin(focus_on)]
        if players_to_drop.name.isin(exclude).sum() > 0:
            players_to_drop = players_to_drop.loc[~players_to_drop.name.isin(exclude)]
        available = self.league.players.loc[self.league.players.fantasy_team.isnull() \
        & (self.league.players.until.isnull() | (self.league.players.until < 17)) \
        & (self.league.players.pct_rostered >= min_rostership)].reset_index(drop=True)
        for my_player in players_to_drop.name:
            self.league.yahoo_client.refresh_oauth(55)
            if (
                players_to_drop.loc[players_to_drop.name == my_player, "until"].values[
                    0
                ]
                >= as_of % 100
            ):
                possible = available.loc[~available.name.str.contains("Average_")]
            else:
                possible = available.loc[
                    ~available.name.str.contains("Average_")
                    & (
                        available.WAR
                        >= self.league.players.loc[
                            self.league.players.name == my_player, "WAR"
                        ].values[0]
                        - 0.5
                    )
                ]
            if available.name.isin(focus_on).sum() > 0:
                possible = possible.loc[possible.name.isin(focus_on)]
            if possible.name.isin(exclude).sum() > 0:
                possible = possible.loc[~possible.name.isin(exclude)]
            if verbose:
                print(my_player + ": " + str(possible.shape[0]) + " better players")
                print(datetime.datetime.now())
            possible = possible.groupby("position").head(limit_per)
            batch_start = len(rows)
            for free_agent in possible.name:
                self.league.players.loc[self.league.players.name == my_player, "fantasy_team"] = None
                self.league.players.loc[
                    self.league.players.name == free_agent, "fantasy_team"
                ] = team_name
                if bestball:
                    new_standings = self.league.bestball_sims(payouts)
                else:
                    new_standings = self.league.season_sims(postseason, payouts)[1]
                row = new_standings.loc[new_standings.team == team_name].copy()
                row["player_to_drop"] = my_player
                row["player_to_add"] = free_agent
                rows.append(row)
                self.league.players.loc[
                    self.league.players.name == my_player, "fantasy_team"
                ] = team_name
                self.league.players.loc[self.league.players.name == free_agent, "fantasy_team"] = None
            if verbose:
                batch = rows[batch_start:]
                if batch:
                    temp = pd.concat(batch, ignore_index=True)[
                        ["player_to_drop", "player_to_add", "earnings"]
                    ]
                    temp["earnings"] -= orig_standings.loc[
                        orig_standings.team == team_name, "earnings"
                    ].values[0]
                    print(
                        temp.sort_values(by="earnings", ascending=False).to_string(
                            index=False
                        )
                    )
                    del temp
        if rows:
            added_value = pd.concat(rows, ignore_index=True)
            extra_cols = [c for c in added_value.columns if c not in base_cols]
            added_value = added_value.reindex(columns=base_cols + extra_cols)
        else:
            added_value = pd.DataFrame(columns=base_cols)
        if added_value.shape[0] > 0:
            for col in [
                "wins_avg",
                "wins_stdev",
                "points_avg",
                "points_stdev",
                "playoffs",
                "playoff_bye",
            ] + (
                ["winner", "runner_up", "third", "earnings"]
                if postseason
                else []
            ):
                added_value[col] -= orig_standings.loc[
                    orig_standings.team == team_name, col
                ].values[0]
                added_value[col] = round(added_value[col], 4)
            added_value = added_value.sort_values(
                by="winner" if postseason else "playoffs", ascending=False
            )
        return added_value

    def possible_adds(
        self,
        focus_on: list = [],
        exclude: list = [],
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list = [800, 300, 100],
        bestball: bool = False,
        min_rostership: float = 0.05,
    ):
        """
        Simulates the remainder of the season with the current roster and compares it to 
        a simulation of the roster after a series of potential add transactions.

        Args:
            focus_on (list, optional): list of players to include in every potential trade, defaults to [].  
            exclude (list, optional): list of players to exclude from every potential trade, defaults to [].  
            limit_per (int, optional): number of players per position to analyze, defaults to 10.  
            team_name (str, optional): name of team to analyze trades for, defaults to None (and therefore team of interest).  
            postseason (bool, optional): whether to analyze postseason gains or just regular season, defaults to True.  
            verbose (bool, optional): whether to print out a status report as the code runs, defaults to True.  
            payouts (list, optional): list of payout amounts for top three finishers, defaults to [800, 300, 100].  
            bestball (bool, optional): whether to use best ball settings during simulation, defaults to False.

        Returns:
            pd.DataFrame: dataframe containing the impact and value of every possible add analyzed.
        """
        as_of = self.league.season * 100 + self.league.week
        self.league.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.league.bestball_sims(payouts)
        else:
            orig_standings = self.league.season_sims(postseason, payouts)[1]
        base_cols = [
            "player_to_add",
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "per_game_avg",
            "per_game_stdev",
            "per_game_fano",
            "playoffs",
            "playoff_bye",
        ] + (
            ["winner", "runner_up", "third", "earnings"]
            if postseason
            else []
        )
        rows = []
        if not team_name:
            team_name = [
                team["name"]
                for team in self.league.teams
                if team["team_key"] == self.league.lg.team_key()
            ][0]
        available = self.league.players.loc[self.league.players.fantasy_team.isnull() \
        & (self.league.players.until.isnull() | (self.league.players.until < 17)) \
        & (self.league.players.pct_rostered >= min_rostership)].reset_index(drop=True)
        possible = available.loc[~available.name.str.contains("Average_")]
        if possible.name.isin(focus_on).sum() > 0:
            possible = possible.loc[possible.name.isin(focus_on)]
        if possible.name.isin(exclude).sum() > 0:
            possible = possible.loc[~possible.name.isin(exclude)]
        possible = possible.groupby("position").head(limit_per)
        for free_agent in possible.name:
            if verbose:
                print("{}, {}".format(free_agent, datetime.datetime.now()))
            self.league.players.loc[
                self.league.players.name == free_agent, "fantasy_team"
            ] = team_name
            if bestball:
                new_standings = self.league.bestball_sims(payouts)
            else:
                new_standings = self.league.season_sims(postseason, payouts)[1]
            row = new_standings.loc[new_standings.team == team_name].copy()
            row["player_to_add"] = free_agent
            row["position"] = possible.loc[
                possible.name == free_agent, "position"
            ].values[0]
            row["current_team"] = possible.loc[
                possible.name == free_agent, "current_team"
            ].values[0]
            rows.append(row)
            self.league.players.loc[self.league.players.name == free_agent, "fantasy_team"] = None
        if rows:
            added_value = pd.concat(rows, ignore_index=True)
            extra_cols = [c for c in added_value.columns if c not in base_cols]
            added_value = added_value.reindex(columns=base_cols + extra_cols)
        else:
            added_value = pd.DataFrame(columns=base_cols)
        if added_value.shape[0] > 0:
            for col in [
                "wins_avg",
                "wins_stdev",
                "points_avg",
                "points_stdev",
                "playoffs",
                "playoff_bye",
            ] + (
                ["winner", "runner_up", "third", "earnings"]
                if postseason
                else []
            ):
                added_value[col] -= orig_standings.loc[
                    orig_standings.team == team_name, col
                ].values[0]
                added_value[col] = round(added_value[col], 4)
            added_value = added_value.sort_values(
                by="winner" if postseason else "playoffs", ascending=False
            )
            if verbose:
                print(
                    added_value[["player_to_add", "earnings"]]
                    .sort_values(by="earnings", ascending=False)
                    .to_string(index=False)
                )
        return added_value
    
    def possible_drops(
        self,
        focus_on: list = [],
        exclude: list = [],
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list = [800, 300, 100],
        bestball: bool = False,
    ):
        """
        Simulates the remainder of the season with the current roster and compares it to 
        a simulation of the roster after a series of potential drop transactions.

        Args:
            focus_on (list, optional): list of players to include in every potential trade, defaults to [].  
            exclude (list, optional): list of players to exclude from every potential trade, defaults to [].  
            team_name (str, optional): name of team to analyze trades for, defaults to None (and therefore team of interest).  
            postseason (bool, optional): whether to analyze postseason gains or just regular season, defaults to True.  
            verbose (bool, optional): whether to print out a status report as the code runs, defaults to True.  
            payouts (list, optional): list of payout amounts for top three finishers, defaults to [800, 300, 100].  
            bestball (bool, optional): whether to use best ball settings during simulation, defaults to False.

        Returns:
            pd.DataFrame: dataframe containing the impact and value of every possible drop analyzed.
        """
        self.league.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.league.bestball_sims(payouts)
        else:
            orig_standings = self.league.season_sims(postseason, payouts)[1]
        base_cols = [
            "player_to_drop",
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "per_game_avg",
            "per_game_stdev",
            "per_game_fano",
            "playoffs",
            "playoff_bye",
        ] + (
            ["winner", "runner_up", "third", "earnings"]
            if postseason
            else []
        )
        rows = []
        if not team_name:
            team_name = [
                team["name"]
                for team in self.league.teams
                if team["team_key"] == self.league.lg.team_key()
            ][0]
        players_to_drop = self.league.players.loc[self.league.players.fantasy_team == team_name]
        if players_to_drop.name.isin(focus_on).sum() > 0:
            players_to_drop = players_to_drop.loc[players_to_drop.name.isin(focus_on)]
        if players_to_drop.name.isin(exclude).sum() > 0:
            players_to_drop = players_to_drop.loc[~players_to_drop.name.isin(exclude)]
        for my_player in players_to_drop.name:
            self.league.players.loc[self.league.players.name == my_player, "fantasy_team"] = None
            if bestball:
                new_standings = self.league.bestball_sims(payouts)
            else:
                new_standings = self.league.season_sims(postseason, payouts)[1]
            row = new_standings.loc[new_standings.team == team_name].copy()
            row["player_to_drop"] = my_player
            rows.append(row)
            self.league.players.loc[self.league.players.name == my_player, "fantasy_team"] = team_name
        if rows:
            reduced_value = pd.concat(rows, ignore_index=True)
            extra_cols = [c for c in reduced_value.columns if c not in base_cols]
            reduced_value = reduced_value.reindex(columns=base_cols + extra_cols)
        else:
            reduced_value = pd.DataFrame(columns=base_cols)
        if reduced_value.shape[0] > 0:
            for col in [
                "wins_avg",
                "wins_stdev",
                "points_avg",
                "points_stdev",
                "playoffs",
                "playoff_bye",
            ] + (
                ["winner", "runner_up", "third", "earnings"]
                if postseason
                else []
            ):
                reduced_value[col] -= orig_standings.loc[
                    orig_standings.team == team_name, col
                ].values[0]
                reduced_value[col] = round(reduced_value[col], 4)
            reduced_value = reduced_value.sort_values(
                by="winner" if postseason else "playoffs", ascending=False
            )
            if verbose:
                print(
                    reduced_value[["player_to_drop", "earnings"]]
                    .sort_values(by="earnings", ascending=False)
                    .to_string(index=False)
                )
        return reduced_value
    
    def possible_trades(
        self,
        focus_on: list = [],
        exclude: list = [],
        given: list = [],
        limit_per: int = 10,
        team_name: str = None,
        postseason: bool = True,
        verbose: bool = True,
        payouts: list = [800, 300, 100],
        bestball: bool = False,
    ):
        """
        Simulates the remainder of the season with the current roster and compares it to 
        a simulation of the roster after a series of potential trade transactions.

        Args:
            focus_on (list, optional): list of players to include in every potential trade, defaults to [].  
            exclude (list, optional): list of players to exclude from every potential trade, defaults to [].  
            given (list, optional): list of players to include in the trade in the background, defaults to [].  
            limit_per (int, optional): number of players per position to analyze, defaults to 10.  
            team_name (str, optional): name of team to analyze trades for, defaults to None (and therefore team of interest).  
            postseason (bool, optional): whether to analyze postseason gains or just regular season, defaults to True.  
            verbose (bool, optional): whether to print out a status report as the code runs, defaults to True.  
            payouts (list, optional): list of payout amounts for top three finishers, defaults to [800, 300, 100].  
            bestball (bool, optional): whether to use best ball settings during simulation, defaults to False.

        Returns:
            pd.DataFrame: dataframe containing the impact and value of every possible trade analyzed.
        """
        self.league.yahoo_client.refresh_oauth()
        if not team_name:
            team_name = [
                team["name"]
                for team in self.league.teams
                if team["team_key"] == self.league.lg.team_key()
            ][0]
        my_players = self.league.players.loc[
            (self.league.players.fantasy_team == team_name)
            & ~self.league.players.position.isin(["K", "DEF"])
        ]
        if my_players.name.isin(focus_on).sum() > 0:
            my_players = my_players.loc[my_players.name.isin(focus_on)]
        if my_players.name.isin(exclude).sum() > 0:
            my_players = my_players.loc[~my_players.name.isin(exclude)]
        their_players = self.league.players.loc[
            (self.league.players.fantasy_team != team_name)
            & ~self.league.players.position.isin(["K", "DEF"])
        ]
        if their_players.name.isin(focus_on).sum() > 0:
            their_players = their_players.loc[their_players.name.isin(focus_on)]
        if their_players.name.isin(exclude).sum() > 0:
            their_players = their_players.loc[~their_players.name.isin(exclude)]
        if bestball:
            orig_standings = self.league.bestball_sims(payouts)
        else:
            orig_standings = self.league.season_sims(postseason, payouts)[1]

        # Make sure there are two teams and narrow down to that team!!!
        given_check = (
            type(given) == list
            and my_players.name.isin(given).any()
            and their_players.loc[their_players.name.isin(given), "fantasy_team"]
            .unique()
            .shape[0]
            == 1
        )
        if given_check:
            mine = [player for player in given if my_players.name.isin([player]).any()]
            theirs = [
                player for player in given if their_players.name.isin([player]).any()
            ]
            their_team = self.league.players.loc[
                self.league.players.name.isin(theirs), "fantasy_team"
            ].values[0]
            self.league.players.loc[self.league.players.name.isin(mine), "fantasy_team"] = their_team
            self.league.players.loc[self.league.players.name.isin(theirs), "fantasy_team"] = team_name
            my_players = my_players.loc[~my_players.name.isin(given)]
            their_players = their_players.loc[
                (their_players.fantasy_team == their_team)
                & ~their_players.name.isin(given)
            ]
            my_players["WAR"] = 0.0
            their_players["WAR"] = 0.0
        # Make sure there are two teams and narrow down to that teams!!!

        my_rows = []
        their_rows = []
        for my_player in my_players.name:
            self.league.yahoo_client.refresh_oauth(55)
            if their_players.name.isin(focus_on).any():
                possible = their_players.copy()
            else:
                possible = their_players.loc[
                    abs(
                        their_players.WAR
                        - my_players.loc[my_players.name == my_player, "WAR"].values[0]
                    )
                    <= 0.5
                ]
            # possible = their_players.loc[their_players.WAR - my_players.loc[my_players.name == my_player,'WAR'].values[0] > -1.0]
            if verbose:
                print(my_player + ": " + str(possible.shape[0]) + " comparable players")
                print(datetime.datetime.now())
            possible = possible.groupby("position").head(limit_per)
            batch_start = len(my_rows)
            for their_player in possible.name:
                their_team = self.league.players.loc[
                    self.league.players.name == their_player, "fantasy_team"
                ].values[0]
                self.league.players.loc[
                    self.league.players.name == my_player, "fantasy_team"
                ] = their_team
                self.league.players.loc[
                    self.league.players.name == their_player, "fantasy_team"
                ] = team_name
                if bestball:
                    new_standings = self.league.bestball_sims(payouts)
                else:
                    new_standings = self.league.season_sims(postseason, payouts)[1]
                self.league.players.loc[
                    self.league.players.name == my_player, "fantasy_team"
                ] = team_name
                self.league.players.loc[
                    self.league.players.name == their_player, "fantasy_team"
                ] = their_team
                new_standings["player_to_trade_away"] = my_player
                new_standings["player_to_trade_for"] = their_player
                my_rows.append(new_standings.loc[new_standings.team == team_name].copy())
                their_rows.append(new_standings.loc[new_standings.team == their_team].copy())
            if verbose and possible.shape[0] > 0:
                me = pd.concat(my_rows[batch_start:], ignore_index=True)[
                    ["player_to_trade_away", "player_to_trade_for", "earnings"]
                ].rename(columns={"earnings": "my_earnings"})
                them = pd.concat(their_rows[batch_start:], ignore_index=True)[
                    ["player_to_trade_away", "player_to_trade_for", "team", "earnings"]
                ].rename(columns={"earnings": "their_earnings"})
                me["my_earnings"] -= orig_standings.loc[
                    orig_standings.team == team_name, "earnings"
                ].values[0]
                for their_team in them.team.unique():
                    them.loc[
                        them.team == their_team, "their_earnings"
                    ] -= orig_standings.loc[
                        orig_standings.team == their_team, "earnings"
                    ].values[
                        0
                    ]
                temp = pd.merge(
                    left=me,
                    right=them,
                    how="inner",
                    on=["player_to_trade_away", "player_to_trade_for"],
                )
                if temp.shape[0] > 0:
                    print(
                        temp.sort_values(by="my_earnings", ascending=False).to_string(
                            index=False
                        )
                    )
                del me, them, temp, their_team

        my_added_value = pd.concat(my_rows, ignore_index=True) if my_rows else pd.DataFrame()
        their_added_value = pd.concat(their_rows, ignore_index=True) if their_rows else pd.DataFrame()

        if given_check:
            mine = [player for player in given if my_players.name.isin([player]).any()]
            theirs = [
                player for player in given if their_players.name.isin([player]).any()
            ]
            their_team = self.league.players.loc[
                self.league.players.name.isin(theirs), "fantasy_team"
            ].values[0]
            self.league.players.loc[self.league.players.name.isin(mine), "fantasy_team"] = their_team
            self.league.players.loc[self.league.players.name.isin(theirs), "fantasy_team"] = team_name

        for col in [
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "per_game_avg",
            "per_game_stdev",
            "per_game_fano",
            "playoffs",
            "playoff_bye",
        ] + (["winner", "runner_up", "third", "earnings"] if postseason else []):
            my_added_value[col] -= orig_standings.loc[
                orig_standings.team == team_name, col
            ].values[0]
            my_added_value[col] = round(my_added_value[col], 4)
        for their_team in their_added_value.team.unique():
            for col in [
                "wins_avg",
                "wins_stdev",
                "points_avg",
                "points_stdev",
                "per_game_avg",
                "per_game_stdev",
                "per_game_fano",
                "playoffs",
                "playoff_bye",
            ] + (["winner", "runner_up", "third", "earnings"] if postseason else []):
                their_added_value.loc[
                    their_added_value.team == their_team, col
                ] -= orig_standings.loc[orig_standings.team == their_team, col].values[
                    0
                ]
                their_added_value[col] = round(their_added_value[col], 4)
        for col in [
            "team",
            "wins_avg",
            "wins_stdev",
            "points_avg",
            "points_stdev",
            "per_game_avg",
            "per_game_stdev",
            "per_game_fano",
            "playoffs",
            "playoff_bye",
        ] + (["winner", "runner_up", "third", "earnings"] if postseason else []):
            my_added_value = my_added_value.rename(
                index=str, columns={col: "my_" + col}
            )
            their_added_value = their_added_value.rename(
                index=str, columns={col: "their_" + col}
            )
        added_value = pd.merge(
            left=my_added_value,
            right=their_added_value,
            how="inner",
            on=["player_to_trade_away", "player_to_trade_for"],
        )
        added_value = added_value.sort_values(
            by="my_winner" if postseason else "playoffs", ascending=False
        )
        return added_value
