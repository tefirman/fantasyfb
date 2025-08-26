#!/usr/bin/env python
# -*-coding:utf-8 -*-
'''
@File    :   fantasyfb.py
@Time    :   2019/09/07 19:09:47  
@Author  :   Taylor Firman  
@Version :   1.0  
@Contact :   tefirman@gmail.com  
@Desc    :   Firman Fantasy Football Algorithm
'''

import pandas as pd
import os
import numpy as np
import sportsref_nfl as sr
import datetime
from fantasy_scoring import FantasyScorer
from league_configs import get_league_config, apply_default_scoring_categories
from schedule_manager import ScheduleManager
from projection_engine import ProjectionEngine
from season_simulator import SeasonSimulator
from yahoo_client import YahooFantasyClient
from excel_exporter import FantasyExcelExporter
from war_calculator import WARCalculator
from player_data_manager import PlayerDataManager
from lineup_optimizer import LineupOptimizer
from move_analyzer import MoveAnalyzer
from email_utils import send_email
from cli import initialize_inputs

class League:
    """
    League class that gathers all relevant settings and statistics
    to simulate and assess the fantasy league in question.

    Attributes:  
        season: integer specifying the season of interest  
        week: integer specifiying the week of interest  
        oauth: yahoo_oauth object contain user credentials and auth tokens  
        lg: yahoo_fantasy_api league object used to connect to Yahoo's API  
        gm: yahoo_fantasy_api game object used to connect to Yahoo's API  
        name: string specifying the name of the fantasy to be analyzed  
        settings: dictionary containing the scheduling and roster settings for the league in question  
        scoring: dictionary containing the scoring categories and values for the league in question  
        teams: list of dictionaries containing identifiers for each fantasy team in the league  
        nfl_teams: dataframe containing different identifiers for each NFL team  
        nfl_schedule: dataframe containing NFL schedules throughout the years with elo statistics for both teams  
        players: dataframe containing demographics and rates for current NFL players  
        num_sims: integer specifying the number of Monte Carlo simulations to run  
        earliest: integer describing the earliest week to pull statistics from (YYYYWW)  
        reference_games: integer describing the number of games to use as a prior for rates  
        basaloppstringtime: list of the four weighting factors when calculating rates  
        schedule: dataframe containing the fantasy schedule for the league and season in question
    """

    def __init__(
        self,
        name: str = None,
        season: int = None,
        week: int = None,
        injurytries: int = 10,
        num_sims: int = 10000,
        earliest: int = None,
        reference_games: int = None,
        basaloppstringtime: list = [],
        sfb: bool = False,
        bestball: str = "",
    ):
        """
        Initializes a League object using the parameters provided and class functions defined below.

        Args:
            name (str, optional): string describing the name of the fantasy team in question, defaults to None.  
            season (int, optional): integer specifying the season of interest, defaults to None.  
            week (int, optional): integer specifiying the week of interest, defaults to None.  
            injurytries (int, optional): integer specifying the number of attempts to pull injury statuses, defaults to 10.  
            num_sims (int, optional): integer specifying the number of Monte Carlo simulations to run, defaults to 10000.  
            earliest (int, optional): integer describing the earliest week to pull statistics from (YYYYWW), defaults to None.  
            reference_games (int, optional): integer describing the number of games to use as a prior for rates, defaults to None.  
            basaloppstringtime (list, optional): list of the four weighting factors when calculating rates, defaults to an empty list.  
            sfb (bool, optional): whether to implement SFB14 settings and scoring, defaults to False.  
            bestball (str, optional): which platform to use when implementing best ball settings/scoring, defaults to a blank string (no bestball).
        """
        self.latest_season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        """ Year of the most recent season """
        self.season = season if type(season) == int else self.latest_season
        """ Season of interest, defaults to most recent season when no value is provided """
        self.yahoo_client = YahooFantasyClient()
        self.name, self.lg_id = self.yahoo_client.connect_to_league(self.season, name)
        self.lg = self.yahoo_client.lg
        self.current_week = self.lg.current_week()
        """ Most recent week of the season of interest """
        self.week = week if type(week) == int else self.current_week
        """ Week of interest during the season of interest, defaults to most recent week """
        self.load_settings(sfb, bestball)
        self.load_fantasy_teams()
        self.schedule_manager = ScheduleManager(
            self.yahoo_client, 
            self.teams, 
            self.settings, 
            self.lg_id,
            self.latest_season
        )
        self.load_nfl_abbrevs()
        self.load_nfl_schedule()
        self.players = self.yahoo_client.get_all_players(injurytries)
        selected = self.yahoo_client.get_team_rosters(self.teams, self.week)
        self.players = pd.merge(
            left=self.players, 
            right=selected, 
            how="left", 
            on="player_id"
        )
        self.lineup_optimizer = LineupOptimizer(self.roster_spots, self.teams, self.yahoo_client)
        self.move_analyzer = MoveAnalyzer(self)
        
        # Initialize player data manager and process all player data
        player_manager = PlayerDataManager(self.yahoo_client, self.season, self.current_week)
        
        # We need stats for name corrections, so load them first
        self.load_stats((self.season - 2) * 100 + 1, self.season * 100 + self.week - 1)
        
        # Load NFL rosters for get_rates() method
        self.nfl_rosters = sr.get_bulk_rosters(self.season - 1, self.latest_season, "NFLRosters.csv")
        self.nfl_rosters = self.nfl_rosters.rename(columns={'player':'name','player_id':'player_id_sr','team':'current_team'})
        
        # Process all player data in one call
        self.players = player_manager.process_players(
            self.players, 
            self.stats, 
            self.nfl_schedule, 
            self.lg_id, 
            self.week
        )
        
        self.load_parameters(earliest, reference_games, basaloppstringtime)
        self.num_sims = num_sims if type(num_sims) == int else 10000
        """ Number of simulations to run when assessing the league of interest """
        self.get_rates()
        self.war_sim()
        self.get_schedule()
        self.starters(self.week)

    def load_settings(self, sfb: bool = False, bestball: str = ""):
        """
        Pulls league roster/schedule settings and scoring modifiers

        Args:
            sfb (bool, optional): whether to use Scott Fish Bowl 13 settings, defaults to False.  
            bestball (str, optional): which best ball settings to use if desired, defaults to "" (redraft).
        """
        # Pulling league settings
        settings_json = self.lg.yhandler.get_settings_raw(self.lg_id)
        self.settings = settings_json["fantasy_content"]["league"][1]["settings"][0]
        self.settings["playoff_start_week"] = int(self.settings["playoff_start_week"])
        self.settings["num_playoff_teams"] = int(self.settings["num_playoff_teams"])
        self.roster_spots = pd.DataFrame([pos["roster_position"] for pos in self.settings["roster_positions"]])
        self.roster_spots['count'] = self.roster_spots['count'].astype(int)
        categories = pd.DataFrame(
            [stat["stat"] for stat in self.settings["stat_categories"]["stats"]]
        )
        modifiers = pd.DataFrame(
            [stat["stat"] for stat in self.settings["stat_modifiers"]["stats"]]
        )
        self.scoring = pd.merge(
            left=categories,
            right=modifiers,
            how="inner",
            on="stat_id",
        )[["display_name", "value"]].astype({"value": float})
        self.scoring.loc[(self.scoring.display_name == "Int") & (self.scoring.value <= 0),"display_name"] = "Int Thrown"
        self.scoring = self.scoring.drop_duplicates(subset=["display_name"]).set_index("display_name")['value'].to_dict()

        # Check for predefined platform configurations
        config = None
        if sfb:
            config = get_league_config('sfb')
        elif str(bestball).lower() in ["dk", "draftkings"]:
            config = get_league_config('draftkings')
        elif str(bestball).lower() in ["underdog"]:
            config = get_league_config('underdog')

        if config:
            # Apply predefined configuration
            if 'settings' in config:
                for key, value in config['settings'].items():
                    self.settings[key] = value
            self.scoring = config['scoring']
            self.roster_spots = config['roster_spots']
        else:
            # Use default Yahoo scoring with missing categories filled in
            self.scoring = apply_default_scoring_categories(self.scoring)

    def load_fantasy_teams(self):
        """
        Pulls a list of all fantasy team names and ids for the league in question.
        """
        # Pulling list of teams in the fantasy league
        league_info = self.lg.yhandler.get_standings_raw(self.lg_id)["fantasy_content"]
        teams_info = league_info["league"][1]["standings"][0]["teams"]
        self.teams = [
            {
                "team_key": teams_info[str(ind)]["team"][0][0]["team_key"],
                "name": teams_info[str(ind)]["team"][0][2]["name"],
                "manager": teams_info[str(ind)]["team"][0][-1]['managers'][0]['manager']['nickname'],
            }
            for ind in range(teams_info["count"])
        ]

    def load_nfl_abbrevs(self):
        """
        Loads a translation table for all NFL team abbreviations across platforms
        """
        self.nfl_teams = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/team_abbrevs.csv"
        )

    def load_nfl_schedule(self, path: str = "NFLSchedule.csv"):
        """
        Loads and processes the NFL schedule for use in future simulations

        Args:
            path (str, optional): location of saved NFL schedule, defaults to "NFLSchedule.csv".
        """
        if os.path.exists(path):
            nfl_schedule = pd.read_csv(path)
        else:
            nfl_schedule = pd.DataFrame(columns=['season','week','score1','score2'])
        before = nfl_schedule.season*100 + nfl_schedule.week < self.season*100 + self.week
        missing = before & nfl_schedule.score1.isnull() & nfl_schedule.score2.isnull()
        if missing.any() or self.season not in nfl_schedule.season.unique():
            s = sr.Schedule(self.season - 8,self.season,False,True,False)
            s.schedule.to_csv(path,index=False)
            nfl_schedule = s.schedule.copy()
        
        nfl_schedule = nfl_schedule[[
                "season",
                "game_date",
                "week",
                "team1_abbrev",
                "team2_abbrev",
                "elo1_pre",
                "elo2_pre",
                "elo_diff",
            ]].rename(
            columns={
                "game_date": "date",
                "team1_abbrev": "home_team",
                "team2_abbrev": "away_team",
                "elo1_pre": "home_elo",
                "elo2_pre": "away_elo",
                "elo_diff": "home_elo_diff",
            },
        )
        nfl_schedule["away_elo_diff"] = -1*nfl_schedule["home_elo_diff"]
        home = nfl_schedule[["season", "week", "date", "home_team", "home_elo_diff", "away_elo"]]\
        .rename(columns={"home_team": "team", "home_elo_diff": "elo_diff", "away_elo": "opp_elo"})
        home["home_away"] = "Home"
        away = nfl_schedule[["season", "week", "date", "away_team", "away_elo_diff", "home_elo"]]\
        .rename(columns={"away_team": "team", "away_elo_diff": "elo_diff", "home_elo": "opp_elo"})
        away["home_away"] = "Away"
        nfl_schedule = pd.concat([home, away], ignore_index=True)
        nfl_schedule.elo_diff = nfl_schedule.elo_diff / 1500
        nfl_schedule.opp_elo = 1500 / nfl_schedule.opp_elo
        try:
            nfl_schedule.date = pd.to_datetime(nfl_schedule.date, format="%Y-%m-%d")
        except:
            nfl_schedule.date = pd.to_datetime(nfl_schedule.date, format="%m/%d/%y") # Accounting for manual updates to schedule csv... Thanks Excel...
        self.nfl_schedule = nfl_schedule.sort_values(by=["season", "week"], ignore_index=True)

    def pull_stats(self, start: int, finish: int, path: str = "GameByGameFantasyFootballStats.csv"):
        """
        Pulls a dataframe containing event rates based on per-game statistics during the specified timeframe.

        Args:
            start (int): year and number of the first week of interest (YYYYWW, e.g. 202102 = week 2 of 2021).  
            finish (int): year and number of the last week of interest (YYYYWW, e.g. 202307 = week 7 of 2023).  
            path (str, optional): location of saved per-game statistics, defaults to "GameByGameFantasyFootballStats.csv".

        Returns:
            pd.DataFrame: dataframe containing player rates based on games during the timespan of interest.
        """
        s = sr.Schedule(start//100,finish//100)
        stats = sr.get_bulk_stats(start//100,start%100,finish//100,finish%100,False,path,schedule_data=s.schedule)
        pts_allowed = pd.concat([s.schedule[['boxscore_abbrev','team1_abbrev','score2']]\
        .rename(columns={'boxscore_abbrev':'game_id','team1_abbrev':'team','score2':'points_allowed'}),\
        s.schedule[['boxscore_abbrev','team2_abbrev','score1']]\
        .rename(columns={'boxscore_abbrev':'game_id','team2_abbrev':'team','score1':'points_allowed'})],ignore_index=True)
        stats = pd.merge(left=stats,right=pts_allowed,how='left',on=['game_id','team'])
        pos_corrections = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/pos_corrections.csv"
        )
        stats = pd.merge(left=stats,right=pos_corrections[['player_id','actual_pos']],how='left',on=['player_id'])
        stats.loc[~stats.actual_pos.isnull(),'pos'] = stats.loc[~stats.actual_pos.isnull(),'actual_pos']
        del stats['actual_pos']
        to_fix = ~stats.pos.isin(["QB", "RB", "WR", "TE", "K"]) & (
            stats.pos.str.contains("QB")
            | stats.pos.str.contains("WR")
            | stats.pos.str.contains("RB")
            | stats.pos.str.contains("TE")
            | (stats.pos.str.contains("K") & ~stats.pos.isin(["MIKE","JACK"]))
        )
        if to_fix.any():
            print('Weird positions in game-by-game stats...')
            print(stats.loc[to_fix, ["player_id", "player", "pos"]].to_string(index=False))
        defenses = (
            stats.loc[~stats.pos.isin(["QB", "RB", "WR", "TE", "K"])]
            .groupby(
                ["game_id", "season", "week", "team", "opponent", "points_allowed"]
            )
            .sum(numeric_only=True)
            .reset_index()
        )
        defenses["player"] = defenses["team"]
        defenses["player_id"] = defenses["player"]
        defenses["pos"] = "DEF"
        if "string" in defenses.columns:
            defenses["string"] = 1.0
        defenses = defenses[[col for col in stats.columns if col in defenses.columns]]
        stats = stats.loc[stats.pos.isin(["QB", "RB", "WR", "TE", "K"])]
        self.stats = pd.concat([stats,defenses], ignore_index=True)\
        .rename(columns={'pos':'position','player':'name','player_id':'player_id_sr'})
        self.stats["weeks_ago"] = (datetime.datetime.now() - pd.to_datetime(self.stats.game_id.str[:8])).dt.days / 7.0

    def add_points(self):
        """
        Calculates per-game fantasy points based on per-game statistics and provided scoring settings.
        """
        scorer = FantasyScorer(self.scoring)
        self.stats = scorer.calculate_points(self.stats)
    
    def load_stats(self, start: int, finish: int):
        """
        Loads individual player statistics for each game in the specified timeframe 
        and calculates fantasy points based on league settings. Initially looks for 
        pre-pulled statistics saved locally and pulls new stats when necessary.

        Args:
            start (int): year and number of the first week of interest (YYYYWW, e.g. 202102 = week 2 of 2021).  
            finish (int): year and number of the last week of interest (YYYYWW, e.g. 202307 = week 7 of 2023).
        """
        self.pull_stats(start, finish)
        self.add_points()
        self.stats = pd.merge(
            left=self.stats,
            right=self.nfl_schedule,
            how="left",
            on=["season", "week", "team"],
        )

    def load_parameters(self, earliest: int = None, reference_games: int = None, basaloppstringtime: list = []):
        """
        Initializes rate adjustment parameters for future season simulations. 
        If parameters are not manually, optimal values are chosen based on 
        maximum likelihood fitting over five years.

        Args:
            earliest (int, optional): year and number of the earliest week to be included in the prior for rate calculation, defaults to None.  
            reference_games (int, optional): number of games to include the prior for rate calculation, defaults to None.  
            basaloppstringtime (list, optional): list containing the basal factor, opponent elo factor, and depth chart factor, defaults to [].
        """
        params = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/weighting_factors.csv"
        )
        if earliest:
            self.earliest = {}
            for pos in ["QB","RB","WR","TE","K","DEF"]:
                self.earliest[pos] = earliest
        else:
            priors = params.loc[params.week == self.week].set_index("position").to_dict()['prior']
            self.earliest = {}
            for pos in priors:
                self.earliest[pos] = (self.season - priors[pos] // 17) * 100 + self.week - priors[pos] % 17
                if (self.earliest[pos] % 100 == 0) | (self.earliest[pos] % 100 > 50):
                    self.earliest[pos] -= 83  # Assuming 17 weeks... Need to change this soon...
        if reference_games:
            self.reference_games = {}
            for pos in ["QB","RB","WR","TE","K","DEF"]:
                self.reference_games[pos] = reference_games
        else:
            self.reference_games = params.loc[params.week == self.week].set_index("position").to_dict()['games']
        if basaloppstringtime:
            self.basaloppstringtime = pd.DataFrame({"position":["QB","RB","WR","TE","K","DEF"]})
            self.basaloppstringtime["basal"] = basaloppstringtime[0]
            self.basaloppstringtime["opp_elo_weight"] = basaloppstringtime[1]
            self.basaloppstringtime["string_weight"] = basaloppstringtime[2]
            self.basaloppstringtime["time_scale"] = basaloppstringtime[3]
        else:
            self.basaloppstringtime = params.loc[params.week == self.week, \
            ["position", "basal", "opp_elo_weight", "string_weight", "time_scale"]]

    def get_rates(self, reload: bool = True):
        """
        Calculates the average and standard deviation of fantasy points for each player 
        based on the specified prior and normalizing with respect to the provided weighting factors.

        Args:
            reload (bool, optional): whether to reload the statistics dataframe, defaults to True.
        """
        as_of = self.season * 100 + self.week
        if not hasattr(self, "stats") or reload:
            self.load_stats(min(self.earliest.values()), as_of - 1)
        
        # Use the new ProjectionEngine
        engine = ProjectionEngine(self.basaloppstringtime, self.reference_games)
        projections = engine.calculate_projections(
            self.stats, 
            self.earliest, 
            as_of,
            self.nfl_schedule
        )
        
        # Separate average players and real players
        league_avg = projections[projections['player_id_sr'].str.startswith('avg_')].copy()
        league_avg['string'] = 2.0
        
        # Merge projections with existing player metadata
        by_player = pd.merge(
            projections[~projections['player_id_sr'].str.startswith('avg_')],
            self.players[[
                "player_id_sr", "player_id", "status", "fantasy_team", "current_team", 
                "position", "string", "until", "bye_week", "pct_rostered", "selected_position"
            ]].drop_duplicates(),
            how="right",
            on=["player_id_sr", "position"],
        )
        
        # Handle rookies (players not in projections) - merge with position averages
        rookies = pd.merge(
            left=by_player.loc[
                by_player.num_games.isnull(),
                ["player_id_sr", "player_id", "status", "fantasy_team", "current_team", 
                "position", "string", "until", "bye_week", "pct_rostered", "selected_position"],
            ],
            right=league_avg[["position", "points_rate", "points_stdev"]],
            how="inner",
            on="position",
        )
        
        # Combine players with data and rookies
        by_player = by_player.loc[~by_player.num_games.isnull()]
        by_player = pd.concat([
            by_player[["player_id_sr", "player_id", "status", "fantasy_team", "current_team", 
                    "position", "points_rate", "points_stdev", "string", "until", 
                    "bye_week", "pct_rostered", "selected_position"]],
            rookies[["player_id_sr", "player_id", "status", "fantasy_team", "current_team", 
                    "position", "points_rate", "points_stdev", "string", "until", 
                    "bye_week", "pct_rostered", "selected_position"]],
            league_avg
        ], ignore_index=True, sort=False)
        
        # Add back player names from NFL rosters
        by_player = pd.merge(
            left=by_player,
            right=self.nfl_rosters[['player_id_sr','name']].drop_duplicates(subset=['player_id_sr'], keep='last'),
            how='left',
            on='player_id_sr'
        )
        
        # Add Yahoo names for players not found in NFL rosters
        by_player = pd.merge(
            left=by_player,
            right=self.players[['player_id','name']].rename(columns={'name':'yahoo_name'}).drop_duplicates(),
            how="left",
            on='player_id'
        )
        missing = by_player.name.isnull() & ~by_player.yahoo_name.isnull()
        by_player.loc[missing,'name'] = by_player.loc[missing,'yahoo_name']
        del by_player['yahoo_name']
        
        # Handle defense naming
        defenses = by_player.player_id_sr.isin(self.nfl_teams.real_abbrev.tolist())
        by_player.loc[defenses,'name'] = by_player.loc[defenses,'player_id_sr']
        
        # Handle average player naming
        avgs = by_player.player_id_sr.astype(str).str.startswith("avg_")
        by_player.loc[avgs,"name"] = "Average_" + by_player.loc[avgs,"position"]
        
        # Update current teams for players who changed teams mid-season
        teams_as_of = (
            self.stats.loc[self.stats.season * 100 + self.stats.week >= as_of]
            .sort_values(by=["season","week"],ascending=True)
            .drop_duplicates(subset="player_id_sr", keep="first")[
                ["player_id_sr", "team"]
            ]
            .rename(columns={"team": "actual_team"})
        )
        by_player = pd.merge(
            left=by_player,
            right=teams_as_of,
            how="left",
            on="player_id_sr",
        )
        not_yet = ~by_player.actual_team.isnull()
        by_player.loc[not_yet,'current_team'] = by_player.loc[not_yet,'actual_team']
        del by_player['actual_team']
        
        self.players = by_player

    def get_schedule(self):
        """
        Pulls the fantasy schedule for the season in question as well as 
        scores for all matchups up to the week in question.
        """
        self.schedule = self.schedule_manager.get_schedule(
            self.season, 
            self.week,
            self.current_week,
            self.lg.team_key()
        )

    def starters(self, week: int):
        """
        Identifies which players should be started on each fantasy team 
        based on fantasy point projections and available roster spots.

        Args:
            week: week for which to identify starters.
        """
        self.players = self.lineup_optimizer.set_optimal_lineup(
            self.players, 
            week, 
            self.season, 
            self.current_week, 
            self.latest_season,
            self.nfl_schedule, 
            self.basaloppstringtime
        )

    def bestball_sims(self, payouts: list = [20,20,20]):
        """
        Simulates the remainder of the fantasy season based on current rosters 
        and best ball settings using Monte Carlo simulations.

        Args:
            payouts (list, optional): list of prize amounts for first, second, and third, defaults to [800, 300, 100].

        Returns:
            standings (pd.DataFrame): simulated results for the final season standings and playoff projections.
        """
        self.yahoo_client.refresh_oauth()
        projections = pd.DataFrame(columns=["fantasy_team", "week", "points_avg", "points_stdev"])
        for week in range(self.week,self.settings['playoff_start_week']):
            self.starters(week)
            projections = pd.concat([projections,self.players.loc[~self.players.fantasy_team.isnull(),\
            ['player_id_sr','name','position','fantasy_team','points_avg','points_stdev']].reset_index(drop=True)],ignore_index=True,sort=False)
            projections.loc[projections.week.isnull(), "week"] = week
        season_sims = pd.concat([projections] * self.num_sims, ignore_index=True)
        season_sims["num_sim"] = season_sims.index // projections.shape[0]
        season_sims["points_sim"] = (
            np.random.normal(loc=0, scale=1, size=season_sims.shape[0])
            * season_sims["points_stdev"]
            + season_sims["points_avg"]
        ).astype(float)
        season_sims = season_sims.sort_values(by='points_sim',ascending=False,ignore_index=True)
        season_sims['injured'] = np.random.rand(season_sims.shape[0]) < 0.1
        season_sims['starter'] = False
        num_pos = self.roster_spots.loc[~self.roster_spots.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])].set_index('position').to_dict()['count']
        for pos in num_pos:
            inds = season_sims.loc[(season_sims.position == pos) & ~season_sims.injured]\
            .groupby(['num_sim','week','fantasy_team']).head(num_pos[pos]).index
            season_sims.loc[inds,'starter'] = True
        flex_pos = {"W/T":['WR','TE'],"W/R/T":['WR','RB','TE'],"Q/W/R/T":['WR','RB','TE','QB']}
        for pos in flex_pos:
            num_flex = self.roster_spots.loc[self.roster_spots.position == pos,'count'].sum()
            inds = season_sims.loc[season_sims.position.isin(flex_pos[pos]) & ~season_sims.injured & ~season_sims.starter]\
            .groupby(['num_sim','week','fantasy_team']).head(num_flex).index
            season_sims.loc[inds,'starter'] = True
        standings_sims = season_sims.loc[season_sims.starter].groupby(['num_sim','fantasy_team']).points_sim.sum().reset_index()
        standings_sims = standings_sims.sort_values(by=['num_sim','points_sim'],ascending=[True,False],ignore_index=True)
        standings_sims['place'] = standings_sims.index%len(self.teams) + 1
        standings_sims["playoffs"] = (standings_sims['place'] <= self.settings["num_playoff_teams"]).astype(float)
        standings_sims["winner"] = (standings_sims['place'] == 1).astype(float)
        standings_sims["runner_up"] = (standings_sims['place'] == 2).astype(float)
        standings_sims["third"] = (standings_sims['place'] == 3).astype(float)
        payouts += [0]*(len(self.teams) - len(payouts))
        standings_sims['earnings'] = payouts*self.num_sims
        standings = standings_sims.groupby('fantasy_team').mean().reset_index()
        standings = pd.merge(left=standings,right=standings_sims.groupby('fantasy_team').points_sim.std()\
        .reset_index().rename(columns={'points_sim':'points_stdev'}),how='inner',on='fantasy_team')
        standings = standings.rename(columns={'fantasy_team':'team','points_sim':'points_avg','place':'avg_place'})
        standings = standings.sort_values(by='playoffs',ascending=False,ignore_index=True)
        del standings['num_sim']
        standings[["wins_avg","wins_stdev","playoff_bye"]] = 0.0
        return standings

    def season_sims(
        self, 
        postseason: bool = True, 
        payouts: list = [800, 300, 100], 
        fixed_winner: list = None,
    ):
        """
        Simulates the remainder of the fantasy season based on current rosters 
        and redraft settings using Monte Carlo simulations.

        Args:
            postseason (bool, optional): whether to simulate the postseason in addition to the regular season, defaults to True.  
            payouts (list, optional): list of prize amounts for first, second, and third, defaults to [800, 300, 100].  
            fixed_winner (list, optional): list containing the week and team name of a fixed winner, defaults to None.

        Returns:
            schedule (pd.DataFrame): simulated results for each matchup throughout the season in question  
            standings (pd.DataFrame): simulated results for the final season standings and playoff projections
        """
        self.yahoo_client.refresh_oauth()
        
        # Calculate team projections for each week (your existing logic)
        self.players["points_var"] = self.players.points_stdev**2
        projections_list = []
        for week in range(17):
            self.starters(week + 1)
            week_projections = (
                self.players.loc[self.players.starter]
                .groupby("fantasy_team")[["points_avg", "points_var"]]
                .sum()
                .reset_index()
            )
            if not week_projections.empty:
                week_projections["week"] = week + 1
                projections_list.append(week_projections)
        if projections_list:
            projections = pd.concat(projections_list, ignore_index=True)
        else:
            projections = pd.DataFrame(columns=["fantasy_team", "week", "points_avg", "points_var"])
        projections["points_stdev"] = projections["points_var"] ** 0.5
        del self.players["points_var"]
        
        # Prepare league settings for simulator
        league_settings = {
            'playoff_start_week': self.settings['playoff_start_week'],
            'num_playoff_teams': self.settings['num_playoff_teams'],
            'uses_playoff_reseeding': self.settings.get('uses_playoff_reseeding', False),
            'num_teams': len(self.teams)
        }
        
        # Use the new SeasonSimulator for regular season AND playoffs
        simulator = SeasonSimulator(league_settings)
        
        schedule, standings = simulator.simulate_season(
            player_projections=projections,
            schedule_df=self.schedule,
            num_sims=self.num_sims,
            include_playoffs=postseason,  # Re-enable playoff simulation
            payouts=payouts,
            fixed_winner=fixed_winner
        )
        
        # Add back the 'me' column from original schedule
        if 'me' in self.schedule.columns:
            schedule = pd.merge(
                schedule, 
                self.schedule[['week', 'team_1', 'team_2', 'me']], 
                on=['week', 'team_1', 'team_2'], 
                how='left'
            )
            schedule['me'] = schedule['me'].fillna(False)
        
        # Add per-game statistics (your existing logic)
        scores = pd.concat([
            schedule[["team_1", "sim_1"]].rename(columns={"team_1": "team", "sim_1": "sim"}),
            schedule[["team_2", "sim_2"]].rename(columns={"team_2": "team", "sim_2": "sim"})
        ], ignore_index=True).groupby("team")
        
        per_game_stats = pd.DataFrame({
            'team': scores.groups.keys(),
            'per_game_avg': [scores.get_group(team)['sim'].mean() for team in scores.groups.keys()],
            'per_game_stdev': [scores.get_group(team)['sim'].std() for team in scores.groups.keys()]
        })
        per_game_stats["per_game_fano"] = per_game_stats["per_game_stdev"] / per_game_stats["per_game_avg"]
        
        # Merge per-game stats into standings
        standings = pd.merge(standings, per_game_stats, on='team', how='left')
        
        # Round values to match your existing format
        standings["wins_avg"] = round(standings["wins_avg"], 3)
        standings["wins_stdev"] = round(standings["wins_stdev"], 3)
        standings["points_avg"] = round(standings["points_avg"], 1)
        standings["points_stdev"] = round(standings["points_stdev"], 1)
        standings["per_game_avg"] = round(standings["per_game_avg"], 1)
        standings["per_game_stdev"] = round(standings["per_game_stdev"], 1)
        standings["per_game_fano"] = round(standings["per_game_fano"], 3)
        
        # Round schedule values
        schedule["points_avg_1"] = round(schedule["points_avg_1"], 1)
        schedule["points_stdev_1"] = round(schedule["points_stdev_1"], 1)
        schedule["points_avg_2"] = round(schedule["points_avg_2"], 1)
        schedule["points_stdev_2"] = round(schedule["points_stdev_2"], 1)
        
        return schedule, standings

    def war_sim(self):
        """
        Simulates the wins-above-replacement (WAR) for each of the players eligible to roster.
        """
        as_of = self.season * 100 + self.week
        self.load_stats(as_of - 100, as_of - 1)
        
        calculator = WARCalculator(self.num_sims)
        self.players = calculator.calculate_war(self.players, self.stats)

    def possible_pickups(self, **kwargs):
        """Analyze potential pickup moves."""
        return self.move_analyzer.possible_pickups(**kwargs)

    def possible_adds(self, **kwargs):
        """Analyze potential add moves."""
        return self.move_analyzer.possible_adds(**kwargs)

    def possible_drops(self, **kwargs):
        """Analyze potential drop moves."""
        return self.move_analyzer.possible_drops(**kwargs)

    def possible_trades(self, **kwargs):
        """Analyze potential trade moves."""
        return self.move_analyzer.possible_trades(**kwargs)

    def perGameDelta(self, team_name: str = None, postseason: bool = True, payouts: list = [800, 300, 100]):
        """
        Simulates the remainder of the season and compares it to a simulation 
        of the season given one team winning or losing each matchup.

        Args:
            team_name (str, optional): name of team to analyze matchup values for, defaults to None (and therefore team of interest).  
            postseason (bool, optional): whether to analyze postseason gains or just regular season, defaults to True.  
            payouts (list, optional): list of payout amounts for top three finishers, defaults to [800, 300, 100].

        Returns:
            pd.DataFrame: dataframe containing the impact and value of every matchup during the week of interest.
        """
        as_of = self.season * 100 + self.week
        self.yahoo_client.refresh_oauth()
        if not team_name:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == self.lg.team_key()
            ][0]
        deltas = self.season_sims(postseason, payouts)[1][["team", "earnings"]]
        for team in self.players.fantasy_team.unique():
            new_standings = self.season_sims(
                postseason, payouts, fixed_winner=[as_of % 100, team]
            )[1][["team", "earnings"]].rename(columns={"earnings": "earnings_new"})
            deltas = pd.merge(left=deltas, right=new_standings, how="inner", on="team")
            deltas[team] = deltas["earnings_new"] - deltas["earnings"]
            del deltas["earnings_new"]
            print(deltas[["team", team]].to_string(index=False))
        del deltas["earnings"]
        return (
            deltas.set_index("team").T.reset_index().rename(columns={"index": "winner"})
        )


