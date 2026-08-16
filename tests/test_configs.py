"""Tests for the generic-mock-draft scoring presets added for issue #47."""

from __future__ import annotations

from fantasyfb.configs import (
    HALF_PPR_CONFIG,
    PPR_CONFIG,
    STANDARD_CONFIG,
    get_league_config,
)


class TestGenericScoringPresets:
    def test_only_reception_scoring_differs(self):
        std, half, ppr = STANDARD_CONFIG["scoring"], HALF_PPR_CONFIG["scoring"], PPR_CONFIG["scoring"]
        assert std["Rec"] == 0.0
        assert half["Rec"] == 0.5
        assert ppr["Rec"] == 1.0
        for key in std:
            if key == "Rec":
                continue
            assert std[key] == half[key] == ppr[key], key

    def test_standard_offensive_scoring(self):
        scoring = STANDARD_CONFIG["scoring"]
        assert scoring["Pass TD"] == 4.0
        assert scoring["Rush TD"] == 6.0
        assert scoring["Rec TD"] == 6.0
        assert scoring["Int Thrown"] == -1.0

    def test_roster_spots_are_the_fixed_v1_shape(self):
        for config in (STANDARD_CONFIG, HALF_PPR_CONFIG, PPR_CONFIG):
            counts = config["roster_spots"].set_index("position")["count"].to_dict()
            assert counts == {
                "QB": 1, "RB": 2, "WR": 2, "TE": 1,
                "W/R/T": 1, "K": 1, "DEF": 1, "BN": 7,
            }
            assert config["roster_spots"]["count"].sum() == 16

    def test_configs_dont_share_mutable_roster_spots(self):
        # Mutating one preset's roster_spots shouldn't leak into the others.
        STANDARD_CONFIG["roster_spots"].loc[0, "count"] = 99
        assert HALF_PPR_CONFIG["roster_spots"].loc[0, "count"] != 99
        STANDARD_CONFIG["roster_spots"].loc[0, "count"] = 1


class TestGetLeagueConfigDispatch:
    def test_standard(self):
        assert get_league_config("standard") is STANDARD_CONFIG
        assert get_league_config("STD") is STANDARD_CONFIG

    def test_half_ppr(self):
        assert get_league_config("half_ppr") is HALF_PPR_CONFIG
        assert get_league_config("half-ppr") is HALF_PPR_CONFIG

    def test_ppr(self):
        assert get_league_config("ppr") is PPR_CONFIG

    def test_unknown_platform_returns_none(self):
        assert get_league_config("espn") is None
