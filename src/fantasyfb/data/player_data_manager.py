"""
Player data management for fantasy football.

This module handles player ID mapping, name corrections, injury tracking,
bye weeks, roster percentages, and depth chart integration.
"""

import datetime
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from .nfl_provider import NFLDataProvider
from .platform_client import FantasyPlatformClient

# injured_list.csv lives outside nflreadpy's caching entirely (a hardcoded
# raw.githubusercontent.com fetch), so it always hits the network with no
# local fallback. OSError covers a dead network here: urllib.error.URLError
# (bare urllib, what pandas uses by default) and requests' connection
# errors both subclass it. It's optional enrichment, so it's correct to
# skip and warn rather than crash a draft-prep run that's otherwise
# working entirely from nflreadpy's own persistent cache.


class PlayerDataManager:
    """
    Manages all player data operations including ID mapping, corrections, and enrichment.
    """
    
    def __init__(self, client: FantasyPlatformClient, season: int, current_week: int,
                 nfl_provider: NFLDataProvider):
        """
        Initialize the player data manager.

        Args:
            client: FantasyPlatformClient instance
            season: Current NFL season
            current_week: Current week in season
            nfl_provider: Pluggable NFL data backend.
        """
        self.client = client
        self.season = season
        self.current_week = current_week
        self.nfl_provider = nfl_provider
        self.latest_season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        self.nfl_teams = self.nfl_provider.team_aliases()
        
    def map_player_ids(self, players: pd.DataFrame) -> pd.DataFrame:
        """
        Map platform player IDs to NFL player IDs.

        nflreadpy's weekly roster feed carries the Yahoo player ID directly,
        so we can join on that instead of the legacy name-matching cascade.
        That eliminates the bespoke name_corrections.csv layer that used to
        be required because Pro Football Reference and Yahoo disagreed on
        player spellings.

        Non-Yahoo clients (e.g. Sleeper) already resolve player_id_sr
        themselves (via gsis_id) and use real NFL team codes directly in
        editorial_team_abbr rather than Yahoo's own abbreviations, so the
        Yahoo-team-code translation and yahoo_id join are skipped for them;
        the name+team fallback below still runs to backfill anyone their
        client-side ID resolution missed.

        Args:
            players: DataFrame with player data from the active platform client

        Returns:
            DataFrame with mapped player IDs
        """
        nfl_rosters = self.nfl_provider.get_rosters(self.season - 1, self.latest_season)
        client_resolved_ids = "player_id_sr" in players.columns and players["player_id_sr"].notna().any()

        if client_resolved_ids:
            # editorial_team_abbr is already a real NFL code (Sleeper); no
            # Yahoo-team-code translation or yahoo_id join needed -- the
            # client already populated player_id_sr via its own native ID.
            players = players.rename(columns={"editorial_team_abbr": "current_team"})
        else:
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
                players["player_id_sr"] = pd.NA

        # Name+team fallback for anyone the primary join missed. The
        # yahoo_id column comes from a static cross-reference inside
        # nflverse that's not backfilled the moment a rookie hits a
        # roster -- the 2025 rookie class as of mid-2026, for instance,
        # is in nflreadpy's roster feed with valid gsis_ids but ~half of
        # them still have null yahoo_id. Without this fallback those
        # players fail to link and surface as "needs reconcile" noise on
        # every pre-draft run.
        unmapped = players["player_id_sr"].isnull()
        if unmapped.any():
            name_join = (
                nfl_rosters.dropna(subset=["player_id_sr"])
                .sort_values("season")
                .drop_duplicates(subset=["name", "current_team"], keep="last")
                [["name", "current_team", "player_id_sr"]]
                .rename(columns={"player_id_sr": "_pid_sr_byname"})
            )
            players = players.merge(
                name_join, on=["name", "current_team"], how="left",
            )
            fill = players["player_id_sr"].isnull() & players["_pid_sr_byname"].notna()
            players.loc[fill, "player_id_sr"] = players.loc[fill, "_pid_sr_byname"]
            del players["_pid_sr_byname"]

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
        players.loc[still_missing, "player_id_sr"] = players.loc[still_missing, "player_id"].astype(str)

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
            try:
                inj_proj = pd.read_csv(
                    "https://raw.githubusercontent.com/"
                    + "tefirman/fantasy-data/main/fantasyfb/injured_list.csv"
                )
            except OSError:
                warnings.warn(
                    "Could not reach injured_list.csv (offline?); skipping "
                    "manual injury-timespan projections.",
                )
                return players
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

    def add_roster_percentages(self, players: pd.DataFrame, inc: int = 25) -> pd.DataFrame:
        """
        Pull the percentage of leagues each player is rostered in.

        Args:
            players: DataFrame with player data
            inc: Number of players to pull per API call

        Returns:
            DataFrame with roster percentage information added. Backends
            with no ownership-percentage concept (e.g. Sleeper) get
            pct_rostered = 0.0 for every player -- callers filtering on
            min_rostership should pass 0.0 explicitly for those leagues.
        """
        roster_pcts = self.client.get_roster_percentages(players, chunk_size=inc)
        if roster_pcts is None:
            players = players.copy()
            players["pct_rostered"] = 0.0
            return players

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
        Pull current team depth charts from nflreadpy and merge into players DataFrame.
        
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
        id_join = depth.dropna(subset=["player_id_sr"])[
            ["player_id_sr", "string", "current_team"]
        ].rename(columns={"current_team": "current_team_depth"})
        players = players.merge(id_join, on="player_id_sr", how="left")
        matched_by_id = players["current_team_depth"].notnull()
        players.loc[matched_by_id, "current_team"] = players.loc[
            matched_by_id, "current_team_depth"
        ]
        del players["current_team_depth"]

        still_unset = players["string"].isnull()
        if still_unset.any():
            # Join on name/position only here, not current_team -- current_team
            # is exactly what's stale for a player who changed teams before
            # nflverse's season roster snapshot caught up, so requiring it to
            # already match would defeat this fallback for those players.
            # Dedupe on (name, position) first since depth charts can have
            # rare same-name/same-position collisions across teams, and a
            # duplicated join key would fan out rows in players.
            name_join = depth[["name", "current_team", "position", "string"]].rename(
                columns={"string": "string_name", "current_team": "current_team_name"}
            ).drop_duplicates(subset=["name", "position"], keep="first")
            players = players.merge(
                name_join, on=["name", "position"], how="left"
            )
            players.loc[still_unset, "string"] = players.loc[still_unset, "string_name"]
            players.loc[still_unset, "current_team"] = players.loc[
                still_unset, "current_team_name"
            ].combine_first(players.loc[still_unset, "current_team"])
            for col in ("string_name", "current_team_name"):
                if col in players.columns:
                    del players[col]

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
                print("Need to reconcile player names with nflreadpy depth charts... " +
                      ", ".join(players.loc[missing, "name"]))

        # Set defaults
        players.loc[players.position == 'DEF', 'string'] = 1.0
        players.string = players.string.fillna(2.0)

        return players

    def process_players(self, players: pd.DataFrame,
                       nfl_schedule: pd.DataFrame, week: int) -> pd.DataFrame:
        """
        Run the complete player data processing pipeline.

        Args:
            players: Raw player data from the active platform client
            nfl_schedule: NFL schedule for bye weeks
            week: Current week being analyzed

        Returns:
            Fully processed player DataFrame
        """
        print("Mapping player IDs...")
        players = self.map_player_ids(players)

        print("Adding injury information...")
        players = self.add_injuries(players, week)

        print("Adding bye weeks...")
        players = self.add_bye_weeks(players, nfl_schedule)

        print("Adding roster percentages...")
        players = self.add_roster_percentages(players)

        print("Adding depth charts...")
        players = self.add_depth_charts(players, week)
        
        return players
