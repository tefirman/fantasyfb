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


class TestDefensiveTacklesForLoss:
    """Tackles-for-loss is a team-DEF stat some leagues score separately
    from sacks; nflreadpy_provider._build_defense feeds it in as
    tackles_for_loss."""

    def test_tfl_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["TFL"] = 0.5
        df = pd.DataFrame([_player("DEF", tackles_for_loss=6)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(3.0)

    def test_tfl_stacks_with_other_defensive_stats(self):
        scoring = dict(SFB16_SCORING)
        scoring["Sack"] = 1.0
        scoring["TFL"] = 0.5
        df = pd.DataFrame([_player("DEF", sacks=3, tackles_for_loss=4)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(3 * 1.0 + 4 * 0.5)

    def test_missing_tfl_column_defaults_to_zero(self):
        df = pd.DataFrame([_player("DEF", sacks=2)])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(0.0)


class TestFieldGoalYardageScoring:
    """Some leagues (e.g. 0.1 pts/yard) score kickers by actual FG distance
    instead of the FG 0-19/20-29/etc. tiers. Regression test for a real
    discrepancy: a kicker who made FGs of 23/47/51 yards plus a PAT was
    projected at way less than Yahoo's actual total because only 'FG 0-19'
    (a flat per-kick rate) was ever applied, ignoring 'FG Yds' entirely."""

    def test_fg_yds_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["FG 0-19"] = 0.0
        scoring["FG Yds"] = 0.1
        scoring["PAT Made"] = 1.0
        df = pd.DataFrame([_player("K", fgm=3, fg_yds=121, xpm=1)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(13.1)

    def test_fg_0_19_and_fg_yds_are_additive_not_exclusive(self):
        # A league could (in principle) award both a flat per-kick bonus
        # and a yardage rate; the two terms should simply add.
        scoring = dict(SFB16_SCORING)
        scoring["FG 0-19"] = 3.0
        scoring["FG Yds"] = 0.1
        df = pd.DataFrame([_player("K", fgm=1, fg_yds=45)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(3.0 + 4.5)

    def test_missing_fg_yds_column_defaults_to_zero(self):
        scoring = dict(SFB16_SCORING)
        scoring["FG 0-19"] = 0.0
        df = pd.DataFrame([_player("K", fgm=2)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(0.0)


class TestMiscellaneousScoringCategories:
    """PAT Miss, Off Fumb TD, 2-PT (offense) and Safe, Blk Kick (defense)
    all exist as real, nonzero categories in at least one league's Yahoo
    scoring settings but had no corresponding stat column wired up at
    all prior to this test."""

    def test_pat_miss_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["PAT Miss"] = -1.0
        df = pd.DataFrame([_player("K", pat_miss=1)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(-1.0)

    def test_off_fumble_td_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["Off Fumb TD"] = 6.0
        df = pd.DataFrame([_player("WR", off_fumble_td=1)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(6.0)

    def test_two_pt_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["2-PT"] = 2.0
        df = pd.DataFrame([_player("RB", two_pt=2)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(4.0)

    def test_safety_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["Safe"] = 4.0
        df = pd.DataFrame([_player("DEF", safeties=1)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(4.0)

    def test_blocked_kick_scored_at_configured_rate(self):
        scoring = dict(SFB16_SCORING)
        scoring["Blk Kick"] = 2.0
        df = pd.DataFrame([_player("DEF", blocked_kicks=2)])
        result = FantasyScorer(scoring).calculate_points(df)
        assert result.loc[0, "points"] == pytest.approx(4.0)

    def test_missing_columns_do_not_raise(self):
        df = pd.DataFrame([
            _player("K", fgm=1),
            _player("DEF", sacks=1),
        ])
        result = FantasyScorer(dict(SFB16_SCORING)).calculate_points(df)
        assert result["points"].notna().all()
