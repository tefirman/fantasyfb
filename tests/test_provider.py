"""Tests for the NflreadpyProvider data backend.

These exercise the canonical schema fantasyfb expects from any
NFLDataProvider, plus a handful of value-level invariants (spread sign
convention, team-code consistency between schedule and team_aliases) that
have bitten us during the sportsref_nfl -> nflreadpy migration.
"""

from __future__ import annotations

import pandas as pd
import pytest


REQUIRED_STAT_COLS = {
    "player_id_sr", "name", "position", "team", "opponent",
    "season", "week", "game_id", "points_allowed",
    "rush_yds", "rush_att", "rush_td", "rush_first_down",
    "rec", "rec_yds", "rec_td", "rec_first_down",
    "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
    "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
    "kick_ret_td", "punt_ret_td", "xpm", "fgm",
    "sacks", "def_int", "fumbles_rec", "def_int_td", "fumbles_rec_td",
}

REQUIRED_SCHEDULE_COLS = {
    "season", "week", "date", "team", "home_away",
    "opp_team", "elo_diff", "opp_elo",
}


class TestPlayerStats:
    def test_returns_rows(self, stats: pd.DataFrame) -> None:
        assert len(stats) > 500

    def test_required_columns_present(self, stats: pd.DataFrame) -> None:
        missing = REQUIRED_STAT_COLS - set(stats.columns)
        assert not missing, f"missing columns: {missing}"

    def test_six_fantasy_positions_present(self, stats: pd.DataFrame) -> None:
        assert {"QB", "RB", "WR", "TE", "K", "DEF"}.issubset(stats.position.unique())

    def test_defenses_have_points_allowed(self, stats: pd.DataFrame) -> None:
        defenses = stats[stats.position == "DEF"]
        assert len(defenses) >= 32
        assert defenses["points_allowed"].notna().all()

    def test_defense_sacks_in_plausible_range(self, stats: pd.DataFrame) -> None:
        defenses = stats[stats.position == "DEF"]
        assert defenses["sacks"].between(0, 12).all()

    def test_yyyyww_range_respected(self, stats: pd.DataFrame) -> None:
        as_of = stats.season * 100 + stats.week
        assert as_of.min() >= 202401
        assert as_of.max() <= 202404


class TestSchedule:
    def test_returns_rows(self, schedule: pd.DataFrame) -> None:
        assert len(schedule) > 500

    def test_required_columns_present(self, schedule: pd.DataFrame) -> None:
        missing = REQUIRED_SCHEDULE_COLS - set(schedule.columns)
        assert not missing, f"missing columns: {missing}"

    def test_home_and_away_rows_balanced(self, schedule: pd.DataFrame) -> None:
        home = (schedule.home_away == "Home").sum()
        away = (schedule.home_away == "Away").sum()
        assert home == away

    def test_home_favorite_has_positive_elo_diff(self, schedule: pd.DataFrame) -> None:
        # KC hosted BAL in 2024 W1 as a 3-point favorite. The legacy
        # convention is positive elo_diff for the favored team.
        kc_w1 = schedule[
            (schedule.season == 2024) & (schedule.week == 1) & (schedule.team == "KC")
        ]
        assert not kc_w1.empty
        assert float(kc_w1.iloc[0]["elo_diff"]) > 0


class TestRosters:
    def test_returns_rows(self, rosters: pd.DataFrame) -> None:
        assert len(rosters) > 1000

    def test_yahoo_id_column_present(self, rosters: pd.DataFrame) -> None:
        assert "yahoo_id" in rosters.columns

    def test_yahoo_id_populated_for_majority(self, rosters: pd.DataFrame) -> None:
        # The whole point of the swap was to get yahoo_id directly. If the
        # population rate craters, the cleanest signal that nflverse
        # changed its roster schema again.
        assert rosters["yahoo_id"].notna().mean() > 0.5

    def test_player_id_in_gsis_format(self, rosters: pd.DataFrame) -> None:
        gsis_match = rosters["player_id_sr"].astype(str).str.match(r"^00-\d{7}$")
        assert gsis_match.mean() > 0.9


class TestDepthCharts:
    def test_returns_rows(self, depth_charts: pd.DataFrame) -> None:
        assert len(depth_charts) > 100

    def test_required_columns_present(self, depth_charts: pd.DataFrame) -> None:
        required = {"name", "current_team", "position", "string", "player_id_sr"}
        assert required.issubset(depth_charts.columns)

    def test_string_column_populated_and_numeric(self, depth_charts: pd.DataFrame) -> None:
        assert depth_charts["string"].notna().all()
        assert pd.api.types.is_numeric_dtype(depth_charts["string"])

    def test_fantasy_positions_present(self, depth_charts: pd.DataFrame) -> None:
        positions = set(depth_charts["position"].dropna().unique())
        assert {"QB", "RB", "WR", "TE"}.issubset(positions)


class TestTeamAliases:
    def test_returns_thirty_two_teams(self, team_aliases: pd.DataFrame) -> None:
        assert len(team_aliases) == 32

    def test_required_columns_present(self, team_aliases: pd.DataFrame) -> None:
        assert {"yahoo", "real_abbrev"}.issubset(team_aliases.columns)

    def test_alias_codes_match_schedule_codes(
        self, team_aliases: pd.DataFrame, schedule: pd.DataFrame
    ) -> None:
        # This is the regression that bit us during the swap: legacy
        # team_abbrevs.csv used PFR-style real_abbrev (CRD, RAV, ...) while
        # nflreadpy uses standard NFL codes (ARI, BAL, ...). Asserting
        # equality keeps that class of bug from coming back.
        schedule_teams = set(schedule["team"].unique())
        alias_teams = set(team_aliases["real_abbrev"].unique())
        assert schedule_teams == alias_teams, (
            f"in schedule not aliases: {schedule_teams - alias_teams}; "
            f"in aliases not schedule: {alias_teams - schedule_teams}"
        )


class TestDraft:
    def test_returns_rows(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert len(draft) >= 200

    def test_required_columns_present(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert {"name", "current_team", "player_id_sr"}.issubset(draft.columns)

    def test_first_overall_pick(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert "Caleb Williams" in draft["name"].tolist()
