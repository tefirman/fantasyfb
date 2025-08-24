"""
Lineup optimization for fantasy football teams.

This module handles setting optimal starting lineups based on projections,
roster constraints, injuries, and bye weeks.
"""

import datetime
import pandas as pd

class LineupOptimizer:
    """
    Handles optimal lineup selection for fantasy football teams.
    """

    def __init__(self, roster_spots, teams, yahoo_client):
        """
        Initialize the lineup optimizer.
        
        Args:
            roster_spots: DataFrame with roster position requirements
            teams: List of team dictionaries
            yahoo_client: YahooFantasyClient instance
        """
        self.roster_spots = roster_spots
        self.teams = teams
        self.yahoo_client = yahoo_client

    def set_optimal_lineup(self, players, week, season, current_week, latest_season, 
                        nfl_schedule, basaloppstringtime):
        """
        Identifies which players should be started on each fantasy team 
        based on fantasy point projections and available roster spots.

        Args:
            players: DataFrame with player data including projections
            week: Week for which to identify starters
            season: Current season
            current_week: The actual current week
            latest_season: Most recent NFL season
            nfl_schedule: NFL schedule with ELO data
            basaloppstringtime: Weighting factors DataFrame

        Returns:
            DataFrame with players marked as starters and injury/game factors added
        """
        as_of = season * 100 + week
        self.yahoo_client.refresh_oauth()
        
        # Add game context factors
        players = pd.merge(
            left=players,
            right=nfl_schedule.loc[
                (nfl_schedule.season == as_of // 100)
                & (nfl_schedule.week == week),
                ["team", "elo_diff"],
            ],
            how="left",
            left_on="current_team",
            right_on="team",
        )
        
        players.elo_diff = players.elo_diff.infer_objects(copy=False).fillna(0.0)
        
        # Add weighting factors if not present
        if "opp_elo_weight" not in players.columns:
            players = pd.merge(left=players, right=basaloppstringtime, how='left', on='position')
        
        # Calculate game factors
        players["opp_factor"] = (players['opp_elo_weight'] * players["elo_diff"])
        players["string_factor"] = players['string_weight'] * (1 - players["string"])
        players["game_factor"] = players['basal'] + players["opp_factor"] + players["string_factor"]
        players["points_avg"] = players["points_rate"] * players["game_factor"]
        
        # Clean up temporary columns
        if "team" in players.columns:
            del players["team"]
        if "elo_diff" in players.columns:
            del players["elo_diff"]
        
        # Sort by projected points
        players = players.sort_values(by="points_avg", ascending=False)
        
        # Initialize starter and injury flags
        players["starter"] = False
        players["injured"] = players.until >= week
        
        # Handle current week with completed games
        if (week == as_of % 100 and as_of // 100 == latest_season and 
            datetime.datetime.now().month > 8):
            players = self._handle_live_week_lineup(players, week, nfl_schedule, as_of)
        # Handle future weeks
        elif week >= as_of % 100:
            players = self._set_future_week_lineup(players, week)
        
        return players

    def _handle_live_week_lineup(self, players, week, nfl_schedule, as_of):
        """Handle lineup setting for the current week with some completed games."""
        # Determine completed games
        cutoff = datetime.datetime.now()
        if datetime.datetime.now().hour < 20:
            cutoff -= datetime.timedelta(days=1)
        
        completed = nfl_schedule.loc[
            (nfl_schedule.season == as_of // 100)
            & (nfl_schedule.week == week)
            & (nfl_schedule.date < cutoff),
            "team",
        ].tolist()
        
        # Set starters for each team
        for team in self.teams:
            # Get already started players
            started = players.loc[
                (players.selected_position != "BN")
                & (players.fantasy_team == team["name"])
                & players.current_team.isin(completed)
            ]
            
            # Get bench players from completed games
            not_available = players.loc[
                (players.selected_position == "BN")
                & (players.fantasy_team == team["name"])
                & players.current_team.isin(completed)
            ]
            
            # Calculate remaining roster needs
            lineup = pd.merge(
                left=self.roster_spots,
                right=started.groupby('selected_position').size()
                .to_frame('num_started').reset_index()
                .rename(columns={'selected_position':'position'}),
                how='left', on='position'
            )
            lineup['count'] -= lineup.num_started.fillna(0.0)
            
            # Set remaining position players
            players = self._fill_remaining_positions(
                players, team["name"], lineup, started, not_available, week
            )
        
        return players

    def _set_future_week_lineup(self, players, week):
        """Set optimal lineup for future weeks."""
        # Get position requirements (excluding flex and bench)
        num_pos = self.roster_spots.loc[
            ~self.roster_spots.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])
        ].set_index('position').to_dict()['count']
        
        # Fill standard positions
        for pos in num_pos:
            for num in range(num_pos[pos]):
                available_players = players.loc[
                    ~players.starter
                    & ~players.injured
                    & (players.bye_week != week)
                    & (players.position == pos)
                ].drop_duplicates(subset=["fantasy_team"], keep="first")
                
                players.loc[available_players.index, "starter"] = True
        
        # Fill flex positions
        flex_pos = {"W/T":['WR','TE'], "W/R/T":['WR','RB','TE'], "Q/W/R/T":['WR','RB','TE','QB']}
        for pos in flex_pos:
            num_flex = self.roster_spots.loc[self.roster_spots.position == pos, 'count'].sum()
            for flex in range(num_flex):
                available_players = players.loc[
                    ~players.starter
                    & ~players.injured
                    & (players.bye_week != week)
                    & players.position.isin(flex_pos[pos])
                ].drop_duplicates(subset=["fantasy_team"], keep="first")
                
                players.loc[available_players.index, "starter"] = True
        
        return players

    def _fill_remaining_positions(self, players, team_name, lineup, started, not_available, week):
        """Fill remaining roster positions for a specific team."""
        num_pos = lineup.loc[
            ~lineup.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])
        ].set_index('position').to_dict()['count']
        
        # Fill standard positions
        for pos in num_pos:
            for num in range(int(num_pos[pos])):
                available_players = players.loc[
                    (players.fantasy_team == team_name)
                    & ~players.starter
                    & ~players.injured
                    & (players.bye_week != week)
                    & (players.position == pos)
                    & ~players.player_id.isin(started.player_id)
                    & ~players.player_id.isin(not_available.player_id)
                ].iloc[:1]
                
                players.loc[available_players.index, "starter"] = True
        
        # Fill flex positions
        flex_pos = {"W/T":['WR','TE'], "W/R/T":['WR','RB','TE'], "Q/W/R/T":['WR','RB','TE','QB']}
        for pos in flex_pos:
            num_flex = int(lineup.loc[lineup.position == pos, 'count'].sum())
            for flex in range(num_flex):
                available_players = players.loc[
                    (players.fantasy_team == team_name)
                    & ~players.starter
                    & ~players.injured
                    & (players.bye_week != week)
                    & players.position.isin(flex_pos[pos])
                    & ~players.player_id.isin(started.player_id)
                    & ~players.player_id.isin(not_available.player_id)
                ].iloc[:1]
                
                players.loc[available_players.index, "starter"] = True
        
        return players
