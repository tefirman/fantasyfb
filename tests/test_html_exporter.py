"""Tests for FantasyHtmlExporter (the single-file HTML report) and the --format flag."""

from __future__ import annotations

import json
import re
import sys

import numpy as np
import pandas as pd
import pytest

from fantasyfb.cli import initialize_inputs
from fantasyfb.io.html_exporter import FantasyHtmlExporter


def _players(fantasy_team):
    rows = [
        ("Josh Allen", "QB", "BUF"),
        ("Bijan Robinson", "RB", "ATL"),
        ("Backup </script> Guy", "WR", "NYJ"),
    ]
    df = pd.DataFrame(
        {
            "name": [r[0] for r in rows],
            "position": [r[1] for r in rows],
            "current_team": [r[2] for r in rows],
            "points_avg": [22.5, 17.1, np.nan],
            "points_stdev": [9.0, 8.0, 5.0],
            "WAR": [1.2, 0.9, 0.0],
            "num_games": [30, 30, 12],
            "matchup_factor": [1.0, 1.05, 0.9],
            "status": [None, "Q", None],
            "bye_week": [7.0, 5.0, np.nan],
            "until": [np.nan, 3.0, np.nan],
            "starter": [1, 1, 0],
            "injured": [0, 1, 0],
            "pct_rostered": [1.0, 1.0, 0.1],
        }
    )
    if fantasy_team is not None:
        df["fantasy_team"] = fantasy_team
    return df


def _standings():
    return pd.DataFrame(
        {
            "team": ["Alpha", "Beta"],
            "wins_avg": [9.1, 7.2],
            "wins_stdev": [1.5, 1.6],
            "points_avg": [1600.0, 1500.0],
            "points_stdev": [80.0, 70.0],
            "per_game_avg": [114.0, 107.0],
            "per_game_stdev": [6.0, 6.0],
            "per_game_fano": [0.05, 0.05],
            "playoffs": [0.9, 0.5],
            "playoff_bye": [0.4, 0.1],
            "winner": [0.3, 0.05],
            "runner_up": [0.2, 0.05],
            "third": [0.2, 0.05],
            "earnings": [300.0, 40.0],
        }
    )


def _data(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)
    assert m, "embedded data blob missing"
    return json.loads(m.group(1))


@pytest.fixture
def exporter(tmp_path):
    return FantasyHtmlExporter(str(tmp_path / "r.html"), week=3, me="Alpha", sims=1000, day="Wednesday")


class TestFantasyHtmlExporter:
    def test_writes_self_contained_file(self, exporter, tmp_path):
        exporter.export_rosters(_players("Alpha"))
        exporter.export_available(_players(None))
        exporter.export_standings(_standings())
        exporter.close()
        html = (tmp_path / "r.html").read_text(encoding="utf-8")
        assert "<style>" in html and "report-data" in html
        # CSS/JS are inlined; only Google Fonts may be fetched remotely
        assert not re.search(r"<script[^>]+src=", html)
        assert not re.search(r'<link[^>]+href="https?://(?!fonts)', html)

    def test_nan_becomes_null_and_ints_stay_ints(self, exporter):
        exporter.export_rosters(_players("Alpha"))
        exporter.export_standings(_standings())
        data = _data(exporter.render())
        guy = next(p for p in data["rosters"] if p["name"].startswith("Backup"))
        assert guy["points_avg"] is None
        assert guy["bye_week"] is None
        q = next(p for p in data["rosters"] if p["name"] == "Bijan Robinson")
        assert q["until"] == 3 and isinstance(q["until"], int)
        assert q["bye_week"] == 5

    def test_script_close_tag_in_data_cannot_break_page(self, exporter):
        exporter.export_rosters(_players("Alpha"))
        html = exporter.render()
        assert html.count("</script>") == 2  # data blob + report js
        names = [p["name"] for p in _data(html)["rosters"]]
        assert "Backup </script> Guy" in names

    def test_unknown_me_falls_back_to_a_standings_team(self, tmp_path):
        exp = FantasyHtmlExporter(str(tmp_path / "r.html"), week=3, me="Nobody")
        exp.export_standings(_standings())
        assert _data(exp.render())["me"] == "Alpha"

    def test_analysis_tables_and_config(self, tmp_path):
        exp = FantasyHtmlExporter(
            str(tmp_path / "r.html"), week=3, me="Alpha",
            drop_safe_threshold=-1.0, drop_depth_threshold=-9.0,
        )
        exp.export_standings(_standings())
        exp.export_analysis(pd.DataFrame({"player_to_drop": ["A"], "earnings": [-2.5]}), "Drops")
        exp.export_analysis(
            pd.DataFrame(
                {"player_to_trade_away": ["A"], "player_to_trade_for": ["B"],
                 "their_team": ["Beta"], "my_earnings": [3.0], "their_earnings": [1.0]}
            ),
            "Trades", freeze_cols=3,
        )
        data = _data(exp.render())
        assert data["drops"][0]["earnings"] == -2.5
        assert data["trades"][0]["their_team"] == "Beta"
        assert data["config"] == {"drop_safe_threshold": -1.0, "drop_depth_threshold": -9.0}
        assert data["adds"] == [] and data["pickups"] == []

    def test_unknown_analysis_name_raises(self, exporter):
        with pytest.raises(ValueError):
            exporter.export_analysis(pd.DataFrame(), "Deltas")

    def test_empty_frames_are_ok(self, exporter):
        exporter.export_schedule(pd.DataFrame())
        assert _data(exporter.render())["schedule"] == []


class TestFormatFlag:
    def test_defaults_to_excel(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fantasyfb"])
        options = initialize_inputs()
        assert options.format == "excel"
        assert options.drop_safe_threshold == -4.0
        assert options.drop_depth_threshold == -12.0

    @pytest.mark.parametrize("fmt", ["html", "both"])
    def test_accepts_html_and_both(self, monkeypatch, fmt):
        monkeypatch.setattr(sys, "argv", ["fantasyfb", "--format", fmt])
        assert initialize_inputs().format == fmt

    def test_rejects_unknown_format(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fantasyfb", "--format", "pdf"])
        with pytest.raises(SystemExit):
            initialize_inputs()
