# tests/test_real_fixtures.py
"""
Test suite using real Yahoo API responses captured as fixtures.

This test suite validates core functionality using realistic data
structures from actual Yahoo Fantasy API responses.
"""

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.fantasyfb.core.league import League
from src.fantasyfb.data.data_manager import DataManager
from tests.fixtures import (
    extract_sample_data_from_fixtures,
    get_mock_yahoo_client_with_real_responses,
    load_real_fixture,
)


class TestRealFixtures:
    """Test core functionality using real API response fixtures."""

    @pytest.fixture
    def mock_yahoo_client(self):
        """Mock Yahoo client with real API responses."""
        return get_mock_yahoo_client_with_real_responses()

    @pytest.fixture
    def sample_data(self):
        """Extract sample data from real fixtures for assertions."""
        return extract_sample_data_from_fixtures()

    def test_user_leagues_structure(self):
        """Test that user leagues fixture has expected structure."""
        user_leagues = load_real_fixture("user_leagues")

        # Validate top-level structure
        assert "count" in user_leagues
        assert user_leagues["count"] == 47  # Based on your real data

        # Check we have NFL teams for 2024
        nfl_2024_teams = []
        for i in range(user_leagues["count"]):
            game_data = user_leagues[str(i)]["game"]
            if isinstance(game_data, list) and len(game_data) >= 2:
                game_info = game_data[0]
                if game_info.get("code") == "nfl" and game_info.get("season") == "2024":
                    teams = game_data[1]["teams"]
                    for j in range(teams["count"]):
                        team = teams[str(j)]["team"][0]
                        team_name = None
                        for item in team:
                            if isinstance(item, dict) and "name" in item:
                                team_name = item["name"]
                                break
                        if team_name:
                            nfl_2024_teams.append(team_name)

        # Should find some 2024 NFL teams
        assert len(nfl_2024_teams) > 0
        assert "The Algorithm" in nfl_2024_teams  # Based on your data

    def test_league_settings_structure(self):
        """Test that league settings fixture has expected structure."""
        settings = load_real_fixture("league_settings")

        # Validate structure
        assert "fantasy_content" in settings
        assert "league" in settings["fantasy_content"]

        league_data = settings["fantasy_content"]["league"]
        assert isinstance(league_data, list)
        assert len(league_data) >= 2

        # Check league info
        league_info = league_data[0]
        assert league_info["season"] == "2024"
        assert league_info["game_code"] == "nfl"

        # Check settings
        settings_data = league_data[1]["settings"][0]
        assert "playoff_start_week" in settings_data
        assert "num_playoff_teams" in settings_data
        assert "roster_positions" in settings_data
        assert "stat_categories" in settings_data
        assert "stat_modifiers" in settings_data

    def test_data_manager_league_selection(self, mock_yahoo_client):
        """Test DataManager can process real user leagues data."""
        data_manager = DataManager(mock_yahoo_client)

        # This should work with the mocked real response
        lg_id, teams = data_manager.load_league_id(2024, "The Algorithm")

        # Should find "The Algorithm" team
        assert lg_id is not None
        assert lg_id.startswith("449.l.")  # Based on your real data

    @patch("src.fantasyfb.data.data_manager.sr.get_bulk_rosters")
    @patch("src.fantasyfb.data.data_manager.sr.get_draft")
    def test_data_manager_settings_processing(
        self, mock_draft, mock_rosters, mock_yahoo_client
    ):
        """Test DataManager processes real settings correctly."""
        # Mock the sportsref dependencies
        mock_rosters.return_value = pd.DataFrame()
        mock_draft.return_value = pd.DataFrame()

        data_manager = DataManager(mock_yahoo_client)

        # Use real league settings
        settings, scoring, roster_spots = data_manager.load_league_settings(
            "449.l.49284"
        )

        # Validate settings processing
        assert isinstance(settings, dict)
        assert "playoff_start_week" in settings
        assert settings["playoff_start_week"] == 15  # From your real data
        assert settings["num_playoff_teams"] == 6

        # Validate scoring processing
        assert isinstance(scoring, dict)
        assert "Pass Yds" in scoring
        assert scoring["Pass Yds"] == 0.04  # From your real data
        assert "Pass TD" in scoring
        assert scoring["Pass TD"] == 6.0

        # Validate roster spots
        assert isinstance(roster_spots, pd.DataFrame)
        assert "position" in roster_spots.columns
        assert "count" in roster_spots.columns

        # Check specific roster requirements from your real data
        qb_spots = roster_spots.loc[roster_spots.position == "QB", "count"].iloc[0]
        assert qb_spots == 1

        wr_spots = roster_spots.loc[roster_spots.position == "WR", "count"].iloc[0]
        assert wr_spots == 2

    def test_scoring_config_completeness(self, mock_yahoo_client):
        """Test that scoring config includes all expected categories."""
        data_manager = DataManager(mock_yahoo_client)
        settings, scoring, roster_spots = data_manager.load_league_settings(
            "449.l.49284"
        )

        # These should all be present (either from API or defaults)
        expected_categories = [
            "Pass Yds",
            "Pass TD",
            "Int Thrown",
            "Rush Yds",
            "Rush TD",
            "Rec Yds",
            "Rec TD",
            "Rec",
            "Fum Lost",
            "2-PT",
            "PAT Made",
            "Sack",
            "Int",
            "Fum Rec",
            "TD",
            "Safe",
            "Blk Kick",
            "Pts Allow 0",
            "Pts Allow 1-6",
            "Pts Allow 7-13",
            "Pts Allow 14-20",
            "Pts Allow 21-27",
            "Pts Allow 28-34",
            "Pts Allow 35+",
        ]

        for category in expected_categories:
            assert category in scoring, f"Missing scoring category: {category}"
            assert isinstance(scoring[category], (int, float))

    @patch("src.fantasyfb.data.data_manager.sr")
    def test_league_initialization_with_real_data(self, mock_sr, mock_yahoo_client):
        """Test League can initialize with real API responses."""
        # Mock the sportsref dependencies
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame()
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame(
            columns=["season", "week"]
        )
        mock_sr.get_all_depth_charts.return_value = pd.DataFrame()

        # Mock the League to use our mocked client instead of creating a real one
        with patch("src.fantasyfb.core.league.YahooClient") as mock_yahoo_class:
            mock_yahoo_class.return_value = mock_yahoo_client

            with patch("src.fantasyfb.core.league.DataManager") as mock_dm_class:
                mock_dm = Mock()
                mock_dm_class.return_value = mock_dm

                # Set up the mock data manager responses
                mock_dm.load_league_id.return_value = ("449.l.49284", [])
                mock_dm.load_league_settings.return_value = (
                    {"playoff_start_week": 15, "num_playoff_teams": 6},
                    {"Pass Yds": 0.04, "Pass TD": 6.0, "Rush Yds": 0.1},
                    pd.DataFrame({"position": ["QB", "RB", "WR"], "count": [1, 2, 2]}),
                )
                mock_dm.load_fantasy_teams.return_value = [{"name": "The Algorithm"}]
                mock_dm.load_nfl_teams.return_value = pd.DataFrame()
                mock_dm.load_nfl_schedule.return_value = pd.DataFrame()
                mock_dm.get_current_week.return_value = 10

                # This should work without errors now
                league = League(team_name="The Algorithm", season=2024, week=10)

                assert league.team_name == "The Algorithm"
                assert league.season == 2024
                assert league.week == 10
                assert league.lg_id == "449.l.49284"

    def test_roster_positions_mapping(self, mock_yahoo_client):
        """Test that roster positions are correctly mapped."""
        data_manager = DataManager(mock_yahoo_client)
        settings, scoring, roster_spots = data_manager.load_league_settings(
            "449.l.49284"
        )

        # Check that all positions from real data are present
        expected_positions = ["QB", "WR", "RB", "W/T", "W/R/T", "K", "DEF", "BN", "IR"]
        actual_positions = roster_spots.position.tolist()

        for pos in expected_positions:
            assert pos in actual_positions, f"Missing roster position: {pos}"

        # Verify counts match real data
        assert roster_spots.loc[roster_spots.position == "QB", "count"].iloc[0] == 1
        assert roster_spots.loc[roster_spots.position == "WR", "count"].iloc[0] == 2
        assert roster_spots.loc[roster_spots.position == "RB", "count"].iloc[0] == 2
        assert roster_spots.loc[roster_spots.position == "BN", "count"].iloc[0] == 5

    def test_sample_data_extraction(self, sample_data):
        """Test that sample data extraction works correctly."""
        # Should extract key values from fixtures
        assert "playoff_start_week" in sample_data
        assert sample_data["playoff_start_week"] == 15

        assert "num_playoff_teams" in sample_data
        assert sample_data["num_playoff_teams"] == 6

        assert "num_teams" in sample_data
        assert sample_data["num_teams"] == 12

        assert "team_names" in sample_data
        assert isinstance(sample_data["team_names"], list)
        assert len(sample_data["team_names"]) == 12


