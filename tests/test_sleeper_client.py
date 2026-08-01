"""Tests for the Sleeper API client's translation logic.

fetch_league() itself is a thin requests.get() wrapper, so it's mocked out
rather than hitting the real (public, no-auth) Sleeper API in CI. The
scoring/roster translation is the part worth covering: mapping Sleeper's
stat-key vocabulary onto fantasyfb's internal scoring schema.
"""

from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

from fantasyfb.data import sleeper_client


# Trimmed version of the real #SFB16 scoring_settings payload (league
# 1367870433398915072), keeping only keys relevant to translation coverage.
SFB16_SCORING_SETTINGS = {
    "pass_yd": 0.04, "pass_cmp": 0.0, "pass_td": 6.0, "pass_fd": 0.0,
    "pass_int": 0.0, "pass_2pt": 2.0,
    "bonus_pass_yd_300": 10.0, "bonus_pass_yd_400": 20.0,
    "rush_yd": 0.1, "rush_att": 0.0, "rush_td": 6.0, "rush_fd": 0.5,
    "rush_2pt": 2.0,
    "bonus_rush_yd_100": 0.0, "bonus_rush_yd_200": 0.0,
    "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "rec_fd": 0.5, "rec_2pt": 2.0,
    "bonus_rec_yd_100": 0.0, "bonus_rec_yd_200": 0.0,
    "bonus_rush_rec_yd_100": 10.0, "bonus_rush_rec_yd_200": 20.0,
    "bonus_rec_te": 1.0, "bonus_fd_te": 1.0,
    "fum_lost": 0.0, "fum_rec_td": 6.0,
    "st_td": 6.0, "def_st_td": 6.0,
    "kr_yd": 0.0, "pr_yd": 0.0,
    "sack": 0.0, "int": 0.0, "fum_rec": 0.0, "safe": 0.0, "blk_kick": 0.0,
    "fgm_0_19": 0.0, "xpm": 0.0,
    "pts_allow_0": 0.0,
    # per-play "long play" bonuses -- intentionally unsupported
    "pass_cmp_40p": 10.0, "rush_40p": 10.0, "rec_40p": 10.0,
}

SFB16_ROSTER_POSITIONS = ["FLEX"] * 8 + ["SUPER_FLEX"] * 2 + ["BN"] * 10


class TestTranslateScoringSettings:
    def test_direct_mappings(self):
        scoring = sleeper_client.translate_scoring_settings(SFB16_SCORING_SETTINGS)
        assert scoring["Pass Yds"] == 0.04
        assert scoring["Pass TD"] == 6.0
        assert scoring["Rush Yds"] == 0.1
        assert scoring["Rush 1D"] == 0.5
        assert scoring["Rec"] == 0.5
        assert scoring["TE Rec Bonus"] == 1.0
        assert scoring["TE 1D Bonus"] == 1.0

    def test_yardage_bonus_tiers(self):
        scoring = sleeper_client.translate_scoring_settings(SFB16_SCORING_SETTINGS)
        assert scoring["Pass 300+"] == 10.0
        assert scoring["Pass 400+"] == 20.0
        assert scoring["Rush+Rec 100+"] == 10.0
        assert scoring["Rush+Rec 200+"] == 20.0
        assert scoring["Rush 100+"] == 0.0
        assert scoring["Rec 100+"] == 0.0

    def test_two_point_variants_collapse_to_one_category(self):
        scoring = sleeper_client.translate_scoring_settings(SFB16_SCORING_SETTINGS)
        assert scoring["2-PT"] == 2.0

    def test_return_td_takes_max_of_st_and_def_st(self):
        settings = dict(SFB16_SCORING_SETTINGS)
        settings["st_td"] = 6.0
        settings["def_st_td"] = 0.0
        scoring = sleeper_client.translate_scoring_settings(settings)
        assert scoring["Ret TD"] == 6.0

    def test_return_yards_falls_back_to_nonzero_variant(self):
        settings = dict(SFB16_SCORING_SETTINGS)
        settings["kr_yd"] = 0.0
        settings["pr_yd"] = 0.2
        scoring = sleeper_client.translate_scoring_settings(settings)
        assert scoring["Ret Yds"] == 0.2

    def test_missing_keys_default_to_zero(self):
        scoring = sleeper_client.translate_scoring_settings({})
        assert scoring["Pass Yds"] == 0.0
        assert scoring["Rush+Rec 100+"] == 0.0


