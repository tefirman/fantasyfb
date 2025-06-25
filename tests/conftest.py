"""
Shared pytest fixtures and configuration.
"""

import pytest
import pandas as pd
from unittest.mock import Mock
import os
import sys

# Add src to path so we can import fantasyfb
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture(scope="session")
def sample_nfl_teams():
    """Sample NFL teams data for testing."""
    return pd.DataFrame({
        "real_abbrev": ["SF", "KC", "DAL", "NE"],
        "yahoo": ["SF", "KC", "DAL", "NE"],
        "fivethirtyeight": ["SF", "KC", "DAL", "NE"]
    })


@pytest.fixture(scope="session") 
def sample_roster_spots():
    """Sample roster configuration."""
    return pd.DataFrame({
        "position": ["QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN"],
        "count": [1, 2, 2, 1, 1, 1, 1, 6]
    })


@pytest.fixture(scope="session")
def sample_scoring():
    """Sample scoring configuration."""
    return {
        "Pass Yds": 0.04,
        "Pass TD": 6.0,
        "Rush Yds": 0.1,
        "Rush TD": 6.0,
        "Rec": 1.0,
        "Rec Yds": 0.1,
        "Rec TD": 6.0,
        "FG 0-19": 3.0,
        "PAT Made": 1.0,
        "Sack": 1.0,
        "Int": 2.0,
        "Fum Rec": 2.0,
        "TD": 6.0,
        "Pts Allow 0": 10.0,
    }


@pytest.fixture
def sample_players():
    """Sample player data for testing."""
    return pd.DataFrame({
        "name": ["Josh Allen", "Christian McCaffrey", "Cooper Kupp", "Travis Kelce"],
        "position": ["QB", "RB", "WR", "TE"],
        "current_team": ["BUF", "SF", "LAR", "KC"],
        "fantasy_team": ["Team A", "Team A", "Team B", None],
        "player_id": [1, 2, 3, 4],
        "player_id_sr": ["AlleJo02", "McCaCh01", "KuppCo00", "KelcTr01"],
        "points_avg": [20.5, 15.2, 12.8, 11.5],
        "points_stdev": [5.0, 4.2, 3.8, 3.5],
        "WAR": [2.5, 1.8, 1.2, 1.0],
        "bye_week": [7, 9, 10, 12]
    })


@pytest.fixture
def sample_nfl_schedule():
    """Sample NFL schedule for testing."""
    return pd.DataFrame({
        "season": [2024] * 6,
        "week": [1, 2, 3, 1, 2, 3],
        "team": ["BUF", "BUF", "BUF", "SF", "SF", "SF"],
        "elo_diff": [0.1, -0.2, 0.0, 0.3, -0.1, 0.2],
        "opp_elo": [1500, 1520, 1480, 1510, 1530, 1490]
    })


@pytest.fixture
def sample_fantasy_schedule():
    """Sample fantasy league schedule."""
    return pd.DataFrame({
        "week": [1, 1, 2, 2],
        "team_1": ["Team A", "Team C", "Team A", "Team C"],
        "team_2": ["Team B", "Team D", "Team D", "Team B"],
        "score_1": [120.5, 95.2, None, None],  # Some completed, some future
        "score_2": [110.3, 105.8, None, None]
    })


@pytest.fixture
def mock_yahoo_response():
    """Mock Yahoo API response structure."""
    return {
        "fantasy_content": {
            "league": [
                {},  # Empty first element (Yahoo API quirk)
                {
                    "settings": [
                        {
                            "playoff_start_week": "14",
                            "num_playoff_teams": "6",
                            "stat_categories": {
                                "stats": [
                                    {"stat": {"stat_id": "4", "display_name": "Pass Yds"}},
                                    {"stat": {"stat_id": "5", "display_name": "Pass TD"}},
                                ]
                            },
                            "stat_modifiers": {
                                "stats": [
                                    {"stat": {"stat_id": "4", "value": "0.04"}},
                                    {"stat": {"stat_id": "5", "value": "6"}},
                                ]
                            },
                            "roster_positions": [
                                {"roster_position": {"position": "QB", "count": "1"}},
                                {"roster_position": {"position": "RB", "count": "2"}},
                            ]
                        }
                    ],
                    "standings": [
                        {
                            "teams": {
                                "count": 2,
                                "0": {"team": [{"team_key": "123.l.456.t.1", "name": "Team A"}]},
                                "1": {"team": [{"team_key": "123.l.456.t.2", "name": "Team B"}]}
                            }
                        }
                    ]
                }
            ]
        }
    }


# Disable API calls during testing unless explicitly enabled
@pytest.fixture(autouse=True)
def disable_api_calls(monkeypatch):
    """Automatically disable real API calls during testing."""
    def mock_api_call(*args, **kwargs):
        raise RuntimeError("Real API calls are disabled during testing. Use mocks instead.")
    
    # Mock the main API classes to prevent accidental real calls
    monkeypatch.setattr("requests.get", mock_api_call)
    monkeypatch.setattr("requests.post", mock_api_call)
