"""Tests for the SFB odds page builder (app/sfb_site/build.py)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "sfb_site"))
import build  # noqa: E402

from fantasyfb.sfb import Rules  # noqa: E402

RULES = Rules(field_quota=2, field_teams=4, regular_season_weeks=11)


def odds_frame():
    names = ["Alpha", "Beta</script><b>", "Gamma", "Delta"]
    return pd.DataFrame({
        "league_id": ["111"] * 4, "team": names, "roster_id": [1, 2, 3, 4],
        "qualify": [0.9, 0.7, 0.3, 0.1],
        "reach_wild_card_2": [0.8, 0.5, 0.2, 0.05], "reach_wild_card_3": [0.6, 0.3, 0.1, 0.02],
        "reach_wild_card_4": [0.4, 0.2, 0.05, 0.01], "reach_semi_finals": [0.2, 0.1, 0.02, 0.0],
        "reach_finals": [0.1, 0.03, 0.01, 0.0], "win": [0.04, 0.01, 0.0, 0.0],
        "wins": [14.0, 12.5, 10.0, 8.0], "points": [2700.0, 2500.0, 2300.0, 2100.0],
        "avg_ppg": [245.45, 227.27, 209.09, 190.91],
    })


def names_frame():
    return pd.DataFrame({
        "platform": ["sleeper", "sleeper", "mfl"], "league_id": ["111", "111", "999"], "roster_id": [1, 2, 1],
        "manager": ["Ann Lee", "", "Zed"], "handle": ["ann", "", "zed"], "league_name": ["Sonic", "Sonic", "Zelda"],
    })


def data():
    cut = np.random.default_rng(0).normal(2385, 28, 500)
    return build.page_data(odds_frame(), cut, names_frame(), through_week=7, rules=RULES)


class TestPageData:
    def test_teams_carry_odds_and_leaderboard_names(self):
        teams = {t["t"]: t for t in data()["teams"]}
        alpha = teams["Alpha"]
        assert (alpha["h"], alpha["m"], alpha["s"]) == ("ann", "Ann Lee", "Sonic")
        assert alpha["q"] == 0.9 and alpha["w"] == 0.04
        assert alpha["r"] == [0.8, 0.6, 0.4, 0.2, 0.1]  # Wild Card 2 through the finals
        assert teams["Gamma"]["h"] == "" and teams["Gamma"]["s"] == ""  # not on the leaderboard

    def test_mfl_leaderboard_rows_are_not_matched_to_sleeper_teams(self):
        assert all(t["h"] != "zed" for t in data()["teams"])

    def test_histogram_counts_every_simulation(self):
        cut = data()["cut"]
        assert sum(cut["counts"]) == cut["total"] == 500
        assert cut["p5"] < cut["p50"] < cut["p95"]

    def test_round_labels_line_up_with_the_odds(self):
        d = data()
        assert d["round_labels"] == [
            "Make the playoffs", "Reach Wild Card 2", "Reach Wild Card 3", "Reach Wild Card 4",
            "Reach Semi-Finals", "Reach Finals", "Win the title"]
        assert d["through_week"] == 7 and d["leagues_count"] == 1


class TestRender:
    def page(self):
        return build.render(data(), "SFB <odds> & more", RULES, generated="October 28, 2026")

    def test_every_placeholder_is_filled(self):
        assert not re.findall(r"__[A-Z_]+__", self.page())

    def test_team_names_cannot_break_out_of_the_data_block(self):
        page = self.page()
        blob = re.search(r'<script id="odds-data" type="application/json">(.*?)</script>', page, re.S).group(1)
        assert "</script>" not in blob
        names = [t["t"] for t in json.loads(blob)["teams"]]
        assert "Beta</script><b>" in names  # intact once parsed

    def test_title_is_escaped(self):
        assert "<title>SFB &lt;odds&gt; &amp; more</title>" in self.page()

    def test_round_sizes_follow_the_rules_scaled_to_the_teams_simulated(self):
        page = build.render(data(), "t", Rules(), generated="")
        # 4 teams of 5,004 simulated, so each round starts with a tiny scaled field
        assert re.search(r"The field shrinks to [\d, and]+ teams", page)


def test_player_rows_skip_thin_and_unmeasured_players():
    players = pd.DataFrame({
        "player_id": ["a", "b", "c"], "name": ["A", "B", "C"], "position": ["QB", "WR", None],
        "nfl_team": ["BUF", "SEA", "NYJ"], "teams": [400, 3, 200], "field_share": [0.08, 0.0, 0.04],
        "playoff_share": [0.09, 0.0, 0.05], "qual_swing": [0.05, 0.4, float("nan")],
        "playoff_swing": [0.2, 0.9, 0.1],
    })
    rows = build.player_rows(players)
    assert [r["n"] for r in rows] == ["A"]
    assert rows[0]["q"] == 0.05 and rows[0]["k"] == 400


def test_page_data_carries_the_cutoffs_the_team_scatter_draws():
    data = build.page_data(odds_frame(), np.array([2380.0, 2400.0, 2420.0]), names_frame(), through_week=7, rules=RULES)
    assert data["auto_wins"] == RULES.auto_wins
    assert data["reg_weeks"] == RULES.regular_season_weeks
    assert data["cut"]["p5"] < data["cut"]["p50"] < data["cut"]["p95"]
    assert all({"g", "p", "q"} <= set(team) for team in data["teams"])