class TestTranslateRosterPositions:
    def test_sfb16_roster_shape(self):
        roster = sleeper_client.translate_roster_positions(SFB16_ROSTER_POSITIONS)
        counts = roster.set_index("position")["count"].to_dict()
        assert counts["W/R/T"] == 8
        assert counts["Q/W/R/T"] == 2
        assert counts["BN"] == 10
        assert roster["count"].sum() == 20

    def test_standard_positions_pass_through(self):
        roster = sleeper_client.translate_roster_positions(
            ["QB", "RB", "RB", "WR", "WR", "TE", "K", "DEF", "BN", "IR"]
        )
        counts = roster.set_index("position")["count"].to_dict()
        assert counts["QB"] == 1
        assert counts["RB"] == 2
        assert counts["WR"] == 2
        assert counts["TE"] == 1
        assert counts["K"] == 1
        assert counts["DEF"] == 1
        assert counts["IR"] == 1


class TestGetLeagueConfig:
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_combines_scoring_and_roster(self, mock_fetch):
        mock_fetch.return_value = {
            "scoring_settings": SFB16_SCORING_SETTINGS,
            "roster_positions": SFB16_ROSTER_POSITIONS,
        }
        config = sleeper_client.get_league_config("1367870433398915072")
        assert config["scoring"]["Pass 300+"] == 10.0
        assert config["roster_spots"]["count"].sum() == 20
        mock_fetch.assert_called_once_with("1367870433398915072")


class TestGetReversalRound:
    @patch("fantasyfb.data.sleeper_client.fetch_draft")
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_returns_reversal_round_from_draft_settings(
        self, mock_fetch_league, mock_fetch_draft
    ):
        mock_fetch_league.return_value = {"draft_id": "999"}
        mock_fetch_draft.return_value = {"settings": {"reversal_round": 3}}
        assert sleeper_client.get_reversal_round("123") == 3
        mock_fetch_league.assert_called_once_with("123")
        mock_fetch_draft.assert_called_once_with("999")

    @patch("fantasyfb.data.sleeper_client.fetch_draft")
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_defaults_to_zero_when_missing(
        self, mock_fetch_league, mock_fetch_draft
    ):
        mock_fetch_league.return_value = {"draft_id": "999"}
        mock_fetch_draft.return_value = {"settings": {}}
        assert sleeper_client.get_reversal_round("123") == 0

    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_real_sfb16_draft_has_trr_disabled(self, mock_get):
        # Regression pin for the real #SFB16 draft (1367870434288078848):
        # reversal_round=0 confirmed live on 2026-07-06.
        mock_league_resp = Mock()
        mock_league_resp.json.return_value = {"draft_id": "1367870434288078848"}
        mock_draft_resp = Mock()
        mock_draft_resp.json.return_value = {
            "settings": {"reversal_round": 0, "teams": 12, "rounds": 20}
        }
        mock_get.side_effect = [mock_league_resp, mock_draft_resp]
        assert sleeper_client.get_reversal_round("1367870433398915072") == 0


class TestFetchDraft:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"draft_id": "999", "settings": {}}
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_draft("999")
        assert result == {"draft_id": "999", "settings": {}}
        mock_get.assert_called_once_with("https://api.sleeper.app/v1/draft/999")


class TestFetchLeague:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_raises_on_http_error(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404")
        mock_get.return_value = mock_response
        try:
            sleeper_client.fetch_league("nonexistent")
            assert False, "expected an exception"
        except Exception as exc:
            assert "404" in str(exc)

    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"league_id": "123"}
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_league("123")
        assert result == {"league_id": "123"}
        mock_get.assert_called_once_with(
            "https://api.sleeper.app/v1/league/123"
        )


