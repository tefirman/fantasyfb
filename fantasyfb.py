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
import time
import datetime
import optparse
import smtplib, ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import traceback
from fantasy_scoring import FantasyScorer
from projection_engine import ProjectionEngine
from season_simulator import SeasonSimulator
from yahoo_client import YahooFantasyClient
from excel_exporter import FantasyExcelExporter
from war_calculator import WARCalculator

# Probably not smart long term, but doing it for now...
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

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
        self.load_nfl_abbrevs()
        self.load_nfl_schedule()
        self.get_yahoo_players(injurytries)
        self.get_fantasy_rosters()
        self.name_corrections()
        self.get_player_ids()
        self.add_injuries()
        self.add_bye_weeks()
        self.add_roster_pcts()
        self.add_depth_charts()
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
        if sfb:
            # # SFB13
            # self.settings['playoff_start_week'] = 12
            # self.settings['num_playoff_teams'] = 6
            # self.scoring = {'Pass Yds':0.04,'Pass Comp':0.1,'Pass TD':6.0,'Pass 1D':0.1,'Pass 300+':0.0,\
            # 'Int Thrown':0.0,'Rush Yds':0.1,'Rush Att':0.25,'Rush TD':6.0,'Rush 1D':1.0,'Rush 100+':0.0,\
            # 'Rec Yds':0.1,'Rec':1.0,'Rec TD':6.0,'Rec 1D':1.0,'Rec 100+':0.0,'Ret Yds':0.0,'Ret TD':6.0,\
            # 'TE Rec Bonus':1.0,'TE 1D Bonus':1.0,'2-PT':2.0,'Fum Lost':0.0,'Fum Ret TD':6.0,\
            # 'FG 0-19':2.0,'FG 20-29':2.5,'FG 30-39':3.5,'FG 40-49':4.5,'FG 50+':5.5,'PAT Made':3.3,\
            # 'Sack':0.0,'Int':0.0,'Fum Rec':0.0,'TD':0.0,'Safe':0.0,'Blk Kick':0.0,\
            # 'Pts Allow 0':0.0,'Pts Allow 1-6':0.0,'Pts Allow 7-13':0.0,'Pts Allow 14-20':0.0,\
            # 'Pts Allow 21-27':0.0,'Pts Allow 28-34':0.0,'Pts Allow 35+':0.0,'XPR':0.0}
            # self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[1,2,3,1,2,1,1,11]})
            # # SFB14
            # self.scoring = {'Pass Yds':0.02,'Pass Comp':0.0,'Pass TD':6.0,'Pass 1D':0.0,'Pass 300+':0.0,\
            # 'Int Thrown':0.0,'Rush Yds':0.1,'Rush Att':0.25,'Rush TD':6.0,'Rush 1D':0.5,'Rush 100+':0.0,\
            # 'Rec Yds':0.1,'Rec':0.75,'Rec TD':6.0,'Rec 1D':0.5,'Rec 100+':0.0,'Ret Yds':0.2,'Ret TD':10.0,\
            # 'TE Rec Bonus':0.75,'TE 1D Bonus':1.0,'2-PT':2.0,'Fum Lost':0.0,'Fum Ret TD':6.0,\
            # 'FG 0-19':2.0,'FG 20-29':2.5,'FG 30-39':3.5,'FG 40-49':4.5,'FG 50+':5.5,'PAT Made':3.3,\
            # 'Sack':0.0,'Int':0.0,'Fum Rec':0.0,'TD':0.0,'Safe':0.0,'Blk Kick':0.0,\
            # 'Pts Allow 0':0.0,'Pts Allow 1-6':0.0,'Pts Allow 7-13':0.0,'Pts Allow 14-20':0.0,\
            # 'Pts Allow 21-27':0.0,'Pts Allow 28-34':0.0,'Pts Allow 35+':0.0,'XPR':0.0}
            # self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[1,1,1,1,5,1,1,11]})
            # SFB15
            self.scoring = {'Pass Yds':0.04,'Pass Comp':0.0,'Pass TD':6.0,'Pass 1D':0.0,'Pass 300+':0.0,\
            'Int Thrown':0.0,'Rush Yds':0.1,'Rush Att':0.5,'Rush TD':6.0,'Rush 1D':1.0,'Rush 100+':0.0,\
            'Rec Yds':0.1,'Rec':2.5,'Rec TD':6.0,'Rec 1D':1.0,'Rec 100+':0.0,'Ret Yds':0.0,'Ret TD':6.0,\
            'TE Rec Bonus':1.0,'TE 1D Bonus':1.0,'2-PT':2.0,'Fum Lost':0.0,'Fum Ret TD':6.0,\
            'FG 0-19':0.0,'FG 20-29':0.0,'FG 30-39':0.0,'FG 40-49':0.0,'FG 50+':0.0,'PAT Made':0.0,\
            'Sack':0.0,'Int':0.0,'Fum Rec':0.0,'TD':0.0,'Safe':0.0,'Blk Kick':0.0,\
            'Pts Allow 0':0.0,'Pts Allow 1-6':0.0,'Pts Allow 7-13':0.0,'Pts Allow 14-20':0.0,\
            'Pts Allow 21-27':0.0,'Pts Allow 28-34':0.0,'Pts Allow 35+':0.0,'XPR':0.0}
            self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[0,0,0,0,9,2,0,11]})
        elif str(bestball).lower() in ["dk", "draftkings"]:
            self.settings['playoff_start_week'] = 14
            self.settings['num_playoff_teams'] = 2
            self.scoring = {'Pass Yds':0.04,'Pass Comp':0.0,'Pass TD':4.0,'Pass 1D':0.0,'Pass 300+':3.0,\
            'Int Thrown':-1.0,'Rush Yds':0.1,'Rush Att':0.0,'Rush TD':6.0,'Rush 1D':0.0,'Rush 100+':3.0,\
            'Rec Yds':0.1,'Rec':1.0,'Rec TD':6.0,'Rec 1D':0.0,'Rec 100+':3.0,'Ret Yds':0.0,'Ret TD':6.0,\
            'TE Rec Bonus':0.0,'TE 1D Bonus':0.0,'2-PT':2.0,'Fum Lost':-1.0,'Fum Ret TD':6.0,\
            'FG 0-19':0.0,'FG 20-29':0.0,'FG 30-39':0.0,'FG 40-49':0.0,'FG 50+':0.0,'PAT Made':0.0,\
            'Sack':0.0,'Int':0.0,'Fum Rec':0.0,'TD':0.0,'Safe':0.0,'Blk Kick':0.0,\
            'Pts Allow 0':0.0,'Pts Allow 1-6':0.0,'Pts Allow 7-13':0.0,'Pts Allow 14-20':0.0,\
            'Pts Allow 21-27':0.0,'Pts Allow 28-34':0.0,'Pts Allow 35+':0.0,'XPR':0.0}
            self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[1,2,3,1,1,0,0,12]})
        elif str(bestball).lower() in ["underdog"]:
            # Slow Puppy
            self.settings['playoff_start_week'] = 14
            self.settings['num_playoff_teams'] = 2
            self.scoring = {'Pass Yds':0.04,'Pass Comp':0.0,'Pass TD':4.0,'Pass 1D':0.0,'Pass 300+':0.0,\
            'Int Thrown':-1.0,'Rush Yds':0.1,'Rush Att':0.0,'Rush TD':6.0,'Rush 1D':0.0,'Rush 100+':0.0,\
            'Rec Yds':0.1,'Rec':0.5,'Rec TD':6.0,'Rec 1D':0.0,'Rec 100+':0.0,'Ret Yds':0.0,'Ret TD':0.0,\
            'TE Rec Bonus':0.0,'TE 1D Bonus':0.0,'2-PT':2.0,'Fum Lost':-2.0,'Fum Ret TD':0.0,\
            'FG 0-19':0.0,'FG 20-29':0.0,'FG 30-39':0.0,'FG 40-49':0.0,'FG 50+':0.0,'PAT Made':0.0,\
            'Sack':0.0,'Int':0.0,'Fum Rec':0.0,'TD':0.0,'Safe':0.0,'Blk Kick':0.0,\
            'Pts Allow 0':0.0,'Pts Allow 1-6':0.0,'Pts Allow 7-13':0.0,'Pts Allow 14-20':0.0,\
            'Pts Allow 21-27':0.0,'Pts Allow 28-34':0.0,'Pts Allow 35+':0.0,'XPR':0.0}
            self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[1,2,3,1,1,0,0,10]})
            # # Pomeranian Superflex
            # self.settings['num_playoff_teams'] = 3
            # self.roster_spots = pd.DataFrame({'position':['QB','RB','WR','TE','W/R/T','Q/W/R/T','K','BN'],'count':[1,2,2,1,1,1,0,12]})
        else:
            if "FG 0-19" not in self.scoring:
                self.scoring["FG 0-19"] = 3
            if "Rec" not in self.scoring:
                self.scoring["Rec"] = 0
            if "Ret Yds" not in self.scoring:
                self.scoring["Ret Yds"] = 0
            for stat in ['Pass Comp','Pass 1D','Rush Att','Rush 1D','Rec 1D',\
            'TE Rec Bonus','TE 1D Bonus','Pass 300+','Rush 100+','Rec 100+']:
                self.scoring[stat] = 0.0

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

    def get_yahoo_players(self, injurytries: int = 10):
        """
        Pulls a dataframe containing details about all NFL players that are eligible 
        to be rostered in the fantasy league in question. Injury statuses will occasionally 
        be excluded by API; in that case, the function will repeat the pull until it sees 
        the injury statuses or hits the upper limit provided in injurytries.

        Args:
            injurytries (int, optional): maximum number of times the code will try to pull the player list, defaults to 10.
        """
        self.yahoo_client.refresh_oauth()
        tries = 0
        while tries < injurytries:
            tries += 1
            players = []
            # Rostered Players
            for page_ind in range(100):
                while True:
                    try:
                        page = self.lg.yhandler.get_players_raw(self.lg_id, page_ind * 25, "T")
                        page = page["fantasy_content"]["league"][1]["players"]
                        break
                    except:
                        print("Players query crapped out... Waiting 30 seconds and trying again...")
                        time.sleep(30)
                if page == []:
                    break
                for player_ind in range(page["count"]):
                    player = [
                        field
                        for field in page[str(player_ind)]["player"][0]
                        if type(field) == dict
                    ]
                    vals = {}
                    for field in player:
                        vals.update(field)
                    vals["name"] = vals["name"]["full"]
                    vals["eligible_positions"] = [
                        pos["position"] for pos in vals["eligible_positions"]
                    ]
                    vals["bye_weeks"] = vals["bye_weeks"]["week"]
                    players.append(vals)
            # Available Players
            for page_ind in range(100):
                """Accounting for a weird player_id deletion in 2015..."""
                while True:
                    try:
                        page = self.lg.yhandler.get_players_raw(self.lg_id, page_ind * 25, "A")
                        page = page["fantasy_content"]["league"][1]["players"]
                        break
                    except:
                        print("Players query crapped out... Waiting 30 seconds and trying again...")
                        time.sleep(30)
                if page == []:
                    break
                for player_ind in range(page["count"]):
                    player = [
                        field
                        for field in page[str(player_ind)]["player"][0]
                        if type(field) == dict
                    ]
                    vals = {}
                    for field in player:
                        vals.update(field)
                    vals["name"] = vals["name"]["full"]
                    vals["eligible_positions"] = [
                        pos["position"] for pos in vals["eligible_positions"]
                    ]
                    vals["bye_weeks"] = vals["bye_weeks"]["week"]
                    players.append(vals)
            self.players = pd.DataFrame(players)
            self.players.player_id = self.players.player_id.astype(int)
            if not self.players.status.isnull().all():
                break

    def get_fantasy_rosters(self):
        """
        Pulls the current fantasy team of each eligible NFL player 
        and merges it into the players dataframe.
        """
        self.yahoo_client.refresh_oauth()
        selected = pd.DataFrame(
            columns=["player_id", "selected_position", "fantasy_team"]
        )
        for team in self.teams:
            while True:
                try:
                    tm = self.lg.to_team(team["team_key"])
                    players = pd.DataFrame(tm.roster(self.week))
                    break
                except:
                    print("Team roster query crapped out... Waiting 30 seconds and trying again...")
                    time.sleep(30)
            if players.shape[0] == 0:
                continue
            if (~players.player_id.isin(self.players.player_id)).any():
                print(
                    "Some players are missing... "
                    + ", ".join(
                        players.loc[~players.player_id.isin(rosters.player_id), "name"]
                    )
                )
            players["fantasy_team"] = team["name"]
            selected = pd.concat([selected,
                players[["player_id", "selected_position", "fantasy_team"]]],
                ignore_index=True,
                sort=False,
            )
        rosters = pd.merge(
            left=self.players, right=selected, how="left", on="player_id"
        )
        if "fantasy_team" not in rosters.columns:
            rosters["fantasy_team"] = None
        rosters.loc[rosters.player_id == 100014, "name"] += " Rams"
        rosters.loc[rosters.player_id == 100024, "name"] += " Chargers"
        rosters.loc[rosters.player_id == 100020, "name"] += " Jets"
        rosters.loc[rosters.player_id == 100019, "name"] += " Giants"
        rosters = pd.merge(
            left=rosters,
            right=self.nfl_teams[["real_abbrev", "name"]],
            how="left",
            on="name",
        )
        rosters.loc[~rosters.real_abbrev.isnull(), "name"] = rosters.loc[
            ~rosters.real_abbrev.isnull(), "real_abbrev"
        ]
        rosters["position"] = rosters.display_position.apply(
            lambda x: [pos for pos in x.split(',') if pos in ['QB','WR','TE','K','RB','DEF']][0]
        )
        self.players = rosters[
            [
                "name",
                "eligible_positions",
                "selected_position",
                "status",
                "player_id",
                "editorial_team_abbr",
                "fantasy_team",
                "position",
            ]
        ]

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

    def name_corrections(self):
        """
        Applies name corrections between Pro Football Reference and Yahoo.
        """
        self.load_stats((self.season - 2) * 100 + 1, self.season * 100 + self.week - 1)
        corrections = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/name_corrections.csv"
        )
        self.players = pd.merge(
            left=self.players, right=corrections, how="left", on="name"
        )
        to_fix = ~self.players.new_name.isnull()
        self.players.loc[to_fix, "name"] = self.players.loc[to_fix, "new_name"]

    def get_player_ids(self):
        """
        Maps between Yahoo player ID's and SportsRef player ID's based on team rosters and draft results.
        """
        self.nfl_rosters = sr.get_bulk_rosters(self.season - 1,self.latest_season,"NFLRosters.csv")
        self.nfl_rosters = self.nfl_rosters.rename(columns={'player':'name','player_id':'player_id_sr','team':'current_team'})
        self.players = pd.merge(
            left=self.players,right=self.nfl_teams[["real_abbrev", "yahoo"]].rename(
                columns={"yahoo": "editorial_team_abbr", "real_abbrev": "current_team"}
            ),
            how="inner",
            on="editorial_team_abbr",
        )
        self.players = pd.merge(left=self.players,right=self.nfl_rosters[['name','current_team','player_id_sr']].drop_duplicates()\
        .rename(columns={'player':'name','player_id':'player_id_sr','team':'current_team'}),how='left',on=['name','current_team'])
        # Two Michael Carter's on the same team. What are the odds...
        self.players = self.players.loc[~self.players.player_id_sr.isin(['CartMi02'])].reset_index(drop=True)
        id_check = self.players.groupby('player_id_sr').size().to_frame('freq').reset_index()
        if id_check.freq.max() > 1:
            print('Found the same player ID on multiple players: ' + ', '.join(id_check.loc[id_check.freq > 1,'player_id_sr'].tolist()))
        defenses = self.players.position.isin(['DEF'])
        self.players.loc[defenses,'player_id_sr'] = self.players.loc[defenses,'name']
        latest_draft = sr.get_draft(self.latest_season)[['player','player_id','team_abbrev']]\
        .rename(columns={'player':'name','player_id':'player_id_sr','team_abbrev':'current_team'})
        missing = self.players.player_id_sr.isnull() & self.players.name.isin(latest_draft.name.unique())
        unsigned = self.players[missing].reset_index(drop=True)
        del unsigned['player_id_sr']
        unsigned = pd.merge(left=unsigned,right=latest_draft[['name','current_team','player_id_sr']].drop_duplicates(subset=['name'],keep='first'),how='inner',on=['name','current_team'])
        self.players = pd.concat([self.players[~missing],unsigned],ignore_index=True)
        missing = self.players.player_id_sr.isnull() & self.players.name.isin(self.nfl_rosters.name.unique())
        closest = self.players[missing].reset_index(drop=True)
        del closest['player_id_sr'], closest['current_team']
        closest = pd.merge(left=closest,right=self.nfl_rosters[['name','current_team','player_id_sr']].drop_duplicates(subset=['name'],keep='last'),how='inner',on='name')
        self.players = pd.concat([self.players[~missing],closest],ignore_index=True)
        still_missing = self.players.player_id_sr.isnull()
        self.players.loc[still_missing,'player_id_sr'] = self.players.loc[still_missing,'player_id']

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

    def add_injuries(self):
        """
        Adds manual projections for injury timespans. If a new injury pops up 
        and no projection has been provided yet, timespan defaults to one week.
        """
        as_of = self.season * 100 + self.week
        if "until" in self.players.columns:
            del self.players["until"]
        self.players["until"] = float("NaN")
        if as_of < self.latest_season * 100 + self.current_week:
            self.load_stats(self.season * 100 + 1, self.season * 100 + 17)
            self.stats = self.stats.loc[
                self.stats.season * 100 + self.stats.week >= as_of
            ]
            healthy = self.stats.loc[
                self.stats.season * 100 + self.stats.week == as_of, "name"
            ].tolist()
            injured = self.players.loc[
                ~self.players.name.isin(healthy), "name"
            ].tolist()
            for name in injured:
                until = self.stats.loc[self.stats.name == name, "week"].min() - 1
                if not np.isnan(until):
                    self.players.loc[self.players.name == name, "until"] = until
                elif self.season < self.latest_season:
                    self.players.loc[self.players.name == name, "until"] = 17
        if as_of // 100 == self.latest_season:
            inj_proj = pd.read_csv(
                "https://raw.githubusercontent.com/"
                + "tefirman/fantasy-data/main/fantasyfb/injured_list.csv"
            )
            inj_proj = inj_proj.loc[inj_proj.until >= self.current_week]
            self.players = pd.merge(
                left=self.players.rename(columns={"until": "until_orig"}),
                right=inj_proj,
                how="left",
                on=["player_id_sr", "name", "position"],
            )
            if as_of % 100 == self.current_week:
                newInjury = (
                    self.players.status.isin(
                        [
                            "O",
                            "D",
                            "SUSP",
                            "IR",
                            "PUP-R",
                            "PUP-P",
                            "NFI-R",
                            "NA",
                            "COVID-19",
                        ]
                    )
                    & (
                        self.players.until.isnull()
                        | (self.players.until < self.current_week)
                    )
                    & (~self.players.fantasy_team.isnull())
                )  # | (self.players.WAR >= 0))
                if newInjury.sum() > 0:
                    print(
                        "Need to look up new injuries... "
                        + ", ".join(self.players.loc[newInjury, "name"].tolist())
                    )
                    self.players.loc[newInjury, "until"] = self.current_week
                    self.players.loc[newInjury,["player_id_sr","name","position","status"]].to_csv("NewInjuries.csv",index=False)
                oldInjury = (
                    ~self.players.status.isin(
                        [
                            "O",
                            "D",
                            "SUSP",
                            "IR",
                            "PUP-R",
                            "PUP-P",
                            "NFI-R",
                            "NA",
                            "COVID-19",
                        ]
                    )
                    & (self.players.until >= self.current_week)
                    & (~self.players.fantasy_team.isnull())
                )  # | (self.players.WAR >= 0))
                if oldInjury.sum() > 0:
                    print(
                        "Need to update old injuries... "
                        + ", ".join(self.players.loc[oldInjury, "name"].tolist())
                    )
                    self.players.loc[oldInjury,["player_id_sr","name","position"]].to_csv("OldInjuries.csv",index=False)
                    # self.players.loc[oldInjury,'until'] = self.current_week
            self.players["until"] = self.players[["until_orig", "until"]].min(axis=1)
            del self.players["until_orig"]

    def add_bye_weeks(self):
        """
        Derives bye weeks based on the current NFL schedule and merges them to the players dataframe.
        """
        byes = pd.DataFrame()
        for team in self.nfl_schedule.team.unique():
            bye_week = 1
            while (
                (self.nfl_schedule.team == team)
                & (self.nfl_schedule.season == self.season)
                & (self.nfl_schedule.week == bye_week)
            ).any():
                bye_week += 1
            byes = pd.concat([byes,
                pd.DataFrame({"current_team": [team], "bye_week": [bye_week]})], ignore_index=True
            )
        self.players = pd.merge(
            left=self.players, right=byes, how="left", on="current_team"
        )

    def add_roster_pcts(self, inc: int = 25):
        """
        Pulls the percentage of leagues each player is rostered in and merges it into the players dataframe.

        Args:
            inc (int, optional): number of players to pull per API call, defaults to 25.
        """
        self.yahoo_client.refresh_oauth()
        roster_pcts = pd.DataFrame()
        for ind in range(self.players.shape[0] // inc + 1):
            while True:
                try:
                    self.yahoo_client.refresh_oauth()
                    if self.players.iloc[inc * ind : inc * (ind + 1)].shape[0] == 0:
                        pcts = {"count":0}
                        break
                    player_ids = (
                        self.players.iloc[inc * ind : inc * (ind + 1)]
                        .player_id.astype(str)
                        .tolist()
                    )
                    player_ids = [
                        val.split(".")[0] for val in player_ids if val != "nan"
                    ]
                    if len(player_ids) > 0:
                        pcts = self.lg.yhandler.get(
                            "league/{}/players;player_keys={}.p.{}/percent_owned".format(
                                self.lg_id, self.lg_id.split('.')[0], ",{}.p.".format(self.lg_id.split('.')[0]).join(player_ids)
                            )
                        )["fantasy_content"]["league"][1]["players"]
                    else:
                        pcts = {"count":0}
                    break
                except:
                    err_message = traceback.format_exc()
                    print(err_message)
                    print(
                        "Roster percentage query crapped out... Waiting 30 seconds and trying again..."
                    )
                    time.sleep(30)
            for player_ind in range(pcts["count"]):
                player = pcts[str(player_ind)]["player"]
                player_id = [
                    int(val["player_id"]) for val in player[0] if "player_id" in val
                ]
                # full_name = [val["name"]["full"] for val in player[0] if "name" in val]
                pct_owned = [
                    float(val["value"]) / 100.0
                    for val in player[1]["percent_owned"]
                    if "value" in val
                ]
                if len(pct_owned) == 0:
                    # print("Can't find roster percentage for {}...".format(full_name))
                    pct_owned = [0.0]
                roster_pcts = pd.concat([roster_pcts,
                    pd.DataFrame(
                        {
                            "player_id": player_id,
                            # "name": full_name,
                            "pct_rostered": pct_owned,
                        }
                    )],
                    ignore_index=True,
                    sort=False,
                )
        self.players = pd.merge(
            left=self.players, right=roster_pcts, how="left", on=["player_id"]#, "name"]
        )
        self.players.pct_rostered = self.players.pct_rostered.fillna(0.0)
        not_found = (self.players.player_id == self.players.player_id_sr) \
        & (~self.players.fantasy_team.isnull() | (self.players.pct_rostered > 0.0))
        if not_found.any():
            # What about unsigned draft picks??? Maybe look them up individually?
            print(
                "Need to reconcile player names with Pro Football Reference... "
                + ", ".join(self.players.loc[not_found, "name"])
            )

    def add_depth_charts(self):
        """
        Pulls current team depth charts from ESPN and merges them into the players dataframe.
        """
        if self.season == self.latest_season and self.week == self.current_week:
            # Include name corrections here???
            self.players = pd.merge(left=self.players,right=sr.get_all_depth_charts()\
            .rename(columns={'player':'name','pos':'position','team':'current_team'}),\
            how="left",on=["current_team","name",'position'])
            missing = self.players.string.isnull() & ~self.players.position.isin(['DEF']) \
            & ((self.players.pct_rostered > 0.05) | ~self.players.fantasy_team.isnull()) \
            & ~self.players.status.isin(['NA']) & self.players.until.isnull()
            if missing.any():
                print(
                    "Need to reconcile player names with ESPN... "
                    + ", ".join(self.players.loc[missing, "name"])
                )
        else:
            self.load_stats(self.season * 100 + 1, self.season * 100 + 17)
            strings = self.stats.loc[self.stats.season * 100 + self.stats.week >= self.season*100 + self.week]\
            .sort_values(by=['season','week'],ascending=True)[['player_id_sr','string']]\
            .drop_duplicates(subset=['player_id_sr'],keep='first')
            self.players = pd.merge(left=self.players,right=strings,how='left',on=['player_id_sr'])
        self.players.loc[self.players.position == 'DEF','string'] = 1.0
        self.players.string = self.players.string.fillna(2.0)

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
        as_of = self.season * 100 + self.week
        self.yahoo_client.refresh_oauth()
        schedule = pd.DataFrame()
        for team in self.teams:
            tm = self.lg.to_team(team["team_key"])
            limit = (
                max(self.settings["playoff_start_week"], as_of % 100 + 1)
                if as_of
                else self.settings["playoff_start_week"]
            )
            for week in range(1, limit):
                while True:
                    try:
                        matchup = tm.yhandler.get_matchup_raw(tm.team_key, week)
                        matchup = matchup["fantasy_content"]["team"][1]["matchups"]
                        break
                    except:
                        print(
                            "Matchup query crapped out... Waiting 30 seconds and trying again..."
                        )
                        time.sleep(30)
                if "0" in matchup.keys():
                    team_1 = matchup["0"]["matchup"]["0"]["teams"]["0"]["team"]
                    team_2 = matchup["0"]["matchup"]["0"]["teams"]["1"]["team"]
                    schedule = pd.concat([schedule,
                        pd.DataFrame(
                            {
                                "week": [week],
                                "team_1": [team_1[0][2]["name"]],
                                "team_2": [team_2[0][2]["name"]],
                                "score_1": [team_1[1]["team_points"]["total"]],
                                "score_2": [team_2[1]["team_points"]["total"]],
                            }
                        )],
                        ignore_index=True,
                    )
        schedule.score_1 = schedule.score_1.astype(float)
        schedule.score_2 = schedule.score_2.astype(float)

        """ MANY MILE POSTSEASON """
        if os.path.exists("res/football/many_mile.csv"):
            many_mile_sched = pd.read_csv("res/football/many_mile.csv")
        else:
            many_mile_sched = pd.DataFrame(columns=["season", "week"])
        algo = (
            schedule.team_1.isin(["The Algorithm"]).any()
            or schedule.team_2.isin(["The Algorithm"]).any()
        )
        if as_of % 100 >= self.settings["playoff_start_week"] and algo:
            many_mile_sched = many_mile_sched.loc[
                (many_mile_sched.season == as_of // 100)
                & (many_mile_sched.week <= as_of % 100)
            ]
            del many_mile_sched["season"]
            if as_of < self.season*100 + self.current_week:
                many_mile_sched.loc[many_mile_sched.week == as_of % 100, "score_1"] = 0.0
                many_mile_sched.loc[many_mile_sched.week == as_of % 100, "score_2"] = 0.0
            standings = schedule.loc[
                schedule.week < self.settings["playoff_start_week"]
            ].reset_index(drop=True)
            standings["win_1"] = (standings.score_1 > standings.score_2).astype(int)
            standings["win_2"] = 1 - standings.win_1
            standings = pd.concat([standings.rename(
                    columns={col: col.replace("_1", "") for col in standings.columns}
                ),
                standings.rename(
                    columns={col: col.replace("_2", "") for col in standings.columns}
                )],
                ignore_index=True,
                sort=False,
            )
            standings = standings.groupby("team").sum().reset_index()
            standings = standings.sort_values(
                by=["win", "score"], ascending=False, ignore_index=True
            )
            consolation = standings.team.tolist()[6:]
            schedule = schedule.loc[
                (schedule.week < self.settings["playoff_start_week"])
                | ~schedule.team_1.isin(consolation)
            ].reset_index(drop=True)
            schedule = pd.concat([schedule,
                many_mile_sched],
                ignore_index=True,
                sort=False,
            )
        """ MANY MILE POSTSEASON """

        switch = schedule.team_1 > schedule.team_2
        schedule.loc[switch, "temp"] = schedule.loc[switch, "team_1"]
        schedule.loc[switch, "team_1"] = schedule.loc[switch, "team_2"]
        schedule.loc[switch, "team_2"] = schedule.loc[switch, "temp"]
        schedule.loc[switch, "temp"] = schedule.loc[switch, "score_1"].astype(float)
        schedule.loc[switch, "score_1"] = schedule.loc[switch, "score_2"].astype(float)
        schedule.loc[switch, "score_2"] = schedule.loc[switch, "temp"].astype(float)
        schedule = (
            schedule[["week", "team_1", "team_2", "score_1", "score_2"]]
            .drop_duplicates()
            .sort_values(by=["week", "team_1", "team_2"])
            .reset_index(drop=True)
        )
        team_name = [
            team["name"]
            for team in self.teams
            if team["team_key"] == self.lg.team_key()
        ][0]
        schedule["me"] = (schedule["team_1"] == team_name) | (
            schedule["team_2"] == team_name
        )
        if as_of:
            schedule.loc[schedule.week > as_of % 100, "score_1"] = 0.0
            schedule.loc[schedule.week > as_of % 100, "score_2"] = 0.0
            if (
                self.latest_season > as_of // 100
                or as_of % 100 < self.current_week
            ):
                schedule.loc[schedule.week == as_of % 100, "score_1"] = 0.0
                schedule.loc[schedule.week == as_of % 100, "score_2"] = 0.0
        self.schedule = schedule

    def starters(self, week: int):
        """
        Identifies which players should be started on each fantasy team 
        based on fantasy point projections and available roster spots.

        Args:
            week (int, optional): week for which to identify starters.
        """
        as_of = self.season * 100 + self.week
        self.yahoo_client.refresh_oauth()
        self.players = pd.merge(
            left=self.players,
            right=self.nfl_schedule.loc[
                (self.nfl_schedule.season == as_of // 100)
                & (self.nfl_schedule.week == week),
                ["team", "elo_diff"],
            ],
            how="left",
            left_on="current_team",
            right_on="team",
        )
        self.players.elo_diff = self.players.elo_diff.infer_objects(copy=False).fillna(0.0)
        if "opp_elo_weight" not in self.players.columns:
            self.players = pd.merge(left=self.players,right=self.basaloppstringtime,how='left',on='position')
        self.players["opp_factor"] = (self.players['opp_elo_weight'] * self.players["elo_diff"])
        self.players["string_factor"] = self.players['string_weight'] * (1 - self.players["string"])
        self.players["game_factor"] = self.players['basal'] + self.players["opp_factor"] + self.players["string_factor"]
        self.players["points_avg"] = self.players["points_rate"]*self.players["game_factor"]#.fillna(1.0)
        del self.players["team"], self.players["elo_diff"]
        # WAR is linear with points_avg, but slope/intercept depends on position
        # Harder to characterize how WAR varies with points_stdev, ignoring for now...
        self.players = self.players.sort_values(by="points_avg", ascending=False)
        # self.players = self.players.sort_values(by='WAR',ascending=False)
        self.players["starter"] = False
        self.players["injured"] = self.players.until >= week
        if (
            week == as_of % 100
            and as_of // 100 == self.latest_season
            and datetime.datetime.now().month > 8
        ):  # Careful when your draft is in September...
            cutoff = datetime.datetime.now()
            if datetime.datetime.now().hour < 20:
                cutoff -= datetime.timedelta(days=1)
            completed = self.nfl_schedule.loc[
                (self.nfl_schedule.season == as_of // 100)
                & (self.nfl_schedule.week == week)
                & (self.nfl_schedule.date < cutoff),
                "team",
            ].tolist()
            for team in self.teams:
                started = self.players.loc[
                    (self.players.selected_position != "BN")
                    & (self.players.fantasy_team == team["name"])
                    & self.players.current_team.isin(completed)
                ]
                not_available = self.players.loc[
                    (self.players.selected_position == "BN")
                    & (self.players.fantasy_team == team["name"])
                    & self.players.current_team.isin(completed)
                ]
                lineup = pd.merge(left=self.roster_spots,right=started.groupby('selected_position').size()\
                .to_frame('num_started').reset_index().rename(columns={'selected_position':'position'}),how='left',on='position')
                lineup['count'] -= lineup.num_started.fillna(0.0)
                num_pos = lineup.loc[~lineup.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])].set_index('position').to_dict()['count']
                for pos in num_pos:
                    for num in range(int(num_pos[pos])):
                        self.players.loc[
                            self.players.loc[
                                (self.players.fantasy_team == team["name"])
                                & ~self.players.starter
                                & ~self.players.injured
                                & (self.players.bye_week != week)
                                & (self.players.position == pos)
                                & ~self.players.player_id.isin(started.player_id)
                                & ~self.players.player_id.isin(not_available.player_id)
                            ]
                            .iloc[:1]
                            .index,
                            "starter",
                        ] = True
                flex_pos = {"W/T":['WR','TE'],"W/R/T":['WR','RB','TE'],"Q/W/R/T":['WR','RB','TE','QB']}
                for pos in flex_pos:
                    num_flex = int(lineup.loc[lineup.position == pos,'count'].sum())
                    for flex in range(num_flex):
                        self.players.loc[
                            self.players.loc[
                                (self.players.fantasy_team == team["name"])
                                & ~self.players.starter
                                & ~self.players.injured
                                & (self.players.bye_week != week)
                                & self.players.position.isin(flex_pos[pos])
                                & ~self.players.player_id.isin(started.player_id)
                                & ~self.players.player_id.isin(not_available.player_id)
                            ]
                            .iloc[:1]
                            .index,
                            "starter",
                        ] = True
        elif week >= as_of % 100:
            num_pos = self.roster_spots.loc[~self.roster_spots.position.isin(["W/T", "W/R/T", "Q/W/R/T", "BN", "IR"])].set_index('position').to_dict()['count']
            for pos in num_pos:
                for num in range(num_pos[pos]):
                    self.players.loc[
                        self.players.loc[
                            ~self.players.starter
                            & ~self.players.injured
                            & (self.players.bye_week != week)
                            & (self.players.position == pos)
                        ]
                        .drop_duplicates(subset=["fantasy_team"], keep="first")
                        .index,
                        "starter",
                    ] = True
            flex_pos = {"W/T":['WR','TE'],"W/R/T":['WR','RB','TE'],"Q/W/R/T":['WR','RB','TE','QB']}
            for pos in flex_pos:
                num_flex = self.roster_spots.loc[self.roster_spots.position == pos,'count'].sum()
                for flex in range(num_flex):
                    self.players.loc[
                        self.players.loc[
                            ~self.players.starter
                            & ~self.players.injured
                            & (self.players.bye_week != week)
                            & self.players.position.isin(flex_pos[pos])
                        ]
                        .drop_duplicates(subset=["fantasy_team"], keep="first")
                        .index,
                        "starter",
                    ] = True

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
        projections = pd.DataFrame(
            columns=["fantasy_team", "week", "points_avg", "points_var"]
        )
        for week in range(17):
            self.starters(week + 1)
            projections = pd.concat([projections,
                self.players.loc[self.players.starter]
                .groupby("fantasy_team")[["points_avg", "points_var"]]
                .sum()
                .reset_index()],
                ignore_index=True,
                sort=False,
            )
            projections.loc[projections.week.isnull(), "week"] = week + 1
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
        as_of = self.season * 100 + self.week
        self.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.bestball_sims(payouts)
        else:
            orig_standings = self.season_sims(postseason, payouts)[1]
        added_value = pd.DataFrame(
            columns=[
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
            ]
            + (
                ["winner", "runner_up", "third", "earnings"]
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
                if postseason
                else []
            )
        )
        if not team_name:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == self.lg.team_key()
            ][0]
        players_to_drop = self.players.loc[self.players.fantasy_team == team_name]
        if players_to_drop.name.isin(focus_on).sum() > 0:
            players_to_drop = players_to_drop.loc[players_to_drop.name.isin(focus_on)]
        if players_to_drop.name.isin(exclude).sum() > 0:
            players_to_drop = players_to_drop.loc[~players_to_drop.name.isin(exclude)]
        available = self.players.loc[self.players.fantasy_team.isnull() \
        & (self.players.until.isnull() | (self.players.until < 17)) \
        & (self.players.pct_rostered >= min_rostership)].reset_index(drop=True)
        for my_player in players_to_drop.name:
            self.yahoo_client.refresh_oauth(55)
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
                        >= self.players.loc[
                            self.players.name == my_player, "WAR"
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
            for free_agent in possible.name:
                self.players.loc[self.players.name == my_player, "fantasy_team"] = None
                self.players.loc[
                    self.players.name == free_agent, "fantasy_team"
                ] = team_name
                if bestball:
                    new_standings = self.bestball_sims(payouts)
                else:
                    new_standings = self.season_sims(postseason, payouts)[1]
                added_value = pd.concat([added_value,
                    new_standings.loc[new_standings.team == team_name]],
                    ignore_index=True,
                    sort=False,
                )
                added_value.loc[added_value.shape[0] - 1, "player_to_drop"] = my_player
                added_value.loc[added_value.shape[0] - 1, "player_to_add"] = free_agent
                self.players.loc[
                    self.players.name == my_player, "fantasy_team"
                ] = team_name
                self.players.loc[self.players.name == free_agent, "fantasy_team"] = None
            if verbose:
                temp = added_value.iloc[-1 * possible.shape[0] :][
                    ["player_to_drop", "player_to_add", "earnings"]
                ]
                temp["earnings"] -= orig_standings.loc[
                    orig_standings.team == team_name, "earnings"
                ].values[0]
                if temp.shape[0] > 0:
                    print(
                        temp.sort_values(by="earnings", ascending=False).to_string(
                            index=False
                        )
                    )
                del temp
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
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
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
        as_of = self.season * 100 + self.week
        self.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.bestball_sims(payouts)
        else:
            orig_standings = self.season_sims(postseason, payouts)[1]
        added_value = pd.DataFrame(
            columns=[
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
            ]
            + (
                ["winner", "runner_up", "third", "earnings"]
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
                if postseason
                else []
            )
        )
        if not team_name:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == self.lg.team_key()
            ][0]
        available = self.players.loc[self.players.fantasy_team.isnull() \
        & (self.players.until.isnull() | (self.players.until < 17)) \
        & (self.players.pct_rostered >= min_rostership)].reset_index(drop=True)
        possible = available.loc[~available.name.str.contains("Average_")]
        if possible.name.isin(focus_on).sum() > 0:
            possible = possible.loc[possible.name.isin(focus_on)]
        if possible.name.isin(exclude).sum() > 0:
            possible = possible.loc[~possible.name.isin(exclude)]
        possible = possible.groupby("position").head(limit_per)
        for free_agent in possible.name:
            if verbose:
                print("{}, {}".format(free_agent, datetime.datetime.now()))
            self.players.loc[
                self.players.name == free_agent, "fantasy_team"
            ] = team_name
            if bestball:
                new_standings = self.bestball_sims(payouts)
            else:
                new_standings = self.season_sims(postseason, payouts)[1]
            added_value = pd.concat([added_value,
                new_standings.loc[new_standings.team == team_name]],
                ignore_index=True,
                sort=False,
            )
            added_value.loc[added_value.shape[0] - 1, "player_to_add"] = free_agent
            added_value.loc[added_value.shape[0] - 1, "position"] = possible.loc[
                possible.name == free_agent, "position"
            ].values[0]
            added_value.loc[added_value.shape[0] - 1, "current_team"] = possible.loc[
                possible.name == free_agent, "current_team"
            ].values[0]
            self.players.loc[self.players.name == free_agent, "fantasy_team"] = None
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
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
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
        self.yahoo_client.refresh_oauth()
        if bestball:
            orig_standings = self.bestball_sims(payouts)
        else:
            orig_standings = self.season_sims(postseason, payouts)[1]
        reduced_value = pd.DataFrame(
            columns=[
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
            ]
            + (
                ["winner", "runner_up", "third", "earnings"]
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
                if postseason
                else []
            )
        )
        if not team_name:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == self.lg.team_key()
            ][0]
        players_to_drop = self.players.loc[self.players.fantasy_team == team_name]
        if players_to_drop.name.isin(focus_on).sum() > 0:
            players_to_drop = players_to_drop.loc[players_to_drop.name.isin(focus_on)]
        if players_to_drop.name.isin(exclude).sum() > 0:
            players_to_drop = players_to_drop.loc[~players_to_drop.name.isin(exclude)]
        for my_player in players_to_drop.name:
            self.players.loc[self.players.name == my_player, "fantasy_team"] = None
            if bestball:
                new_standings = self.bestball_sims(payouts)
            else:
                new_standings = self.season_sims(postseason, payouts)[1]
            reduced_value = pd.concat([reduced_value,
                new_standings.loc[new_standings.team == team_name]],
                ignore_index=True,
                sort=False,
            )
            reduced_value.loc[reduced_value.shape[0] - 1, "player_to_drop"] = my_player
            self.players.loc[self.players.name == my_player, "fantasy_team"] = team_name
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
                + (
                    ["many_mile"]
                    if (self.schedule.team_1.isin(["The Algorithm"]).any()
                    or self.schedule.team_2.isin(["The Algorithm"]).any()) \
                    and not bestball else []
                )
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
        self.yahoo_client.refresh_oauth()
        if not team_name:
            team_name = [
                team["name"]
                for team in self.teams
                if team["team_key"] == self.lg.team_key()
            ][0]
        my_players = self.players.loc[
            (self.players.fantasy_team == team_name)
            & ~self.players.position.isin(["K", "DEF"])
        ]
        if my_players.name.isin(focus_on).sum() > 0:
            my_players = my_players.loc[my_players.name.isin(focus_on)]
        if my_players.name.isin(exclude).sum() > 0:
            my_players = my_players.loc[~my_players.name.isin(exclude)]
        their_players = self.players.loc[
            (self.players.fantasy_team != team_name)
            & ~self.players.position.isin(["K", "DEF"])
        ]
        if their_players.name.isin(focus_on).sum() > 0:
            their_players = their_players.loc[their_players.name.isin(focus_on)]
        if their_players.name.isin(exclude).sum() > 0:
            their_players = their_players.loc[~their_players.name.isin(exclude)]
        if bestball:
            orig_standings = self.bestball_sims(payouts)
        else:
            orig_standings = self.season_sims(postseason, payouts)[1]

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
            their_team = self.players.loc[
                self.players.name.isin(theirs), "fantasy_team"
            ].values[0]
            self.players.loc[self.players.name.isin(mine), "fantasy_team"] = their_team
            self.players.loc[self.players.name.isin(theirs), "fantasy_team"] = team_name
            my_players = my_players.loc[~my_players.name.isin(given)]
            their_players = their_players.loc[
                (their_players.fantasy_team == their_team)
                & ~their_players.name.isin(given)
            ]
            my_players["WAR"] = 0.0
            their_players["WAR"] = 0.0
        # Make sure there are two teams and narrow down to that teams!!!

        my_added_value = pd.DataFrame()
        their_added_value = pd.DataFrame()
        for my_player in my_players.name:
            self.yahoo_client.refresh_oauth(55)
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
            for their_player in possible.name:
                their_team = self.players.loc[
                    self.players.name == their_player, "fantasy_team"
                ].values[0]
                self.players.loc[
                    self.players.name == my_player, "fantasy_team"
                ] = their_team
                self.players.loc[
                    self.players.name == their_player, "fantasy_team"
                ] = team_name
                if bestball:
                    new_standings = self.bestball_sims(payouts)
                else:
                    new_standings = self.season_sims(postseason, payouts)[1]
                self.players.loc[
                    self.players.name == my_player, "fantasy_team"
                ] = team_name
                self.players.loc[
                    self.players.name == their_player, "fantasy_team"
                ] = their_team
                new_standings["player_to_trade_away"] = my_player
                new_standings["player_to_trade_for"] = their_player
                my_added_value = pd.concat([my_added_value,
                    new_standings.loc[new_standings.team == team_name]],
                    ignore_index=True,
                )
                their_added_value = pd.concat([their_added_value,
                    new_standings.loc[new_standings.team == their_team]],
                    ignore_index=True,
                )
            if verbose and possible.shape[0] > 0:
                me = my_added_value.iloc[-1 * possible.shape[0] :][
                    ["player_to_trade_away", "player_to_trade_for", "earnings"]
                ].rename(columns={"earnings": "my_earnings"})
                them = their_added_value.iloc[-1 * possible.shape[0] :][
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

        if given_check:
            mine = [player for player in given if my_players.name.isin([player]).any()]
            theirs = [
                player for player in given if their_players.name.isin([player]).any()
            ]
            their_team = self.players.loc[
                self.players.name.isin(theirs), "fantasy_team"
            ].values[0]
            self.players.loc[self.players.name.isin(mine), "fantasy_team"] = their_team
            self.players.loc[self.players.name.isin(theirs), "fantasy_team"] = team_name

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


def sendEmail(subject: str, body: str, address: str, filename: str = None):
    """
    Sends an email to the address provided with whichever subject, body, and attachements desired.

    Args:
        subject (str): subject line of the email to be sent.  
        body (str): body text of the email to be sent.  
        address (str): email address to send the message to.  
        filename (str, optional): location of a file to be attached to the email, defaults to None.
    """
    message = MIMEMultipart()
    message["From"] = os.environ["EMAIL_SENDER"]
    message["To"] = address
    message["Subject"] = subject
    message.attach(MIMEText(body + "\n\n", "plain"))
    if filename and os.path.exists(str(filename)):
        with open(filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", "attachment; filename= " + filename.split("/")[-1]
        )
        message.attach(part)
    text = message.as_string()
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(os.environ["EMAIL_SENDER"], os.environ["EMAIL_PW"])
        server.sendmail(os.environ["EMAIL_SENDER"], address, text)


def initialize_inputs():
    """
    Initializing arguments based on command line inputs provided by the user.

    Returns:
        optparse.Values: collection of cleaned input values based on inputs and basic logic.
    """
    parser = optparse.OptionParser()
    parser.add_option(
        "--season",
        action="store",
        type="int",
        dest="season",
        help="season of interest"
    )
    parser.add_option(
        "--week",
        action="store",
        type="int",
        dest="week",
        help="week to project the season from"
    )
    parser.add_option(
        "--name",
        action="store",
        dest="name",
        help="name of team to analyze in the case of multiple teams in a single season",
    )
    parser.add_option(
        "--earliest",
        action="store",
        type="int",
        dest="earliest",
        help="earliest week of stats being considered, e.g. 201807 corresponds to week 7 of the 2018 season",
    )
    parser.add_option(
        "--games",
        action="store",
        type="int",
        dest="games",
        help="number of games to build each player's prior off of",
    )
    parser.add_option(
        "--basaloppstringtime",
        action="store",
        dest="basaloppstringtime",
        help="scaling factors for basal/opponent/depthchart/time factors, comma-separated string of values",
    )
    parser.add_option(
        "--sims", action="store", type="int", dest="sims", help="number of season simulations"
    )
    parser.add_option(
        "--payouts",
        action="store",
        dest="payouts",
        help="comma separated string containing integer payouts for 1st, 2nd, and 3rd",
    )
    parser.add_option(
        "--injurytries",
        action="store",
        type="int",
        dest="injurytries",
        default=10,
        help="number of times to try pulling injury statuses before rolling with it",
    )
    parser.add_option(
        "--bestball",
        action="store_true",
        dest="bestball",
        help="whether to assess the league of interest in the context of bestball (simulates bench contributions better)",
    )
    parser.add_option(
        "--pickups",
        action="store",
        dest="pickups",
        help='assess possible free agent pickups for the players specified ("all" will analyze all possible pickups)',
    )
    parser.add_option(
        "--adds",
        action="store_true",
        dest="adds",
        help="whether to assess possible free agent adds",
    )
    parser.add_option(
        "--drops",
        action="store_true",
        dest="drops",
        help="whether to assess possible drops",
    )
    parser.add_option(
        "--trades",
        action="store",
        dest="trades",
        help='assess possible trades for the players specified ("all" will analyze all possible trades)',
    )
    parser.add_option(
        "--given",
        action="store",
        dest="given",
        help="given players to start with for multi-player trades",
    )
    parser.add_option(
        "--deltas",
        action="store_true",
        dest="deltas",
        help="whether to assess deltas for each matchup of the current week",
    )
    parser.add_option(
        "--output",
        action="store",
        dest="output",
        help="where to save the final projections spreadsheet",
    )
    parser.add_option(
        "--email",
        action="store",
        dest="email",
        help="where to send the final projections spreadsheet",
    )
    options, args = parser.parse_args()
    if not options.season:
        options.season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
    if options.basaloppstringtime:
        options.basaloppstringtime = options.basaloppstringtime.split(",")
        if all([val.isnumeric() for val in options.basaloppstringtime]) and len(options.basal_oppstringtime) == 4:
            options.basaloppstringtime = [float(val) for val in options.basaloppstringtime]
        else:
            print("Invalid rate inference parameters, using defaults...")
            options.basaloppstringtime = None
    if options.payouts:
        options.payouts = options.payouts.split(",")
        if all([val.isnumeric() for val in options.payouts]) and len(options.payouts) == 3:
            options.payouts = [float(val) for val in options.payouts]
        else:
            print("Weird values provided for payouts... Assuming standard payouts...")
            options.payouts = [60.0,30.0,10.0]
    elif options.name == "The Algorithm":
        options.payouts = [720, 360, 120]
    elif options.name == "Toothless Wonders":
        options.payouts = [350, 100, 50]
    elif options.name == "The GENIEs":
        options.payouts = [120, 0, 0]
    elif options.name == "The Great Gadsby's":
        options.payouts = [50, 35, 15]
    else:
        options.payouts = [60.0,30.0,10.0]
    if not options.output:
        options.output = (
            os.path.expanduser("~/Documents/")
            if os.path.exists(os.path.expanduser("~/Documents/"))
            else os.path.expanduser("~/")
        )
        if not os.path.exists(options.output + options.name.replace(" ", "")):
            os.mkdir(options.output + options.name.replace(" ", ""))
        if not os.path.exists(
            options.output + options.name.replace(" ", "") + "/" + str(options.season)
        ):
            os.mkdir(
                options.output
                + options.name.replace(" ", "")
                + "/"
                + str(options.season)
            )
        options.output += options.name.replace(" ", "") + "/" + str(options.season)
    if options.output[-1] != "/":
        options.output += "/"
    return options


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
            sendEmail(
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
