"""Tests for ScheduleManager's delegation to a FantasyPlatformClient and
its platform-agnostic schedule post-processing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb.sim.schedule_manager import ScheduleManager

TEAMS = [
    {"team_key": "1", "name": "Zeta", "manager": "Zed"},
    {"team_key": "2", "name": "Alpha", "manager": "Ann"},
]

SETTINGS = {"playoff_start_week": 15, "num_playoff_teams": 6, "end_week": 17}


class FakeClient:
    def __init__(self, schedule: pd.DataFrame):
        self._schedule = schedule
        self.refresh_oauth_calls = 0
        self.get_schedule_calls = []

    def refresh_oauth(self, threshold: int = 59) -> None:
        self.refresh_oauth_calls += 1

    def get_schedule(self, teams, current_week, playoff_start_week, end_week=None):
        self.get_schedule_calls.append(
            {
                "teams": teams,
                "current_week": current_week,
                "playoff_start_week": playoff_start_week,
                "end_week": end_week,
            }
        )
        return self._schedule


def make_manager(schedule: pd.DataFrame, settings: dict = None) -> tuple:
    client = FakeClient(schedule)
    manager = ScheduleManager(client, TEAMS, settings or SETTINGS, "123", 2026)
    return manager, client


class TestScheduleManagerDelegation:
    def test_delegates_to_client_get_schedule(self):
        raw = pd.DataFrame(
            {
                "week": [1],
                "team_1": ["Alpha"],
                "team_2": ["Zeta"],
                "score_1": [100.0],
                "score_2": [90.0],
            }
        )
        manager, client = make_manager(raw)
        manager.get_schedule(season=2026, week=3, current_week=3)

        assert client.refresh_oauth_calls == 1
        assert len(client.get_schedule_calls) == 1
        call = client.get_schedule_calls[0]
        assert call["playoff_start_week"] == 15
        assert call["end_week"] == 17
        # current_week is derived so that client.get_schedule's own
        # max(playoff_start_week, current_week + 1) reproduces the same
        # limit ScheduleManager computed pre-refactor.
        assert call["current_week"] == max(15, 3 % 100 + 1) - 1

    def test_passes_end_week_from_settings(self):
        raw = pd.DataFrame(columns=["week", "team_1", "team_2", "score_1", "score_2"])
        manager, client = make_manager(raw, {**SETTINGS, "end_week": 18})
        manager.get_schedule(season=2026, week=1, current_week=1)
        assert client.get_schedule_calls[0]["end_week"] == 18


class TestScheduleManagerCleanSchedule:
    def test_standardizes_team_order_alphabetically(self):
        raw = pd.DataFrame(
            {
                "week": [1],
                "team_1": ["Zeta"],
                "team_2": ["Alpha"],
                "score_1": [90.0],
                "score_2": [100.0],
            }
        )
        manager, _ = make_manager(raw)
        schedule = manager.get_schedule(season=2026, week=3, current_week=3)
        row = schedule.iloc[0]
        assert row["team_1"] == "Alpha"
        assert row["team_2"] == "Zeta"
        assert row["score_1"] == 100.0
        assert row["score_2"] == 90.0

    def test_multi_row_swap_does_not_alias_scores(self):
        # Regression test for a pandas block-manager aliasing bug: with
        # multiple rows needing a swap, an uncopied .values array can view
        # into the same block being assigned into, corrupting every row's
        # score_2 to whatever score_1 or score_2 the assignment last wrote.
        raw = pd.DataFrame(
            {
                "week": [1, 1, 2],
                "team_1": ["Zeta", "Bravo", "Alpha"],
                "team_2": ["Alpha", "Alpha", "Zeta"],
                "score_1": [90.0, 70.0, 50.0],
                "score_2": [100.0, 80.0, 60.0],
            }
        )
        manager, _ = make_manager(raw)
        schedule = manager.get_schedule(season=2026, week=3, current_week=3)

        def row(week, team_1, team_2):
            match = schedule[
                (schedule["week"] == week)
                & (schedule["team_1"] == team_1)
                & (schedule["team_2"] == team_2)
            ]
            assert len(match) == 1
            return match.iloc[0]

        # Week 1 (Zeta, Alpha) gets swapped to (Alpha, Zeta) -> scores flip.
        wk1_alpha_zeta = row(1, "Alpha", "Zeta")
        assert wk1_alpha_zeta["score_1"] == 100.0
        assert wk1_alpha_zeta["score_2"] == 90.0
        wk1_alpha_bravo = row(1, "Alpha", "Bravo")
        assert wk1_alpha_bravo["score_1"] == 80.0
        assert wk1_alpha_bravo["score_2"] == 70.0
        # Week 2 (Alpha, Zeta) is already in order -> scores unchanged.
        wk2_alpha_zeta = row(2, "Alpha", "Zeta")
        assert wk2_alpha_zeta["score_1"] == 50.0
        assert wk2_alpha_zeta["score_2"] == 60.0

    def test_adds_me_column_when_team_key_provided(self):
        raw = pd.DataFrame(
            {
                "week": [1, 1],
                "team_1": ["Alpha", "Alpha"],
                "team_2": ["Zeta", "Zeta"],
                "score_1": [100.0, 100.0],
                "score_2": [90.0, 90.0],
            }
        )
        manager, _ = make_manager(raw)
        schedule = manager.get_schedule(season=2026, week=3, current_week=3, team_key="1")
        assert schedule["me"].all()

    def test_zeroes_scores_for_weeks_at_or_after_as_of(self):
        raw = pd.DataFrame(
            {
                "week": [3, 4],
                "team_1": ["Alpha", "Alpha"],
                "team_2": ["Zeta", "Zeta"],
                "score_1": [100.0, 50.0],
                "score_2": [90.0, 40.0],
            }
        )
        manager, _ = make_manager(raw)
        schedule = manager.get_schedule(season=2026, week=3, current_week=3)
        by_week = schedule.set_index("week")
        assert by_week.loc[3, "score_1"] == 0.0
        assert by_week.loc[4, "score_1"] == 0.0