# ---------------------------------------------------------------------------
# SleeperClient: teams, rosters, schedule, player pool
# ---------------------------------------------------------------------------

USERS = [
    {"user_id": "u1", "display_name": "Alice", "metadata": {"team_name": "Team Alice"}},
    {"user_id": "u2", "display_name": "Bob", "metadata": {}},
]

ROSTERS = [
    {
        "roster_id": 1,
        "owner_id": "u1",
        "players": ["100", "101", "102", "103", "104", "105", "106", "107"],
        "starters": ["100", "101", "102", "103", "104", "105", "106"],
        "reserve": ["107"],
    },
    {
        "roster_id": 2,
        "owner_id": "u2",
        "players": ["200", "201"],
        "starters": ["200"],
        "reserve": [],
    },
]

TEAMS = [
    {"team_key": "1", "name": "Team Alice", "manager": "Alice"},
    {"team_key": "2", "name": "Bob", "manager": "Bob"},
]

# QB, RB, RB, WR, WR, TE, FLEX -- 7 starting slots, then bench/IR.
LEAGUE_ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "IR"]


class TestFetchUsers:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = USERS
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_users("123")
        assert result == USERS
        mock_get.assert_called_once_with(
            "https://api.sleeper.app/v1/league/123/users"
        )


class TestFetchRosters:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = ROSTERS
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_rosters("123")
        assert result == ROSTERS
        mock_get.assert_called_once_with(
            "https://api.sleeper.app/v1/league/123/rosters"
        )


