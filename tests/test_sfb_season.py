"""Tests for Scott Fish Bowl season structure on Sleeper.

SFB leagues ("#SFB16 - ...") count only the first 11 weeks as the regular
season, then run field-wide playoffs in weeks 12-17 for teams with 13+ wins
(plus the best of the rest on points). Sleeper's own settings describe none
of this, so fantasyfb detects the league by name. See
https://scottfishbowl.com/rules2026.php.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from fantasyfb import League
from fantasyfb.data import sleeper_client
from fantasyfb.io.html_exporter import FantasyHtmlExporter
from fantasyfb.sim.season_simulator import SeasonSimulator
from test_median_win import _sims, regular_season_standings


class TestDetection:
    @pytest.mark.parametrize("name", [
        "#SFB16 - Boris (GoldenEye 007)", "SFB16", "sfb 16 league", "Bowl SFB15 #2",
    ])
    def test_sfb_names_are_detected(self, name):
        assert sleeper_client.is_sfb_league(name)

    @pytest.mark.parametrize("name", [
        "Office League", "SFBX", "Sfb", "Superflex Fish Bowl", "", None,
    ])
    def test_other_names_are_not(self, name):
        assert not sleeper_client.is_sfb_league(name)


class TestSleeperSettings:
    @staticmethod
    def _settings(name, **raw):
        raw = {"playoff_week_start": 0, "playoff_teams": 6, **raw}
        with patch("fantasyfb.data.sleeper_client.fetch_league") as fetch:
            fetch.return_value = {
                "name": name, "scoring_settings": {}, "roster_positions": [],
                "settings": raw,
            }
            return sleeper_client.SleeperClient("123").get_league_config()["settings"]

    def test_sfb_gets_an_11_week_regular_season_and_a_win_threshold(self):
        s = self._settings("#SFB16 - Boris")
        assert s["sfb"] is True
        assert s["playoff_start_week"] == 12  # weeks 1-11 are the regular season
        assert s["end_week"] == 17
        assert s["playoff_win_threshold"] == 13

    def test_sfb_overrides_whatever_sleeper_says_about_playoffs(self):
        s = self._settings("#SFB16", playoff_week_start=15, playoff_teams=4)
        assert s["playoff_start_week"] == 12 and s["playoff_win_threshold"] == 13

    def test_other_leagues_are_untouched(self):
        s = self._settings("Office League", playoff_week_start=14, playoff_teams=4)
        assert "sfb" not in s and "playoff_win_threshold" not in s
        assert s["playoff_start_week"] == 14 and s["end_week"] == 15


# 13 wins is unreachable in a few-week test, so use a small threshold.
WEEKS = [[100, 90, 80, 70], [70, 80, 90, 100], [95, 85, 75, 65]]


def _standings(threshold=None, median=True, **extra):
    settings = {"playoff_start_week": 99, "num_playoff_teams": 2, "num_teams": 4,
                "median_win": median, **extra}
    if threshold:
        settings["playoff_win_threshold"] = threshold
    sim = SeasonSimulator(settings)
    st = regular_season_standings(sim, _sims(WEEKS))
    return sim, st


class TestSimulator:
    def test_playoffs_means_reaching_the_win_threshold(self):
        _, st = _standings(threshold=4)
        by = st.set_index("team")
        assert (by["playoffs"] == (by["wins"] >= 4).astype(int)).all()
        assert by["playoffs"].sum() > 0

    def test_without_a_threshold_the_in_league_top_n_still_makes_it(self):
        _, st = _standings()
        assert st["playoffs"].sum() == 2  # num_playoff_teams, one simulation

    def test_no_bye_title_or_payout_in_field_wide_playoffs(self):
        sim, st = _standings(threshold=4, num_playoff_teams=6)
        out = sim._aggregate_standings_results(st, None, [60, 30, 10])
        assert (out["playoff_bye"] == 0).all()
        assert (out[["winner", "runner_up", "third"]] == 0).all().all()

    def test_objective_is_the_chance_of_reaching_the_threshold(self):
        sim, st = _standings(threshold=4)
        out = sim._aggregate_standings_results(st, None, [60, 30, 10])
        assert (out["earnings"] == out["playoffs"]).all()

    def test_earnings_stay_zero_for_ordinary_leagues(self):
        sim, st = _standings()
        out = sim._aggregate_standings_results(st, None, [60, 30, 10])
        assert (out["earnings"] == 0).all()

    def test_no_bracket_is_simulated(self):
        sim = SeasonSimulator({"playoff_start_week": 3, "num_playoff_teams": 2,
                               "num_teams": 4, "playoff_win_threshold": 2})
        with patch.object(SeasonSimulator, "_simulate_playoffs") as bracket:
            proj = pd.DataFrame([
                {"fantasy_team": t, "week": w, "points_avg": 100.0, "points_stdev": 1.0}
                for t in "ABCD" for w in (1, 2)
            ])
            sched = pd.DataFrame([
                {"week": w, "team_1": a, "team_2": b, "score_1": 0.0, "score_2": 0.0}
                for w in (1, 2) for a, b in (("A", "B"), ("C", "D"))
            ])
            sim.simulate_season(proj, sched, num_sims=5, include_playoffs=True)
        bracket.assert_not_called()


class TestScheduleTrim:
    @staticmethod
    def _league(settings):
        class Manager:
            def get_schedule(self, *args):
                return pd.DataFrame({"week": list(range(1, 15)), "team_1": "A", "team_2": "B"})

        lg = League.__new__(League)
        lg.schedule_manager = Manager()
        lg.season, lg.week, lg.current_week, lg.my_team_key = 2026, 7, 7, None
        lg.settings = settings
        return lg

    def test_sfb_schedule_stops_after_the_regular_season(self):
        lg = self._league({"sfb": True, "playoff_start_week": 12})
        lg.get_schedule()
        assert lg.schedule.week.tolist() == list(range(1, 12))
        assert lg.schedule.index.tolist() == list(range(11))

    def test_other_leagues_keep_every_scheduled_week(self):
        lg = self._league({"playoff_start_week": 12})
        lg.get_schedule()
        assert lg.schedule.week.max() == 14


class TestReport:
    @staticmethod
    def _render(**kw):
        exp = FantasyHtmlExporter("unused.html", week=3, me="A", **kw)
        exp.export_standings(pd.DataFrame({"team": ["A"], "wins_avg": [1.0]}))
        return exp.render()

    def test_sfb_flag_and_explanation(self):
        html = self._render(sfb=True)
        assert '"sfb": true' in html
        assert "Scott Fish Bowl league" in html and "13+ wins" in html
        assert 'id="notices"' in html

    def test_ordinary_reports_have_no_sfb_text(self):
        html = self._render()
        assert '"sfb": false' in html
        assert "Scott Fish Bowl league" not in html

    def test_sfb_notice_is_added_alongside_other_notices(self):
        html = self._render(sfb=True, notices=["Something else"])
        assert "Something else" in html and "Scott Fish Bowl league" in html
