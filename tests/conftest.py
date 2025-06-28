# tests/conftest.py
"""
Pytest configuration and shared fixtures.

This file contains pytest configuration and fixtures that are shared
across multiple test files.
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch
from pathlib import Path

from tests.fixtures import get_mock_yahoo_client_with_real_responses
from src.fantasyfb.data.data_manager import DataManager


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "real_api: tests that require real API fixtures"
    )
    config.addinivalue_line(
        "markers", "integration: integration tests that test multiple components"
    )
    config.addinivalue_line(
        "markers", "slow: tests that take longer to run"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names/locations."""
    for item in items:
        # Add real_api marker to tests using real fixtures
        if "real_fixture" in item.name or "test_real" in item.name:
            item.add_marker(pytest.mark.real_api)
        
        # Add integration marker to integration tests
        if "integration" in str(item.fspath) or "test_integration" in item.name:
            item.add_marker(pytest.mark.integration)
        
        # Add slow marker to tests that might be slow
        if any(keyword in item.name for keyword in ["simulation", "season_sim", "bestball"]):
            item.add_marker(pytest.mark.slow)


# Shared fixtures
@pytest.fixture
def mock_yahoo_client():
    """Mock Yahoo client with real API responses."""
    return get_mock_yahoo_client_with_real_responses()


@pytest.fixture
def mock_data_manager(mock_yahoo_client):
    """Mock DataManager with real fixture responses."""
    return DataManager(mock_yahoo_client)


@pytest.fixture
def sample_league_settings():
    """Sample league settings for testing."""
    return {
        "playoff_start_week": 15,
        "num_playoff_teams": 6,
        "max_teams": 12,
        "trade_end_date": "",
        "waiver_type": "FR",
        "uses_faab": True
    }


@pytest.fixture
def sample_scoring_config():
    """Sample scoring configuration for testing."""
    return {
        "Pass Yds": 0.04,
        "Pass TD": 6.0,
        "Int Thrown": -2.0,
        "Rush Yds": 0.1,
        "Rush TD": 6.0,
        "Rec Yds": 0.1,
        "Rec TD": 6.0,
        "Rec": 0.0,  # Standard scoring, not PPR
        "Fum Lost": -2.0,
        "2-PT": 2.0,
        "PAT Made": 1.0,
        "Sack": 1.0,
        "Int": 2.0,
        "Fum Rec": 2.0,
        "TD": 6.0,
        "Safe": 2.0,
        "Blk Kick": 2.0,
        "Pts Allow 0": 10.0,
        "Pts Allow 1-6": 7.0,
        "Pts Allow 7-13": 4.0,
        "Pts Allow 14-20": 1.0,
        "Pts Allow 21-27": 0.0,
        "Pts Allow 28-34": -1.0,
        "Pts Allow 35+": -4.0,
        # Defaults for missing categories
        "Pass Comp": 0.0,
        "Pass 1D": 0.0,
        "Rush Att": 0.0,
        "Rush 1D": 0.0,
        "Rec 1D": 0.0,
        "TE Rec Bonus": 0.0,
        "TE 1D Bonus": 0.0,
        "Pass 300+": 0.0,
        "Rush 100+": 0.0,
        "Rec 100+": 0.0,
        "Ret Yds": 0.05,
        "Ret TD": 6.0,
        "FG 0-19": 3.0,
        "FG 20-29": 3.0,
        "FG 30-39": 3.0,
        "FG 40-49": 4.0,
        "FG 50+": 5.0
    }


@pytest.fixture
def sample_roster_spots():
    """Sample roster configuration for testing."""
    return pd.DataFrame({
        "position": ["QB", "RB", "WR", "TE", "W/T", "W/R/T", "K", "DEF", "BN", "IR"],
        "count": [1, 2, 2, 1, 1, 1, 1, 1, 5, 1]
    })


