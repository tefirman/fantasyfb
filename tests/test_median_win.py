"""Tests for the "median game" league option (Sleeper's league_average_match).

With it on, every regular-season week each team also gets a win for scoring
above that week's league median, on top of its head-to-head result. The rule
is checked against #SFB16's real records (all 12 teams match head-to-head
plus median wins); the tests here pin the simulator math, the Sleeper
setting, and that leagues without the option are left exactly as they were.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from fantasyfb.data import sleeper_client
from fantasyfb.io.html_exporter import FantasyHtmlExporter
from fantasyfb.sim.season_simulator import SeasonSimulator


def _sims(weeks: list[list[float]], num_sim: int = 0) -> pd.DataFrame:
    """One simulation of a league. ``weeks[i]`` holds that week's scores in
    team order A, B, C, D, ...; teams pair off (A-B, C-D, ...) every week."""
    names = "ABCDEFGH"
    rows = []
    for week, scores in enumerate(weeks, start=1):
        for i in range(0, len(scores), 2):
            s1, s2 = scores[i], scores[i + 1]
            rows.append(dict(
                num_sim=num_sim, week=week, team_1=names[i], team_2=names[i + 1],
                sim_1=s1, sim_2=s2, win_1=int(s1 > s2), win_2=int(s2 > s1),
            ))
    return pd.DataFrame(rows)


def _wins(sims: pd.DataFrame, **settings) -> dict:
    base = {"playoff_start_week": 99, "num_playoff_teams": 2, "num_teams": 4}
    sim = SeasonSimulator({**base, **settings})
    standings = sim._calculate_regular_season_standings(sims)
    return standings.set_index("team")["wins"].to_dict()


WEEKS = [[100, 90, 80, 70], [70, 80, 90, 100]]


class TestSimulatedStandings:
    def test_head_to_head_only_when_option_is_off(self):
        assert _wins(_sims(WEEKS)) == {"A": 1, "B": 1, "C": 1, "D": 1}
        assert _wins(_sims(WEEKS), median_win=False) == _wins(_sims(WEEKS))

    def test_median_adds_a_win_for_the_top_half_each_week(self):
        # week 1 median 85: A, B above. week 2 median 85: C, D above.
        # A: h2h wk1 + median wk1; B: h2h wk2 + median wk1;
        # C: h2h wk1 + median wk2; D: h2h wk2 + median wk2.
        assert _wins(_sims(WEEKS), median_win=True) == {"A": 2, "B": 2, "C": 2, "D": 2}

    def test_a_loser_can_still_win_the_median(self):
        # B loses to A but outscores C and D.
        wins = _wins(_sims([[100, 90, 80, 70]]), median_win=True)
        assert wins["B"] == 1  # median win only
        assert wins["C"] == 1  # head-to-head win only (80 vs 70), below median

    def test_tie_at_the_median_is_half_a_win(self):
        sims = _sims([[100, 90, 80, 90]])  # the median of the four is 90, a tie for B and D
        wins = _wins(sims, median_win=True)
        assert wins["B"] == 0.5  # lost head-to-head, tied the median
        assert wins["D"] == 1.5  # beat C head-to-head, tied the median
        assert wins["A"] == 2  # beat B head-to-head and is above the median
        assert wins["C"] == 0  # lost to D head-to-head and is below the median

    def test_median_is_taken_per_simulation_and_per_week(self):
        # two sims with swapped scores must not pool into one median
        sims = pd.concat([
            _sims([[100, 90, 80, 70]], num_sim=0),
            _sims([[70, 80, 90, 100]], num_sim=1),
        ], ignore_index=True)
        sim = SeasonSimulator({"playoff_start_week": 99, "num_playoff_teams": 2,
                               "num_teams": 4, "median_win": True})
        st = sim._calculate_regular_season_standings(sims)
        by = st.set_index(["num_sim", "team"])["wins"]
        assert by[(0, "A")] == 2 and by[(1, "A")] == 0

    def test_playoff_weeks_do_not_count(self):
        sims = _sims(WEEKS)  # weeks 1 and 2
        assert _wins(sims, median_win=True, playoff_start_week=2) == {
            "A": 2, "B": 1, "C": 1, "D": 0,
        }

    def test_league_wide_wins_are_head_to_head_plus_half_the_teams_per_week(self):
        sims = _sims([[101, 99, 98, 97, 96, 95], [60, 70, 80, 90, 100, 110]])
        wins = _wins(sims, median_win=True, num_teams=6)
        assert sum(wins.values()) == pytest.approx(2 * 3 + 2 * 3)


class TestSleeperSetting:
    @staticmethod
    def _config(league_average_match):
        raw = {"playoff_week_start": 14, "playoff_teams": 6}
        if league_average_match is not None:
            raw["league_average_match"] = league_average_match
        with patch("fantasyfb.data.sleeper_client.fetch_league") as fetch:
            fetch.return_value = {
                "scoring_settings": {}, "roster_positions": [], "settings": raw,
            }
            return sleeper_client.SleeperClient("123").get_league_config()["settings"]

    def test_league_average_match_turns_on_median_win(self):
        assert self._config(1)["median_win"] is True

    def test_off_or_absent_is_off(self):
        assert self._config(0)["median_win"] is False
        assert self._config(None)["median_win"] is False


class TestReportFlag:
    @staticmethod
    def _render(**kw) -> str:
        exp = FantasyHtmlExporter("unused.html", week=3, me="A", **kw)
        exp.export_standings(pd.DataFrame({"team": ["A"], "wins_avg": [1.0]}))
        return exp.render()

    def test_payload_carries_the_flag_and_report_counts_median_games(self):
        on = self._render(median_win=True)
        assert '"median_win": true' in on
        assert "D.median_win" in on  # report.js computes the combined record

    def test_record_column_is_a_sort_button_ranked_by_win_percentage(self):
        html = self._render(median_win=True)
        assert 'data-action="sort-stand" data-key="record"' in html
        assert 'S.sKey === "record"' in html and "recPct" in html

    def test_flag_defaults_to_off(self):
        assert '"median_win": false' in self._render()