class TestFetchMatchups:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [{"roster_id": 1, "matchup_id": 1}]
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_matchups("123", 3)
        assert result == [{"roster_id": 1, "matchup_id": 1}]
        mock_get.assert_called_once_with(
            "https://api.sleeper.app/v1/league/123/matchups/3"
        )

    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_none_body_returns_empty_list(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = None
        mock_get.return_value = mock_response
        assert sleeper_client.fetch_matchups("123", 18) == []


class TestFetchNflState:
    @patch("fantasyfb.data.sleeper_client.requests.get")
    def test_returns_json_body(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"week": 2, "display_week": 3}
        mock_get.return_value = mock_response
        result = sleeper_client.fetch_nfl_state()
        assert result == {"week": 2, "display_week": 3}
        mock_get.assert_called_once_with("https://api.sleeper.app/v1/state/nfl")


class TestFetchAllPlayers:
    def test_fetches_and_caches_when_no_cache_present(self, tmp_path):
        cache_path = str(tmp_path / "sleeper_players.json")
        with patch("fantasyfb.data.sleeper_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"100": {"position": "QB"}}
            mock_get.return_value = mock_response
            result = sleeper_client.fetch_all_players(cache_path=cache_path)
        assert result == {"100": {"position": "QB"}}
        assert os.path.exists(cache_path)

    def test_uses_fresh_cache_without_hitting_network(self, tmp_path):
        cache_path = str(tmp_path / "sleeper_players.json")
        with open(cache_path, "w") as f:
            json.dump({"100": {"position": "QB"}}, f)
        with patch("fantasyfb.data.sleeper_client.requests.get") as mock_get:
            result = sleeper_client.fetch_all_players(cache_path=cache_path)
        mock_get.assert_not_called()
        assert result == {"100": {"position": "QB"}}

    def test_refetches_when_cache_stale(self, tmp_path):
        cache_path = str(tmp_path / "sleeper_players.json")
        with open(cache_path, "w") as f:
            json.dump({"100": {"position": "QB"}}, f)
        with patch("fantasyfb.data.sleeper_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"100": {"position": "RB"}}
            mock_get.return_value = mock_response
            result = sleeper_client.fetch_all_players(
                cache_path=cache_path, max_age_seconds=0
            )
        mock_get.assert_called_once()
        assert result == {"100": {"position": "RB"}}

    def test_force_refresh_bypasses_fresh_cache(self, tmp_path):
        cache_path = str(tmp_path / "sleeper_players.json")
        with open(cache_path, "w") as f:
            json.dump({"100": {"position": "QB"}}, f)
        with patch("fantasyfb.data.sleeper_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"100": {"position": "RB"}}
            mock_get.return_value = mock_response
            result = sleeper_client.fetch_all_players(
                cache_path=cache_path, force_refresh=True
            )
        mock_get.assert_called_once()
        assert result == {"100": {"position": "RB"}}


class TestStartingSlots:
    def test_excludes_bench_and_ir(self):
        slots = sleeper_client._starting_slots(LEAGUE_ROSTER_POSITIONS)
        assert slots == ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T"]


class TestSleeperClientGetCurrentWeek:
    @patch("fantasyfb.data.sleeper_client.fetch_nfl_state")
    def test_prefers_display_week(self, mock_state):
        mock_state.return_value = {"week": 2, "display_week": 3}
        client = sleeper_client.SleeperClient("123")
        assert client.get_current_week() == 3

    @patch("fantasyfb.data.sleeper_client.fetch_nfl_state")
    def test_falls_back_to_week(self, mock_state):
        mock_state.return_value = {"week": 2}
        client = sleeper_client.SleeperClient("123")
        assert client.get_current_week() == 2


class TestSleeperClientGetFantasyTeams:
    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_users")
    def test_joins_users_and_rosters(self, mock_users, mock_rosters):
        mock_users.return_value = USERS
        mock_rosters.return_value = ROSTERS
        client = sleeper_client.SleeperClient("123")
        assert client.get_fantasy_teams() == TEAMS

    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_users")
    def test_unknown_owner_falls_back_to_unknown(self, mock_users, mock_rosters):
        mock_users.return_value = []
        mock_rosters.return_value = [{"roster_id": 9, "owner_id": "ghost"}]
        client = sleeper_client.SleeperClient("123")
        teams = client.get_fantasy_teams()
        assert teams == [{"team_key": "9", "name": "Unknown", "manager": "Unknown"}]


class TestSleeperClientGetAllPlayers:
    @patch("fantasyfb.data.sleeper_client.fetch_all_players")
    def test_filters_to_fantasy_positions_and_maps_columns(self, mock_fetch):
        mock_fetch.return_value = {
            "100": {
                "position": "QB", "full_name": "Josh Allen", "team": "BUF",
                "injury_status": None, "status": "Active",
                "fantasy_positions": ["QB"], "gsis_id": "00-0034857",
                "yahoo_id": "31002",
            },
            "SEA": {
                "position": "DEF", "full_name": "Seattle Seahawks", "team": "SEA",
                "fantasy_positions": ["DEF"],
            },
            "999": {"position": "LS", "full_name": "Long Snapper"},
        }
        client = sleeper_client.SleeperClient("123")
        players = client.get_all_players()
        assert set(players["player_id"]) == {"100", "SEA"}
        row = players.set_index("player_id").loc["100"]
        assert row["name"] == "Josh Allen"
        assert row["editorial_team_abbr"] == "BUF"
        assert row["status"] == "Active"
        assert row["player_id_sr"] == "00-0034857"
        assert row["yahoo_id"] == "31002"

    @patch("fantasyfb.data.sleeper_client.fetch_all_players")
    def test_injury_status_takes_priority_over_status(self, mock_fetch):
        mock_fetch.return_value = {
            "100": {
                "position": "RB", "full_name": "Hurt Guy",
                "injury_status": "Questionable", "status": "Active",
            },
        }
        client = sleeper_client.SleeperClient("123")
        players = client.get_all_players()
        assert players.iloc[0]["status"] == "Questionable"

    @patch("fantasyfb.data.sleeper_client.fetch_all_players")
    def test_falls_back_to_first_last_name_when_full_name_missing(self, mock_fetch):
        mock_fetch.return_value = {
            "100": {"position": "WR", "first_name": "Jane", "last_name": "Doe"},
        }
        client = sleeper_client.SleeperClient("123")
        players = client.get_all_players()
        assert players.iloc[0]["name"] == "Jane Doe"


class TestSleeperClientGetTeamRosters:
    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_uses_weekly_matchup_starters_when_available(
        self, mock_league, mock_matchups, mock_rosters
    ):
        mock_league.return_value = {"roster_positions": LEAGUE_ROSTER_POSITIONS}
        mock_rosters.return_value = ROSTERS
        mock_matchups.return_value = [
            {
                "roster_id": 1, "matchup_id": 1, "points": 123.4,
                "starters": ["100", "101", "102", "103", "104", "105", "106"],
                "players": ["100", "101", "102", "103", "104", "105", "106", "107"],
            },
            {
                "roster_id": 2, "matchup_id": 1, "points": 110.0,
                "starters": ["200"],
                "players": ["200", "201"],
            },
        ]
        client = sleeper_client.SleeperClient("123")
        rosters = client.get_team_rosters(TEAMS, 3)

        by_player = rosters.set_index("player_id")
        assert by_player.loc["100", "selected_position"] == "QB"
        assert by_player.loc["101", "selected_position"] == "RB"
        assert by_player.loc["106", "selected_position"] == "W/R/T"
        assert by_player.loc["100", "fantasy_team"] == "Team Alice"
        # 107 is on roster 1's reserve list -> IR, not BN.
        assert by_player.loc["107", "selected_position"] == "IR"
        # 201 isn't a starter and isn't on reserve -> BN.
        assert by_player.loc["201", "selected_position"] == "BN"
        assert by_player.loc["200", "selected_position"] == "QB"
        assert by_player.loc["200", "fantasy_team"] == "Bob"

    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_falls_back_to_current_rosters_when_no_matchup_data(
        self, mock_league, mock_matchups, mock_rosters
    ):
        mock_league.return_value = {"roster_positions": LEAGUE_ROSTER_POSITIONS}
        mock_rosters.return_value = ROSTERS
        mock_matchups.return_value = []

        client = sleeper_client.SleeperClient("123")
        rosters = client.get_team_rosters(TEAMS, 18)

        by_player = rosters.set_index("player_id")
        assert by_player.loc["100", "selected_position"] == "QB"
        assert by_player.loc["200", "fantasy_team"] == "Bob"

    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_unknown_roster_id_is_skipped(
        self, mock_league, mock_matchups, mock_rosters
    ):
        mock_league.return_value = {"roster_positions": LEAGUE_ROSTER_POSITIONS}
        mock_rosters.return_value = ROSTERS
        mock_matchups.return_value = [
            {"roster_id": 99, "matchup_id": 1, "points": 0.0, "starters": ["300"], "players": ["300"]},
        ]
        client = sleeper_client.SleeperClient("123")
        rosters = client.get_team_rosters(TEAMS, 3)
        assert rosters.empty


class TestSleeperClientGetSchedule:
    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    def test_pairs_teams_by_matchup_id(self, mock_matchups):
        def side_effect(league_id, week):
            if week == 1:
                return [
                    {"roster_id": 1, "matchup_id": 1, "points": 100.0},
                    {"roster_id": 2, "matchup_id": 1, "points": 90.0},
                ]
            return []

        mock_matchups.side_effect = side_effect
        client = sleeper_client.SleeperClient("123")
        schedule = client.get_schedule(TEAMS, current_week=1, playoff_start_week=1)

        assert schedule.shape[0] == 1
        row = schedule.iloc[0]
        assert row["team_1"] == "Team Alice"
        assert row["team_2"] == "Bob"
        assert row["score_1"] == 100.0
        assert row["score_2"] == 90.0

    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    def test_skips_unpaired_bye_entries(self, mock_matchups):
        mock_matchups.return_value = [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
        ]
        client = sleeper_client.SleeperClient("123")
        schedule = client.get_schedule(TEAMS, current_week=1, playoff_start_week=1)
        assert schedule.empty
        assert list(schedule.columns) == ["week", "team_1", "team_2", "score_1", "score_2"]

    @patch("fantasyfb.data.sleeper_client.fetch_matchups")
    def test_end_week_caps_query_range(self, mock_matchups):
        mock_matchups.return_value = []
        client = sleeper_client.SleeperClient("123")
        client.get_schedule(TEAMS, current_week=1, playoff_start_week=20, end_week=3)
        queried_weeks = sorted({call.args[1] for call in mock_matchups.call_args_list})
        assert queried_weeks == [1, 2, 3]


class TestSleeperClientGetLeagueConfig:
    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_derives_settings_from_raw_playoff_fields(self, mock_fetch):
        mock_fetch.return_value = {
            "scoring_settings": SFB16_SCORING_SETTINGS,
            "roster_positions": SFB16_ROSTER_POSITIONS,
            "settings": {"playoff_week_start": 14, "playoff_teams": 4},
        }
        client = sleeper_client.SleeperClient("123")
        config = client.get_league_config()
        assert config["settings"]["playoff_start_week"] == 14
        assert config["settings"]["num_playoff_teams"] == 4
        assert config["settings"]["end_week"] == 15
        assert config["scoring"]["Pass TD"] == 6.0
        assert config["roster_spots"]["count"].sum() == 20

    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_six_team_playoffs_gets_two_week_cushion(self, mock_fetch):
        mock_fetch.return_value = {
            "scoring_settings": {}, "roster_positions": [],
            "settings": {"playoff_week_start": 14, "playoff_teams": 6},
        }
        client = sleeper_client.SleeperClient("123")
        config = client.get_league_config()
        assert config["settings"]["end_week"] == 16

    @patch("fantasyfb.data.sleeper_client.fetch_league")
    def test_unset_playoff_week_start_falls_back_to_default(self, mock_fetch):
        mock_fetch.return_value = {
            "scoring_settings": {}, "roster_positions": [],
            "settings": {"playoff_week_start": 0, "playoff_teams": 0},
        }
        client = sleeper_client.SleeperClient("123")
        config = client.get_league_config()
        assert config["settings"]["playoff_start_week"] == 15
        assert config["settings"]["num_playoff_teams"] == 6


class TestSleeperClientGetMyTeamKey:
    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_users")
    def test_matches_by_team_name(self, mock_users, mock_rosters):
        mock_users.return_value = USERS
        mock_rosters.return_value = ROSTERS
        client = sleeper_client.SleeperClient("123", my_team_name="Team Alice")
        assert client.get_my_team_key() == "1"

    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_users")
    def test_falls_back_to_manager_name(self, mock_users, mock_rosters):
        # "Team Alice" (team_key "1") has manager "Alice" -- distinct from
        # its team name, so matching on manager only works via the fallback.
        mock_users.return_value = USERS
        mock_rosters.return_value = ROSTERS
        client = sleeper_client.SleeperClient("123", my_team_name="Alice")
        assert client.get_my_team_key() == "1"

    def test_returns_none_when_no_team_name_given(self):
        client = sleeper_client.SleeperClient("123")
        assert client.get_my_team_key() is None

    @patch("fantasyfb.data.sleeper_client.fetch_rosters")
    @patch("fantasyfb.data.sleeper_client.fetch_users")
    def test_returns_none_when_no_match(self, mock_users, mock_rosters):
        mock_users.return_value = USERS
        mock_rosters.return_value = ROSTERS
        client = sleeper_client.SleeperClient("123", my_team_name="Nonexistent Team")
        assert client.get_my_team_key() is None


class TestSleeperClientGetRosterPercentages:
    def test_always_returns_none(self):
        client = sleeper_client.SleeperClient("123")
        assert client.get_roster_percentages(None) is None
