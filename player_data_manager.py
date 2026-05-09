"""
Player data management for fantasy football.

This module handles player ID mapping, name corrections, injury tracking,
bye weeks, roster percentages, and depth chart integration.
"""

import datetime
import time
import traceback
from typing import Optional

import numpy as np
import pandas as pd

from nfl_data_provider import NFLDataProvider


class PlayerDataManager:
    """
    Manages all player data operations including ID mapping, corrections, and enrichment.
    """
    
    def __init__(self, yahoo_client, season: int, current_week: int,
                 nfl_provider: NFLDataProvider):
        """
        Initialize the player data manager.

        Args:
            yahoo_client: YahooFantasyClient instance
            season: Current NFL season
            current_week: Current week in season
            nfl_provider: Pluggable NFL data backend.
        """
        self.yahoo_client = yahoo_client
        self.season = season
        self.current_week = current_week
        self.nfl_provider = nfl_provider
        self.latest_season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        self.nfl_teams = self.nfl_provider.team_aliases()
        
    def apply_name_corrections(self, players: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
        """
        Apply legacy name corrections between the historical roster feed and Yahoo.

        Largely a no-op since the swap to nflreadpy: Yahoo<->NFL linkage now
        happens via yahoo_id in map_player_ids, not name matching. The
        corrections CSV survives to catch any pre-2024 backfills that
        still reference legacy spellings.

        Args:
            players: DataFrame with Yahoo player data
            stats: DataFrame with NFL stats from the active provider

        Returns:
            DataFrame with corrected player names
        """
        corrections = pd.read_csv(
            "https://raw.githubusercontent.com/"
            + "tefirman/fantasy-data/main/fantasyfb/name_corrections.csv"
        )
        players = pd.merge(
            left=players, right=corrections, how="left", on="name"
        )
        to_fix = ~players.new_name.isnull()
        players.loc[to_fix, "name"] = players.loc[to_fix, "new_name"]
        
        # Clean up temporary column
        if 'new_name' in players.columns:
            del players['new_name']
            
        return players

    def map_player_ids(self, players: pd.DataFrame) -> pd.DataFrame:
        """
        Map Yahoo player IDs to NFL player IDs.

        nflreadpy's weekly roster feed carries the Yahoo player ID directly,
        so we can join on that instead of the legacy name-matching cascade.
        That eliminates the bespoke name_corrections.csv layer that used to
        be required because Pro Football Reference and Yahoo disagreed on
        player spellings.

        Args:
            players: DataFrame with Yahoo player data

        Returns:
            DataFrame with mapped player IDs
        """
        nfl_rosters = self.nfl_provider.get_rosters(self.season - 1, self.latest_season)

        # Map Yahoo team abbreviations -> NFL team abbreviations.
        players = pd.merge(
            left=players,
            right=self.nfl_teams[["real_abbrev", "yahoo"]].rename(
                columns={"yahoo": "editorial_team_abbr", "real_abbrev": "current_team"}
            ),
            how="inner",
            on="editorial_team_abbr",
        )

        if "yahoo_id" in nfl_rosters.columns:
            # Preferred path: exact ID join. Take the most recent roster
            # entry per yahoo_id to handle mid-season team changes.
            roster_by_yid = (
                nfl_rosters.dropna(subset=["yahoo_id"])
                .assign(yahoo_id=lambda d: d["yahoo_id"].astype(str))
                .sort_values("season")
                .drop_duplicates(subset=["yahoo_id"], keep="last")
                [["yahoo_id", "player_id_sr"]]
            )
            players = players.assign(yahoo_id=players["player_id"].astype(str)).merge(
                roster_by_yid, on="yahoo_id", how="left"
            )
            del players["yahoo_id"]
        else:
            # Fallback: name + team match.
            players = players.merge(
                nfl_rosters[["name", "current_team", "player_id_sr"]].drop_duplicates(),
                on=["name", "current_team"], how="left",
            )

        # Defenses use the team abbreviation as their ID.
        defenses = players["position"].isin(["DEF"])
        players.loc[defenses, "player_id_sr"] = players.loc[defenses, "name"]

        # Surface duplicate IDs so we can flag data-quality regressions early.
        id_check = players.groupby("player_id_sr").size().to_frame("freq").reset_index()
        if not id_check.empty and id_check.freq.max() > 1:
            print("Found the same player ID on multiple players: " +
                  ", ".join(id_check.loc[id_check.freq > 1, "player_id_sr"].astype(str).tolist()))

        # Final fallback: anyone we still couldn't link gets their Yahoo ID
        # so downstream joins on player_id_sr don't drop them entirely.
        still_missing = players["player_id_sr"].isnull()
        players.loc[still_missing, "player_id_sr"] = players.loc[still_missing, "player_id"]

        return players

    def add_injuries(self, players: pd.DataFrame, week: int) -> pd.DataFrame:
        """
        Add manual projections for injury timespans.
        
        Args:
            players: DataFrame with player data
            week: Current week being analyzed
            
        Returns:
            DataFrame with injury information added
        """
        as_of = self.season * 100 + week
        
        if "until" in players.columns:
            del players["until"]
        players["until"] = float("NaN")
        
        # For past seasons, infer from actual game participation
        if as_of < self.latest_season * 100 + self.current_week:
            # This would require loading stats - simplified for now
            # In the full implementation, you'd load stats and check participation
            pass
            
        # For current season, use injury projections
        if as_of // 100 == self.latest_season:
            inj_proj = pd.read_csv(
                "https://raw.githubusercontent.com/"
                + "tefirman/fantasy-data/main/fantasyfb/injured_list.csv"
            )
            inj_proj = inj_proj.loc[inj_proj.until >= self.current_week]
            
            players = pd.merge(
                left=players.rename(columns={"until": "until_orig"}),
                right=inj_proj,
                how="left",
                on=["player_id_sr", "name", "position"],
            )
            
            if as_of % 100 == self.current_week:
                # Check for new injuries
                new_injury = (
                    players.status.isin([
                        "O", "D", "SUSP", "IR", "PUP-R", "PUP-P", "NFI-R", "NA", "COVID-19"
                    ])
                    & (players.until.isnull() | (players.until < self.current_week))
                    & (~players.fantasy_team.isnull())
                )
                
                if new_injury.any():
                    print("Need to look up new injuries... " + 
                          ", ".join(players.loc[new_injury, "name"].tolist()))
                    players.loc[new_injury, "until"] = self.current_week
                    players.loc[new_injury, ["player_id_sr","name","position","status"]].to_csv(
                        "NewInjuries.csv", index=False
                    )
                
                # Check for recovered players
                old_injury = (
                    ~players.status.isin([
                        "O", "D", "SUSP", "IR", "PUP-R", "PUP-P", "NFI-R", "NA", "COVID-19"
                    ])
                    & (players.until >= self.current_week)
                    & (~players.fantasy_team.isnull())
                )
                
                if old_injury.any():
                    print("Need to update old injuries... " + 
                          ", ".join(players.loc[old_injury, "name"].tolist()))
                    players.loc[old_injury, ["player_id_sr","name","position"]].to_csv(
                        "OldInjuries.csv", index=False
                    )
            
            players["until"] = players[["until_orig", "until"]].min(axis=1)
            if "until_orig" in players.columns:
                del players["until_orig"]
        
        return players

    def add_bye_weeks(self, players: pd.DataFrame, nfl_schedule: pd.DataFrame) -> pd.DataFrame:
        """
        Derive bye weeks based on the current NFL schedule.
        
        Args:
            players: DataFrame with player data
            nfl_schedule: NFL schedule DataFrame
            
        Returns:
            DataFrame with bye week information added
        """
        byes = pd.DataFrame()
        for team in nfl_schedule.team.unique():
            bye_week = 1
            while (
                (nfl_schedule.team == team)
                & (nfl_schedule.season == self.season)
                & (nfl_schedule.week == bye_week)
            ).any():
                bye_week += 1
            byes = pd.concat([
                byes,
                pd.DataFrame({"current_team": [team], "bye_week": [bye_week]})
            ], ignore_index=True)
        
        players = pd.merge(
            left=players, right=byes, how="left", on="current_team"
        )
        
        return players

    def add_roster_percentages(self, players: pd.DataFrame, lg_id: str, inc: int = 25) -> pd.DataFrame:
        """
        Pull the percentage of leagues each player is rostered in.
        
        Args:
            players: DataFrame with player data
            lg_id: League ID for Yahoo API
            inc: Number of players to pull per API call
            
        Returns:
            DataFrame with roster percentage information added
        """
        self.yahoo_client.refresh_oauth()
        roster_pcts = pd.DataFrame()
        
        for ind in range(players.shape[0] // inc + 1):
            while True:
                try:
                    self.yahoo_client.refresh_oauth()
                    chunk = players.iloc[inc * ind : inc * (ind + 1)]
                    
                    if chunk.shape[0] == 0:
                        pcts = {"count": 0}
                        break
                    
                    player_ids = chunk.player_id.astype(str).tolist()
                    player_ids = [val.split(".")[0] for val in player_ids if val != "nan"]
                    
                    if len(player_ids) > 0:
                        pcts = self.yahoo_client.lg.yhandler.get(
                            "league/{}/players;player_keys={}.p.{}/percent_owned".format(
                                lg_id, 
                                lg_id.split('.')[0], 
                                ",{}.p.".format(lg_id.split('.')[0]).join(player_ids)
                            )
                        )["fantasy_content"]["league"][1]["players"]
                    else:
                        pcts = {"count": 0}
                    break
                    
                except:
                    err_message = traceback.format_exc()
                    print(err_message)
                    print("Roster percentage query failed... Waiting 30 seconds and trying again...")
                    time.sleep(30)
            
            for player_ind in range(pcts["count"]):
                player = pcts[str(player_ind)]["player"]
                player_id = [int(val["player_id"]) for val in player[0] if "player_id" in val]
                pct_owned = [
                    float(val["value"]) / 100.0
                    for val in player[1]["percent_owned"]
                    if "value" in val
                ]
                if len(pct_owned) == 0:
                    pct_owned = [0.0]
                
                roster_pcts = pd.concat([
                    roster_pcts,
                    pd.DataFrame({
                        "player_id": player_id,
                        "pct_rostered": pct_owned,
                    })
                ], ignore_index=True, sort=False)
        
        players = pd.merge(
            left=players, right=roster_pcts, how="left", on=["player_id"]
        )
        players.pct_rostered = players.pct_rostered.fillna(0.0)
        
        # Check for unmapped players
        not_found = (
            (players.player_id == players.player_id_sr) 
            & (~players.fantasy_team.isnull() | (players.pct_rostered > 0.0))
        )
        if not_found.any():
            print("Need to reconcile player names with nflreadpy... " +
                  ", ".join(players.loc[not_found, "name"]))
        
        return players

    def add_depth_charts(self, players: pd.DataFrame, week: int) -> pd.DataFrame:
        """
        Pull current team depth charts from ESPN and merge into players DataFrame.
        
        Args:
            players: DataFrame with player data
            week: Current week being analyzed
            
        Returns:
            DataFrame with depth chart information added
        """
        # Always load the current depth chart, regardless of which season
        # the user is analyzing. The previous gate (only loading for
        # current season + current week) made sense in a world where we
        # had historical depth charts to fall back on, but we don't --
        # nflreadpy only ships current depth charts and the alternative
        # was every offensive player getting fillna(2.0), which silently
        # imposed a ~50% backup penalty on every legitimate starter for
        # any non-current-season analysis. Today's depth chart is the best
        # info we have; trust it.
        depth = self.nfl_provider.get_depth_charts()
        id_join = depth.dropna(subset=["player_id_sr"])[["player_id_sr", "string"]]
        players = players.merge(id_join, on="player_id_sr", how="left")

        still_unset = players["string"].isnull()
        if still_unset.any():
            name_join = depth[["name", "current_team", "position", "string"]].rename(
                columns={"string": "string_name"}
            )
            players = players.merge(
                name_join, on=["name", "current_team", "position"], how="left"
            )
            players.loc[still_unset, "string"] = players.loc[still_unset, "string_name"]
            if "string_name" in players.columns:
                del players["string_name"]

        # Surface unmapped fantasy-relevant players so name drift
        # (especially for newly-signed players) gets flagged early.
        if self.season == self.latest_season and week == self.current_week:
            missing = (
                players.string.isnull()
                & ~players.position.isin(['DEF'])
                & ((players.pct_rostered > 0.05) | ~players.fantasy_team.isnull())
                & ~players.status.isin(['NA'])
                & players.until.isnull()
            )
            if missing.any():
                print("Need to reconcile player names with ESPN... " +
                      ", ".join(players.loc[missing, "name"]))

        # Set defaults
        players.loc[players.position == 'DEF', 'string'] = 1.0
        players.string = players.string.fillna(2.0)

        return players

    def process_players(self, players: pd.DataFrame, stats: pd.DataFrame, 
                       nfl_schedule: pd.DataFrame, lg_id: str, week: int) -> pd.DataFrame:
        """
        Run the complete player data processing pipeline.
        
        Args:
            players: Raw Yahoo player data
            stats: NFL stats from the active provider, used by the
                   legacy name-correction step
            nfl_schedule: NFL schedule for bye weeks
            lg_id: League ID for roster percentages
            week: Current week being analyzed
            
        Returns:
            Fully processed player DataFrame
        """
        print("Applying name corrections...")
        players = self.apply_name_corrections(players, stats)
        
        print("Mapping player IDs...")
        players = self.map_player_ids(players)
        
        print("Adding injury information...")
        players = self.add_injuries(players, week)
        
        print("Adding bye weeks...")
        players = self.add_bye_weeks(players, nfl_schedule)
        
        print("Adding roster percentages...")
        players = self.add_roster_percentages(players, lg_id)
        
        print("Adding depth charts...")
        players = self.add_depth_charts(players, week)
        
        return players