def main():
    options = initialize_inputs()
    league = League(
        name=options.name,
        season=options.season,
        week=options.week,
        injurytries=options.injurytries,
        num_sims=options.sims,
        earliest=options.earliest,
        reference_games=options.games,
        basaloppstringtime=options.basaloppstringtime,
    )
    # Create Excel exporter
    excel_file = options.output + "FantasyFootballProjections_{}Week{}{}.xlsx".format(
        datetime.datetime.now().strftime("%A"), league.week, "_BestBall" if options.bestball else ""
    )
    exporter = FantasyExcelExporter(excel_file)

    rosters = (
        league.players.loc[~league.players.fantasy_team.isnull()]
        .sort_values(by=["fantasy_team", "WAR"], ascending=[True, False])
        .copy()
    )
    exporter.export_rosters(rosters)

    available = league.players.loc[
        league.players.fantasy_team.isnull()
        & (league.players.until.isnull() | (league.players.until < 17))
    ].sort_values(by="WAR", ascending=False)
    del available["fantasy_team"]
    exporter.export_available(available)

    if options.bestball:
        standings_sim = league.bestball_sims(payouts=options.payouts)
    else:
        schedule_sim, standings_sim = league.season_sims(True, payouts=options.payouts)
        print(
            schedule_sim.loc[
                schedule_sim.week == league.week,
                [
                    "week",
                    "team_1",
                    "team_2",
                    "win_1",
                    "win_2",
                    "points_avg_1",
                    "points_avg_2",
                ],
            ].to_string(index=False)
        )
        print(
            standings_sim[
                [
                    "team",
                    "wins_avg",
                    "points_avg",
                    "playoffs",
                    "playoff_bye",
                    "winner",
                    "earnings",
                ]
                + (["many_mile"] if league.name == "The Algorithm" else [])
            ].to_string(index=False)
        )
        exporter.export_schedule(schedule_sim)
    has_many_mile = league.name == "The Algorithm" and not options.bestball
    exporter.export_standings(standings_sim, has_many_mile)

    if options.pickups:
        pickups = league.possible_pickups(
            focus_on=[val.strip() for val in options.pickups.split(",")]
            if options.pickups.lower() != "all"
            else [],
            exclude=["Tom Brady"],
            limit_per=5,
            payouts=options.payouts,
            bestball=options.bestball,
        )
        exporter.export_analysis(pickups, "Pickups", freeze_cols=2, has_many_mile=has_many_mile)

    if options.adds:
        adds = league.possible_adds(
            exclude=["Tom Brady"],
            limit_per=5,
            payouts=options.payouts,
            bestball=options.bestball,
        )
        exporter.export_analysis(adds, "Adds", has_many_mile=has_many_mile)

    if options.drops:
        drops = league.possible_drops(
            payouts=options.payouts,
            bestball=options.bestball,
        )
        exporter.export_analysis(drops, "Drops", has_many_mile=has_many_mile)

    if options.trades or options.given:
        if not options.trades:
            options.trades = "all"
        trades = league.possible_trades(
            focus_on=[val.strip() for val in options.trades.split(",")]
            if options.trades.lower() != "all"
            else [],
            exclude=["Tom Brady"],
            given=[val.strip() for val in options.given.split(",")] if options.given else [],
            limit_per=10,
            payouts=options.payouts,
            bestball=options.bestball,
        )
        exporter.export_analysis(trades, "Trades", freeze_cols=3, has_many_mile=False)

    if options.deltas:
        deltas = league.perGameDelta(payouts=options.payouts)
        exporter.export_deltas(deltas)

    exporter.close()
    os.system(
        'touch -t {} "{}"'.format(
            datetime.datetime.now().strftime("%Y%m%d%H%M"),
            "/".join(options.output.split("/")[:-2]),
        )
    )
    if options.email:
        try:
            send_email(
                "Fantasy Football Projections for " + options.name,
                "Best of luck to you this fantasy football season!!!",
                options.email,
                options.output
                + "FantasyFootballProjections_{}Week{}.xlsx".format(
                    datetime.datetime.now().strftime("%A"), league.week
                ),
            )
        except:
            print(
                "Couldn't email results, maybe no wifi...\nResults saved to "
                + options.output
                + "FantasyFootballProjections_{}Week{}.xlsx".format(
                    datetime.datetime.now().strftime("%A"), league.week
                )
            )


if __name__ == "__main__":
    main()
