"""Tests for the per-play long-play bonuses (20-29/30-39/40+ yard receptions,
40+ yard rushes, 40+ yard completions and passing TDs) added for Scott Fish
Bowl style Sleeper leagues.

The counts come from play-by-play, the scorer pays them, and League attaches
them only when the league scores them. The guarantee that matters most is the
last one: a league that doesn't score them must be untouched.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb import League
from fantasyfb.configs import apply_default_scoring_categories
from fantasyfb.data.nfl_provider import NFLDataProvider
from fantasyfb.data.nflreadpy_provider import NflreadpyProvider
from fantasyfb.scoring.fantasy_scoring import FantasyScorer

COLUMNS = list(NFLDataProvider.LONG_PLAY_COLUMNS)


def _scoring(**long_play) -> dict:
    return apply_default_scoring_categories({"Rec": 0.5, "Rec Yds": 0.1, **long_play})


class TestScorer:
    def test_each_long_play_category_pays_its_own_column(self):
        scoring = _scoring(**{
            "Rec 20-29": 1.0, "Rec 30-39": 2.0, "Rec 40+": 4.0,
            "Rush 40+": 8.0, "Pass Comp 40+": 16.0, "Pass TD 40+": 32.0,
        })
        df = pd.DataFrame([{
            "position": "WR", "rec_20_29": 1, "rec_30_39": 1, "rec_40p": 1,
            "rush_40p": 1, "pass_cmp_40p": 1, "pass_td_40p": 1,
        }])
        assert FantasyScorer(scoring).calculate_points(df).loc[0, "points"] == 63.0

    def test_zero_weights_leave_points_unchanged(self):
        base = pd.DataFrame([{"position": "WR", "rec": 5, "rec_yds": 70}])
        with_counts = base.assign(rec_40p=2, rush_40p=1, pass_cmp_40p=3)
        scorer = FantasyScorer(_scoring())
        assert (
            scorer.calculate_points(base).loc[0, "points"]
            == scorer.calculate_points(with_counts).loc[0, "points"]
        )

    def test_missing_count_columns_are_treated_as_zero(self):
        df = pd.DataFrame([{"position": "WR", "rec": 4, "rec_yds": 50}])
        scorer = FantasyScorer(_scoring(**{"Rec 40+": 10.0}))
        assert scorer.calculate_points(df).loc[0, "points"] == pytest.approx(7.0)

    def test_negative_bonus_subtracts(self):
        df = pd.DataFrame([{"position": "RB", "rush_40p": 2}])
        scorer = FantasyScorer(_scoring(**{"Rush 40+": -3.0}))
        assert scorer.calculate_points(df).loc[0, "points"] == -6.0

    def test_defenses_are_not_scored_for_long_plays(self):
        df = pd.DataFrame([{"position": "DEF", "rec_40p": 5}])
        scorer = FantasyScorer(_scoring(**{"Rec 40+": 10.0}))
        assert scorer.calculate_points(df).loc[0, "points"] == 0.0


def _pbp() -> pd.DataFrame:
    """Plays covering every tier boundary, a nullified play, a 2-point-sized
    gain, and a postseason play."""
    base = dict(season=2026, week=3, season_type="REG", complete_pass=0,
                pass_touchdown=0, passing_yards=None, receiving_yards=None,
                rushing_yards=None, passer_player_id=None,
                receiver_player_id=None, rusher_player_id=None)

    def catch(rec, yds, td=0, **kw):
        return {**base, "play_type": "pass", "complete_pass": 1,
                "passer_player_id": "QB1", "receiver_player_id": rec,
                "passing_yards": yds, "receiving_yards": yds,
                "pass_touchdown": td, **kw}

    def run(rusher, yds, **kw):
        return {**base, "play_type": "run", "rusher_player_id": rusher,
                "rushing_yards": yds, **kw}

    return pd.DataFrame([
        catch("WR1", 19), catch("WR1", 20), catch("WR1", 29),   # 20-29 x2
        catch("WR1", 30), catch("WR1", 39),                     # 30-39 x2
        catch("WR1", 40), catch("WR1", 75, td=1),               # 40+ x2, one TD
        run("RB1", 39), run("RB1", 40), run("RB1", 80),         # 40+ x2
        catch("WR2", 50, play_type="no_play"),                  # nullified
        catch("WR2", 60, season_type="POST"),                   # postseason
        {**base, "play_type": "pass", "passer_player_id": "QB1"},  # incompletion
    ])


class TestCountLongPlays:
    @pytest.fixture
    def counts(self):
        out = NflreadpyProvider._count_long_plays(_pbp())
        return out.set_index("player_id_sr")

    def test_receiver_tiers_are_exclusive_and_inclusive_at_boundaries(self, counts):
        wr = counts.loc["WR1"]
        assert (wr.rec_20_29, wr.rec_30_39, wr.rec_40p) == (2, 2, 2)

    def test_rushes_need_40_yards(self, counts):
        assert counts.loc["RB1", "rush_40p"] == 2

    def test_passer_gets_completions_and_touchdowns_at_40_plus(self, counts):
        qb = counts.loc["QB1"]
        assert qb.pass_cmp_40p == 2
        assert qb.pass_td_40p == 1

    def test_nullified_and_postseason_plays_are_ignored(self, counts):
        assert "WR2" not in counts.index

    def test_one_row_per_player_game_with_every_column(self):
        out = NflreadpyProvider._count_long_plays(_pbp())
        assert out.columns.tolist() == ["player_id_sr", "season", "week", *COLUMNS]
        assert not out.duplicated(["player_id_sr", "season", "week"]).any()


class _Provider:
    """Provider that records whether long-play counts were requested."""

    def __init__(self, counts: pd.DataFrame):
        self._counts = counts
        self.requested = False

    def get_long_play_counts(self, start, finish):
        self.requested = True
        return self._counts


def _league(scoring: dict, counts: pd.DataFrame) -> League:
    lg = League.__new__(League)
    lg.scoring = scoring
    lg.nfl_provider = _Provider(counts)
    return lg


def _stats() -> pd.DataFrame:
    return pd.DataFrame({
        "player_id_sr": ["a", "b", "TEN"], "season": [2026] * 3, "week": [3] * 3,
        "position": ["WR", "WR", "DEF"], "rec": [5, 4, 0], "rec_yds": [60, 40, 0],
    })


def _counts() -> pd.DataFrame:
    return pd.DataFrame({
        "player_id_sr": ["a"], "season": [2026], "week": [3],
        **{c: [1 if c == "rec_40p" else 0] for c in COLUMNS},
    })


class TestLeagueAttachesCounts:
    def test_untouched_and_not_requested_when_league_does_not_score_them(self):
        lg = _league(_scoring(), _counts())
        stats = _stats()
        out = lg._add_long_plays(stats, 202603, 202603)
        assert out is stats
        assert lg.nfl_provider.requested is False

    def test_merges_counts_and_zero_fills_when_scored(self):
        lg = _league(_scoring(**{"Rec 40+": 10.0}), _counts())
        out = lg._add_long_plays(_stats(), 202603, 202603)
        assert lg.nfl_provider.requested is True
        assert len(out) == 3  # no fan-out
        assert out.set_index("player_id_sr").rec_40p.to_dict() == {"a": 1, "b": 0, "TEN": 0}
        assert out[COLUMNS].notna().all().all()

    def test_provider_without_play_by_play_scores_zero_without_failing(self):
        class Bare(NFLDataProvider):
            get_player_stats = get_schedule = get_rosters = get_draft = None
            get_depth_charts = team_aliases = None

        empty = NFLDataProvider.get_long_play_counts(Bare.__new__(Bare), 202603, 202603)
        lg = _league(_scoring(**{"Rec 40+": 10.0}), empty)
        out = lg._add_long_plays(_stats(), 202603, 202603)
        assert (out.rec_40p == 0).all() and len(out) == 3


class TestLiveWeekActualsIncludeBonuses:
    def test_finished_games_score_long_plays_too(self):
        import datetime
        from test_live_week_actuals import (
            _NOW, _FakeProvider, _make_league, _run_at, _schedule_done_and_late,
        )

        box = pd.DataFrame({
            "player_id_sr": ["p_done_1"], "name": ["Done One"], "position": ["WR"],
            "team": ["DONE_TEAM"], "season": [2026], "week": [3],
            "rec": [4], "rec_yds": [100],
        })

        class Provider(_FakeProvider):
            def get_long_play_counts(self, start, finish):
                return pd.DataFrame({
                    "player_id_sr": ["p_done_1"], "season": [2026], "week": [3],
                    **{c: [1 if c == "rec_40p" else 0] for c in COLUMNS},
                })

        lg = _make_league(provider=Provider(box), nfl_schedule=_schedule_done_and_late())
        lg.scoring = _scoring(**{"Rec 40+": 10.0})
        real = _run_at(lg, _NOW, lambda: lg._live_week_actuals(3))
        # 4 rec (2) + 100 rec yds (10) + one 40+ reception (10)
        assert real["p_done_1"] == pytest.approx(22.0)