@pytest.fixture
def sample_fantasy_teams():
    """Sample fantasy teams for testing."""
    return [
        {"team_key": "449.l.49284.t.1", "name": "Team 1", "manager": "Manager 1"},
        {"team_key": "449.l.49284.t.2", "name": "Team 2", "manager": "Manager 2"},
        {"team_key": "449.l.49284.t.3", "name": "Team 3", "manager": "Manager 3"},
        {"team_key": "449.l.49284.t.4", "name": "Team 4", "manager": "Manager 4"},
        {"team_key": "449.l.49284.t.5", "name": "Team 5", "manager": "Manager 5"},
        {"team_key": "449.l.49284.t.6", "name": "Team 6", "manager": "Manager 6"},
        {"team_key": "449.l.49284.t.7", "name": "Team 7", "manager": "Manager 7"},
        {"team_key": "449.l.49284.t.8", "name": "Team 8", "manager": "Manager 8"},
        {"team_key": "449.l.49284.t.9", "name": "The Algorithm", "manager": "Taylor"},
        {"team_key": "449.l.49284.t.10", "name": "Team 10", "manager": "Manager 10"},
        {"team_key": "449.l.49284.t.11", "name": "Team 11", "manager": "Manager 11"},
        {"team_key": "449.l.49284.t.12", "name": "Team 12", "manager": "Manager 12"},
    ]


@pytest.fixture
def sample_players_data():
    """Sample player data for testing."""
    return pd.DataFrame({
        "name": ["Josh Allen", "Saquon Barkley", "Tyreek Hill", "Travis Kelce", "Justin Tucker", "Buffalo Defense"],
        "position": ["QB", "RB", "WR", "TE", "K", "DEF"],
        "current_team": ["BUF", "PHI", "MIA", "KC", "BAL", "BUF"],
        "player_id": [100001, 100002, 100003, 100004, 100005, 100006],
        "player_id_sr": ["AlleJo02", "BarkSa00", "HillTy00", "KelcTr01", "TuckJu01", "BUF"],
        "fantasy_team": ["The Algorithm", "Team 1", "Team 2", "Team 3", "Team 4", "The Algorithm"],
        "selected_position": ["QB", "RB", "WR", "TE", "K", "DEF"],
        "starter": [True, True, True, True, True, True],
        "points_avg": [22.5, 15.3, 14.8, 12.1, 8.5, 9.2],
        "points_stdev": [6.2, 4.8, 5.1, 3.9, 2.1, 4.3],
        "WAR": [3.2, 2.1, 1.8, 1.5, 0.8, 1.0],
        "bye_week": [12, 7, 6, 10, 14, 12],
        "status": [None, None, None, "Q", None, None],
        "until": [None, None, None, None, None, None],
        "string": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "pct_rostered": [99.8, 98.5, 97.2, 95.1, 78.3, 65.4]
    })


@pytest.fixture
def mock_sportsref():
    """Mock sportsref module to avoid external dependencies."""
    with patch('src.fantasyfb.utils.sportsref_nfl') as mock_sr:
        # Mock common sportsref functions
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame({
            'player': ['Josh Allen', 'Saquon Barkley'], 
            'player_id': ['AlleJo02', 'BarkSa00'],
            'team': ['BUF', 'PHI'],
            'season': [2024, 2024]
        })
        
        mock_sr.get_draft.return_value = pd.DataFrame({
            'player': ['Caleb Williams'],
            'player_id': ['WillCa05'], 
            'team_abbrev': ['CHI'],
            'draft_pick': [1]
        })
        
        mock_sr.get_all_depth_charts.return_value = pd.DataFrame({
            'player': ['Josh Allen', 'Saquon Barkley'],
            'pos': ['QB', 'RB'],
            'team': ['BUF', 'PHI'], 
            'string': [1.0, 1.0]
        })
        
        # Mock Schedule class
        mock_schedule = Mock()
        mock_schedule.schedule = pd.DataFrame({
            'season': [2024, 2024],
            'week': [1, 2], 
            'team': ['BUF', 'PHI'],
            'elo_diff': [0.1, -0.05],
            'opp_elo': [1520, 1480]
        })
        mock_sr.Schedule.return_value = mock_schedule
        
        yield mock_sr


