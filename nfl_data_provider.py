"""
NFL data provider interface.

Defines the contract that every concrete NFL data backend must satisfy so
that the rest of fantasyfb is decoupled from any specific source (PFR,
nflreadpy, ESPN, etc.).

The canonical column schema returned by each method is documented on the
method itself. Concrete providers are responsible for translating their
upstream schema into this canonical one.
"""

from abc import ABC, abstractmethod

import pandas as pd


class NFLDataProvider(ABC):
    """Abstract base for NFL data backends.

    The legacy column name `player_id_sr` is preserved as the canonical
    cross-table player identifier. Concrete providers are free to populate
    it with whatever ID system they natively use (PFR id, GSIS id, etc.) as
    long as the same value joins stats, rosters, and depth charts.
    """

    @abstractmethod
    def get_player_stats(self, start: int, finish: int) -> pd.DataFrame:
        """Per-game player + team-defense stats for the YYYYWW range.

        Required columns:
            player_id_sr, name, position, team, opponent,
            season, week, game_id, points_allowed,
            rush_yds, rush_att, rush_td, rush_first_down,
            rec, rec_yds, rec_td, rec_first_down,
            pass_yds, pass_cmp, pass_td, pass_first_down, pass_int,
            fumbles_lost, kick_ret_yds, punt_ret_yds,
            kick_ret_td, punt_ret_td, xpm, fgm,
            sacks, def_int, fumbles_rec, def_int_td, fumbles_rec_td

        Defenses are emitted as one row per team-week with
        position == "DEF" and player_id_sr set to the team abbreviation.
        """

    @abstractmethod
    def get_schedule(self, start_year: int, end_year: int) -> pd.DataFrame:
        """NFL schedule with one row per team-game (two rows per game).

        Required columns:
            season, week, date, team, home_away, opp_team,
            elo_diff, opp_elo

        elo_diff and opp_elo carry forward the legacy "opponent strength"
        signal. Providers without true Elo ratings should map a strength
        proxy (e.g. Vegas spread) into elo_diff with consistent sign:
        positive elo_diff means the team is favored.
        """

    @abstractmethod
    def get_rosters(self, start_year: int, end_year: int) -> pd.DataFrame:
        """Active rosters for the year range.

        Required columns:
            name, current_team, position, player_id_sr

        Optional columns (populated when available):
            yahoo_id  -- enables direct Yahoo->NFL ID linkage
        """

    @abstractmethod
    def get_depth_charts(self) -> pd.DataFrame:
        """Current-week depth charts.

        Required columns:
            name, current_team, position, string

        `string` follows the legacy convention: 1.0 = starter, 2.0 = backup,
        3.0 = third string, etc.
        """

    @abstractmethod
    def get_draft(self, year: int) -> pd.DataFrame:
        """Draft picks for the given year.

        Required columns:
            name, current_team, player_id_sr
        """

    @abstractmethod
    def team_aliases(self) -> pd.DataFrame:
        """Translation table between Yahoo and provider-native team codes.

        Required columns:
            yahoo        -- value Yahoo emits as `editorial_team_abbr`
            real_abbrev  -- provider-native team code (matches the `team`
                            column returned by get_player_stats and
                            get_schedule)

        The column names mirror the legacy team_abbrevs.csv schema so that
        existing callers reading `nfl_teams.real_abbrev` keep working; the
        values now point at the active backend rather than at PFR.
        """
