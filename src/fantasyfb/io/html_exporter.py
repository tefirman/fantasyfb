"""
HTML export functionality for fantasy football projections.

Mirrors the shape of :class:`~fantasyfb.io.excel_exporter.FantasyExcelExporter`
(collect DataFrames, then ``close()`` writes the file) but produces a single
self-contained, interactive ``.html`` report. All tables are embedded as one
JSON blob and rendered client-side by a small vanilla-JS script, so the file
works offline and can be emailed.
"""

import json
import os
from typing import Optional

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

# Columns that arrive as float (because of NaNs) but are whole numbers.
_INT_COLS = ["week", "until", "bye_week", "starter", "injured", "num_games", "me"]

_ROSTER_COLS = [
    "name", "position", "current_team", "points_avg", "points_stdev",
    "WAR", "fantasy_team", "num_games", "matchup_factor",
    "status", "bye_week", "until", "starter", "injured", "pct_rostered",
]
_AVAILABLE_COLS = [
    "name", "position", "current_team", "points_avg", "points_stdev",
    "WAR", "num_games", "matchup_factor", "status", "bye_week", "until",
    "pct_rostered",
]
_SCHEDULE_COLS = [
    "week", "team_1", "team_2", "win_1", "win_2", "points_avg_1",
    "points_stdev_1", "points_avg_2", "points_stdev_2", "me",
]
_STANDINGS_COLS = [
    "team", "wins_avg", "wins_stdev", "points_avg", "points_stdev",
    "per_game_avg", "per_game_stdev", "per_game_fano", "playoffs",
    "playoff_bye", "winner", "runner_up", "third", "earnings",
]


def _records(df: Optional[pd.DataFrame], columns: Optional[list] = None) -> list:
    """DataFrame -> JSON-safe list of dicts (NaN/NaT -> None, numpy -> native)."""
    if df is None or len(df) == 0:
        return []
    df = df.copy()
    if columns is not None:
        df = df[[c for c in columns if c in df.columns]]
    for col in _INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    # to_json emits NaN as null and handles numpy scalars.
    return json.loads(df.to_json(orient="records"))


class FantasyHtmlExporter:
    """
    Collects fantasy football DataFrames and writes one interactive HTML report.
    """

    def __init__(
        self,
        output_path: str,
        week: int,
        me: str,
        sims: Optional[int] = None,
        day: Optional[str] = None,
        platform: str = "Yahoo",
        bestball: bool = False,
        drop_safe_threshold: float = -4.0,
        drop_depth_threshold: float = -12.0,
    ):
        """
        Args:
            output_path: Full path to the output .html file
            week: Current NFL week
            me: Name of the user's own fantasy team (the report's default view)
            sims: Number of Monte Carlo simulations behind the numbers
            day: Weekday label shown in the header (e.g. "Wednesday")
            platform: Fantasy platform name shown in the footer
            bestball: Whether the report is for a best ball run
            drop_safe_threshold: A drop whose expected-earnings delta is above
                this value gets the "Safe to cut" verdict
            drop_depth_threshold: Above this (but not above the safe
                threshold) gets "Depth"; anything lower is "Keep"
        """
        self.output_path = output_path
        self.week = int(week)
        self.me = me
        self.sims = sims
        self.day = day
        self.platform = platform
        self.bestball = bestball
        self.config = {
            "drop_safe_threshold": drop_safe_threshold,
            "drop_depth_threshold": drop_depth_threshold,
        }
        self.data = {
            "rosters": [], "available": [], "schedule": [], "standings": [],
            "adds": [], "pickups": [], "drops": [], "trades": [], "deltas": [],
        }

    def export_rosters(self, rosters_df: pd.DataFrame):
        """Collect rostered players."""
        self.data["rosters"] = _records(rosters_df, _ROSTER_COLS)

    def export_available(self, available_df: pd.DataFrame):
        """Collect available (free agent) players."""
        self.data["available"] = _records(available_df, _AVAILABLE_COLS)

    def export_schedule(self, schedule_df: pd.DataFrame):
        """Collect the simulated league schedule."""
        self.data["schedule"] = _records(schedule_df, _SCHEDULE_COLS)

    def export_standings(self, standings_df: pd.DataFrame):
        """Collect simulated standings."""
        self.data["standings"] = _records(standings_df, _STANDINGS_COLS)

    def export_analysis(self, data_df: pd.DataFrame, sheet_name: str,
                        freeze_cols: int = 1):
        """
        Collect an analysis table ("Adds", "Pickups", "Drops" or "Trades").

        ``freeze_cols`` is accepted for signature parity with the Excel
        exporter and ignored.
        """
        key = sheet_name.lower()
        if key not in ("adds", "pickups", "drops", "trades"):
            raise ValueError(f"Unknown analysis table: {sheet_name!r}")
        self.data[key] = _records(data_df)

    def export_deltas(self, deltas_df: pd.DataFrame):
        """
        Collect per-game deltas (the ``--deltas`` rooting guide).

        ``deltas_df`` is the frame returned by ``League.perGameDelta``: one row
        per hypothetical winner (``winner`` column), one column per team holding
        that team's change in expected earnings if that winner wins.
        """
        self.data["deltas"] = _records(deltas_df)

    def _payload(self) -> dict:
        # The report is scoped to one team at a time, so "me" must be a team
        # that actually appears in the standings.
        teams = [row["team"] for row in self.data["standings"]]
        me = self.me if self.me in teams or not teams else teams[0]
        payload = {
            "week": self.week,
            "day": self.day or "Weekly",
            "sims": self.sims,
            "me": me,
            "bestball": self.bestball,
            "config": self.config,
        }
        payload.update(self.data)
        return payload

    def render(self) -> str:
        """Render the report to an HTML string."""
        env = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "j2"]),
        )

        def _read(name: str) -> str:
            with open(os.path.join(_TEMPLATE_DIR, name), encoding="utf-8") as f:
                return f.read()

        # Keep "</script>" and HTML comment openers out of the JSON blob.
        data_json = (
            json.dumps(self._payload(), allow_nan=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        return env.get_template("report.html.j2").render(
            week=self.week,
            bestball=self.bestball,
            platform=self.platform,
            css=Markup(_read("industry-styles.css")),
            js=Markup(_read("report.js")),
            data_json=Markup(data_json),
        )

    def close(self):
        """Write the HTML file."""
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(self.render())
