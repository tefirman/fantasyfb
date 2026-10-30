"""Tests for League.for_league(), which reuses one league's projections for another.

Bypasses __init__ via __new__ (see test_get_rates.py) and stubs the two
steps that need NFL data (get_schedule, starters), so only the swap of
league-specific state is exercised.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb import League
from fantasyfb.configs import apply_default_scoring_categories


ROSTER_SPOTS = pd.DataFrame({"position": ["W/R/T", "BN"], "count": [2, 2]})


class FakeClient:
    def __init__(self, rosters, scoring=None, roster_spots=ROSTER_SPOTS):
        self.rosters = rosters
        self.scoring = scoring or {"Rec": 0.5, "Rush Yds": 0.1}
        self.roster_spots = roster_spots
        self.my_team_name = None
        self.lg_id = "other"

    def get_league_config(self):
        return {
            "settings": {"end_week": 17, "playoff_start_week": 12},
            "roster_spots": self.roster_spots,
            "scoring": dict(self.scoring),
        }

    def get_fantasy_teams(self):
        return [{"team_key": "1", "name": "Other Team", "manager": "m"}]

    def get_my_team_key(self):
        return "1" if self.my_team_name == "Other Team" else None

    def get_team_rosters(self, teams, week):
        return self.rosters


@pytest.fixture
def template(monkeypatch):
    monkeypatch.setattr(League, "get_schedule", lambda self: None)
    monkeypatch.setattr(League, "starters", lambda self, week, teams=None: None)
    league = League.__new__(League)
    league.week = 7
    league.latest_season = 2026
    league.scoring = apply_default_scoring_categories({"Rec": 0.5, "Rush Yds": 0.1})
    league.roster_spots = ROSTER_SPOTS
    league.players = pd.DataFrame({
        "player_id": ["a", "b", "c"],
        "points_avg": [10.0, 8.0, 6.0],
        "fantasy_team": ["Template Team", "Template Team", None],
        "selected_position": ["W/R/T", "BN", None],
    })
    return league


def test_rosters_come_from_the_other_league_and_projections_are_shared(template):
    rosters = pd.DataFrame({
        "player_id": ["b", "c"],
        "selected_position": ["W/R/T", "BN"],
        "fantasy_team": ["Other Team", "Other Team"],
    })
    other = template.for_league(FakeClient(rosters), name="Other Team")

    by_id = other.players.set_index("player_id")
    assert by_id.points_avg.to_dict() == {"a": 10.0, "b": 8.0, "c": 6.0}
    assert by_id.fantasy_team.fillna("none").to_dict() == {
        "a": "none", "b": "Other Team", "c": "Other Team"}
    assert other.my_team_key == "1"
    assert other.lg_id == "other"


def test_template_league_is_left_unchanged(template):
    before = template.players.copy()
    rosters = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])
    other = template.for_league(FakeClient(rosters))

    pd.testing.assert_frame_equal(template.players, before)
    assert other.players is not template.players
    assert other.teams == [{"team_key": "1", "name": "Other Team", "manager": "m"}]


def test_zero_weight_scoring_categories_do_not_count_as_a_difference(template):
    rosters = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])
    template.for_league(FakeClient(rosters, scoring={"Rec": 0.5, "Rush Yds": 0.1}))


def test_different_scoring_is_refused(template):
    rosters = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])
    with pytest.raises(ValueError, match="Scoring or roster spots differ"):
        template.for_league(FakeClient(rosters, scoring={"Rec": 1.0, "Rush Yds": 0.1}))


def test_different_roster_spots_are_refused(template):
    rosters = pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])
    spots = pd.DataFrame({"position": ["W/R/T", "BN"], "count": [3, 2]})
    with pytest.raises(ValueError, match="Scoring or roster spots differ"):
        template.for_league(FakeClient(rosters, roster_spots=spots))