@pytest.fixture
def mock_external_data():
    """Mock external data sources (GitHub CSVs, etc.)."""
    mock_team_abbrevs = pd.DataFrame({
        'real_abbrev': ['BUF', 'PHI', 'MIA', 'KC', 'BAL'],
        'yahoo': ['Buf', 'Phi', 'Mia', 'KC', 'Bal'],
        'fivethirtyeight': ['BUF', 'PHI', 'MIA', 'KC', 'BAL']
    })
    
    mock_name_corrections = pd.DataFrame({
        'name': ['Josh Allen'],
        'new_name': ['Joshua Allen']
    })
    
    with patch('pandas.read_csv') as mock_read_csv:
        def side_effect(url, **kwargs):
            if 'team_abbrevs' in url:
                return mock_team_abbrevs
            elif 'name_corrections' in url:
                return mock_name_corrections
            elif 'injured_list' in url:
                return pd.DataFrame({
                    'player_id_sr': ['KelcTr01'],
                    'name': ['Travis Kelce'], 
                    'position': ['TE'],
                    'until': [10]
                })
            else:
                return pd.DataFrame()
        
        mock_read_csv.side_effect = side_effect
        yield mock_read_csv


@pytest.fixture(scope="session")
def fixtures_available():
    """Check if real fixtures are available."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    required_fixtures = [
        "user_leagues_real.json",
        "league_settings_real.json"
    ]
    
    available = all((fixtures_dir / fixture).exists() for fixture in required_fixtures)
    
    if not available:
        pytest.skip("Real fixtures not available. Run 'python capture_fixtures.py' first.")
    
    return True


# Custom pytest markers for skipping tests
def pytest_runtest_setup(item):
    """Skip tests if required fixtures are not available."""
    if item.get_closest_marker("real_api"):
        fixtures_dir = Path(__file__).parent / "fixtures"
        if not fixtures_dir.exists() or not any(fixtures_dir.glob("*_real.json")):
            pytest.skip("Real API fixtures not available")


# Helper functions for tests
@pytest.fixture
def assert_dataframe_structure():
    """Helper function to assert DataFrame structure."""
    def _assert_structure(df, expected_columns, min_rows=0):
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= min_rows
        for col in expected_columns:
            assert col in df.columns
        return True
    return _assert_structure


@pytest.fixture
def assert_scoring_complete():
    """Helper function to assert scoring configuration is complete."""
    def _assert_complete(scoring_dict):
        required_categories = [
            "Pass Yds", "Pass TD", "Int Thrown", "Rush Yds", "Rush TD",
            "Rec Yds", "Rec TD", "Rec", "Fum Lost", "2-PT", "PAT Made",
            "Sack", "Int", "Fum Rec", "TD", "Safe", "Blk Kick",
            "Pts Allow 0", "Pts Allow 1-6", "Pts Allow 35+"
        ]
        
        for category in required_categories:
            assert category in scoring_dict
            assert isinstance(scoring_dict[category], (int, float))
        
        return True
    return _assert_complete


# Environment setup for tests
@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Set up test environment variables and paths."""
    # Ensure we don't accidentally make real API calls
    monkeypatch.setenv("CONSUMER_KEY", "test_key")
    monkeypatch.setenv("CONSUMER_SECRET", "test_secret")
    
    # Set test data paths
    test_dir = Path(__file__).parent
    monkeypatch.setenv("TEST_DATA_DIR", str(test_dir / "fixtures"))


# Cleanup fixtures
@pytest.fixture
def cleanup_test_files():
    """Cleanup test files after tests."""
    created_files = []
    
    def _add_file(filepath):
        created_files.append(Path(filepath))
    
    yield _add_file
    
    # Cleanup after test
    for filepath in created_files:
        if filepath.exists():
            filepath.unlink()


# Performance testing fixtures
@pytest.fixture
def performance_timer():
    """Simple performance timer for tests."""
    import time
    
    times = {}
    
    def start_timer(name):
        times[name] = time.time()
    
    def end_timer(name):
        if name in times:
            return time.time() - times[name]
        return None
    
    timer = Mock()
    timer.start = start_timer
    timer.end = end_timer
    return timer