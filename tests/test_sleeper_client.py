"""Tests for the Sleeper API client's translation logic.

fetch_league() itself is a thin requests.get() wrapper, so it's mocked out
rather than hitting the real (public, no-auth) Sleeper API in CI. The
scoring/roster translation is the part worth covering: mapping Sleeper's
stat-key vocabulary onto fantasyfb's internal scoring schema.
"""

from __future__ import annotations

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
