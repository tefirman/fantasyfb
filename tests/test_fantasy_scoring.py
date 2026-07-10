"""Tests for FantasyScorer's yardage-bonus handling.

Covers the bonus categories added for Scott Fish Bowl 16 (Sleeper-sourced
scoring): stacking Pass 300+/400+ and Rush/Rec 100+/200+ tiers, plus the
combined Rush+Rec yardage bonus that Sleeper scores separately from the
standalone rush/rec bonuses.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb.configs import apply_default_scoring_categories
from fantasyfb.scoring.fantasy_scoring import FantasyScorer


SFB16_SCORING = apply_default_scoring_categories({
    "Pass Yds": 0.04, "Pass TD": 6.0, "Pass 300+": 10.0, "Pass 400+": 20.0,
    "Rush Yds": 0.1, "Rush TD": 6.0, "Rush 1D": 0.5,
    "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6.0, "Rec 1D": 0.5,
    "Rush+Rec 100+": 10.0, "Rush+Rec 200+": 20.0,
    "TE Rec Bonus": 1.0, "TE 1D Bonus": 1.0,
})


def _player(position: str, **stats) -> dict:
    row = {"position": position}
    row.update(stats)
    return row


class TestPassingYardageBonuses:
    def test_no_bonus_under_300(self):
        df = pd.DataFrame([_player("QB", pass_yds=280)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(280 * 0.04)

    def test_300_plus_bonus_applies(self):
        df = pd.DataFrame([_player("QB", pass_yds=320)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(320 * 0.04 + 10.0)

    def test_400_plus_stacks_with_300_plus(self):
        df = pd.DataFrame([_player("QB", pass_yds=420)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(420 * 0.04 + 10.0 + 20.0)


class TestCombinedRushRecBonus:
    def test_combined_yards_under_100_no_bonus(self):
        df = pd.DataFrame([_player("RB", rush_yds=60, rec_yds=30)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(90 * 0.1)

    def test_combined_100_plus_bonus_applies_even_when_neither_alone_hits_100(self):
        df = pd.DataFrame([_player("RB", rush_yds=60, rec_yds=45)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(105 * 0.1 + 10.0)

    def test_combined_200_plus_stacks_with_100_plus(self):
        df = pd.DataFrame([_player("RB", rush_yds=120, rec_yds=90)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(210 * 0.1 + 10.0 + 20.0)

    def test_standalone_and_combined_bonuses_both_fire(self):
        scoring = dict(SFB16_SCORING)
        scoring["Rush 100+"] = 5.0
        df = pd.DataFrame([_player("RB", rush_yds=150, rec_yds=10)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(160 * 0.1 + 5.0 + 10.0)
