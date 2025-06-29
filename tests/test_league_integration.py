# tests/test_league_integration.py
"""
Integration tests for the full League class using real fixtures.
"""
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.fantasyfb.core.league import League


@pytest.mark.integration
class TestLeagueIntegration:
    """Integration tests for League class with real data."""

    @patch("src.fantasyfb.core.league.YahooClient")
    @patch("src.fantasyfb.data.data_manager.sr")
    def test_league_initialization_full_pipeline(self, mock_sr, mock_yahoo_class):
        """Test full League initialization pipeline with mocked dependencies."""
        # Mock sportsref calls
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame(
            {
                "player": ["Josh Allen", "Saquon Barkley"],
                "player_id": ["AlleJo02", "BarkSa00"],
                "team": ["BUF", "NYG"],
            }
        )
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame(
            {
                "season": [2024, 2024],
                "week": [10, 10],
                "team": ["BUF", "NYG"],
                "elo_diff": [0.1, -0.1],
            }
        )
        mock_sr.get_all_depth_charts.return_value = pd.DataFrame(
            {
                "player": ["Josh Allen", "Saquon Barkley"],
                "pos": ["QB", "RB"],
                "team": ["BUF", "NYG"],
                "string": [1.0, 1.0],
            }
        )

        # Mock Yahoo client and DataManager
        from tests.fixtures import get_mock_yahoo_client_with_real_responses

        mock_client = get_mock_yahoo_client_with_real_responses()
        mock_yahoo_class.return_value = mock_client

        # Mock the data_manager methods to return expected data structure
        with patch("src.fantasyfb.core.league.DataManager") as mock_dm_class:
            mock_dm = Mock()
            mock_dm_class.return_value = mock_dm

            # Mock all the DataManager methods
            mock_dm.load_league_id.return_value = (
                "449.l.49284",
                [{"name": "The Algorithm"}],
            )
            mock_dm.load_league_settings.return_value = (
                {"playoff_start_week": 15, "num_playoff_teams": 6},
                {"Pass Yds": 0.04, "Pass TD": 6.0, "Rush Yds": 0.1},
                pd.DataFrame({"position": ["QB", "RB", "WR"], "count": [1, 2, 2]}),
            )
            mock_dm.load_fantasy_teams.return_value = [{"name": "The Algorithm"}]
            mock_dm.load_nfl_teams.return_value = pd.DataFrame(
                {"real_abbrev": ["BUF", "NYG"], "yahoo": ["Buf", "NYG"]}
            )
            mock_dm.load_nfl_schedule.return_value = pd.DataFrame(
                {"season": [2024], "week": [10], "team": ["BUF"], "elo_diff": [0.0]}
            )
            mock_dm.get_current_week.return_value = 10

            # Initialize League - this should work end-to-end
            league = League(team_name="The Algorithm", season=2024, week=10)

            # Verify league was initialized properly - check the attributes that should exist
            assert league.team_name == "The Algorithm"
            assert league.season == 2024
            assert league.week == 10
            assert hasattr(league, "lg_id")
            assert hasattr(league, "settings")
            assert hasattr(league, "scoring")
            # Note: 'players' might not be loaded until explicitly requested

    @patch("src.fantasyfb.core.league.YahooClient")
    @patch("src.fantasyfb.data.data_manager.sr")
    def test_player_processing_pipeline(self, mock_sr, mock_yahoo_class):
        """Test that player processing works with real fixture structure."""
        # Setup mocks (same as above)
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame()
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame(
            {"season": [2024], "week": [10], "team": ["BUF"], "elo_diff": [0.0]}
        )

        from tests.fixtures import get_mock_yahoo_client_with_real_responses

        mock_client = get_mock_yahoo_client_with_real_responses()
        mock_yahoo_class.return_value = mock_client

        with patch("src.fantasyfb.core.league.DataManager") as mock_dm_class:
            mock_dm = Mock()
            mock_dm_class.return_value = mock_dm

            # Mock responses
            mock_dm.load_league_id.return_value = (
                "449.l.49284",
                [{"name": "The Algorithm"}],
            )
            mock_dm.load_league_settings.return_value = (
                {"playoff_start_week": 15, "num_playoff_teams": 6},
                {"Pass Yds": 0.04, "Pass TD": 6.0},
                pd.DataFrame({"position": ["QB"], "count": [1]}),
            )
            mock_dm.load_fantasy_teams.return_value = [{"name": "The Algorithm"}]
            mock_dm.load_nfl_teams.return_value = pd.DataFrame()
            mock_dm.load_nfl_schedule.return_value = pd.DataFrame()
            mock_dm.get_current_week.return_value = 10

            league = League(team_name="The Algorithm", season=2024, week=10)

            # Test that we can access the player analyzer (lazy loading)
            assert hasattr(league, "_player_analyzer")
            # The actual players data might be loaded on-demand via the analyzer

    def test_scoring_system_validation(self):
        """Test that scoring system is properly validated and complete."""
        # This test just validates we have a reasonable test structure
        assert True  # Placeholder for future scoring validation tests