class TestFixtureHelpers:
    """Test the fixture helper functions themselves."""

    def test_load_real_fixture_user_leagues(self):
        """Test loading user leagues fixture."""
        data = load_real_fixture("user_leagues")
        assert isinstance(data, dict)
        assert "count" in data
        assert data["count"] > 0

    def test_load_real_fixture_league_settings(self):
        """Test loading league settings fixture."""
        data = load_real_fixture("league_settings")
        assert isinstance(data, dict)
        assert "fantasy_content" in data

    def test_load_nonexistent_fixture(self):
        """Test error handling for missing fixtures."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_real_fixture("nonexistent_fixture")

        assert "not found" in str(exc_info.value)
        assert "capture_fixtures.py" in str(exc_info.value)

    def test_mock_client_creation(self):
        """Test that mock client is created correctly."""
        mock_client = get_mock_yahoo_client_with_real_responses()

        # Should have the expected methods
        assert hasattr(mock_client, "get_user_leagues")
        assert hasattr(mock_client, "get_league_settings")
        assert hasattr(mock_client, "get_league_standings")

        # Methods should return realistic data
        user_leagues = mock_client.get_user_leagues()
        assert isinstance(user_leagues, dict)
        assert "count" in user_leagues


# Integration-style tests that exercise multiple components
class TestIntegrationWithRealData:
    """Integration tests using real fixture data."""

    @patch("src.fantasyfb.data.data_manager.sr")
    def test_full_data_pipeline(self, mock_sr):
        """Test the full data loading pipeline with real fixtures."""
        # Mock sportsref dependencies
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame(
            {"player": ["Test Player"], "player_id": ["test123"], "team": ["SEA"]}
        )
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame(
            {"season": [2024], "week": [1], "team": ["SEA"], "elo_diff": [0.0]}
        )

        # Use real fixtures
        mock_client = get_mock_yahoo_client_with_real_responses()
        data_manager = DataManager(mock_client)

        # Test each step of the pipeline
        lg_id, teams = data_manager.load_league_id(2024, "The Algorithm")
        assert lg_id.startswith("449.l.")

        settings, scoring, roster_spots = data_manager.load_league_settings(lg_id)
        assert isinstance(settings, dict)
        assert isinstance(scoring, dict)
        assert isinstance(roster_spots, pd.DataFrame)

        teams = data_manager.load_fantasy_teams(lg_id)
        assert isinstance(teams, list)
        assert len(teams) > 0


if __name__ == "__main__":
    # Run specific test
    pytest.main([__file__, "-v"])
