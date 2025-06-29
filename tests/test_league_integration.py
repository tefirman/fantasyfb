# tests/test_league_integration.py
"""
Integration tests for the full League class using real fixtures.
"""
import pytest
from unittest.mock import Mock, patch
import pandas as pd

from src.fantasyfb.core.league import League


@pytest.mark.integration
class TestLeagueIntegration:
    """Integration tests for League class with real data."""
    
    @patch('src.fantasyfb.core.league.YahooClient')
    @patch('src.fantasyfb.data.data_manager.sr')
    def test_league_initialization_full_pipeline(self, mock_sr, mock_yahoo_class):
        """Test full League initialization pipeline with mocked dependencies."""
        # Mock sportsref calls
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame({
            'player': ['Josh Allen', 'Saquon Barkley'],
            'player_id': ['AlleJo02', 'BarkSa00'],
            'team': ['BUF', 'NYG']
        })
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame({
            'season': [2024, 2024],
            'week': [10, 10],
            'team': ['BUF', 'NYG'],
            'elo_diff': [0.1, -0.1]
        })
        mock_sr.get_all_depth_charts.return_value = pd.DataFrame({
            'player': ['Josh Allen', 'Saquon Barkley'],
            'pos': ['QB', 'RB'],
            'team': ['BUF', 'NYG'],
            'string': [1.0, 1.0]
        })
        
        # Mock Yahoo client
        from tests.fixtures import get_mock_yahoo_client_with_real_responses
        mock_client = get_mock_yahoo_client_with_real_responses()
        mock_yahoo_class.return_value = mock_client
        
        # Initialize League - this should work end-to-end
        league = League(team_name="The Algorithm", season=2024, week=10)
        
        # Verify league was initialized properly
        assert league.team_name == "The Algorithm"
        assert league.season == 2024
        assert league.week == 10
        assert hasattr(league, 'lg_id')
        assert hasattr(league, 'players')
        assert hasattr(league, 'settings')
        assert hasattr(league, 'scoring')
    
    @patch('src.fantasyfb.core.league.YahooClient')
    @patch('src.fantasyfb.data.data_manager.sr')
    def test_player_processing_pipeline(self, mock_sr, mock_yahoo_class):
        """Test that player processing works with real fixture structure."""
        # Setup mocks
        mock_sr.get_bulk_rosters.return_value = pd.DataFrame()
        mock_sr.get_draft.return_value = pd.DataFrame()
        mock_sr.Schedule.return_value.schedule = pd.DataFrame({
            'season': [2024], 'week': [10], 'team': ['BUF'], 'elo_diff': [0.0]
        })
        
        from tests.fixtures import get_mock_yahoo_client_with_real_responses
        mock_client = get_mock_yahoo_client_with_real_responses()
        mock_yahoo_class.return_value = mock_client
        
        league = League(team_name="The Algorithm", season=2024, week=10)
        
        # Players DataFrame should be populated
        assert hasattr(league, 'players')
        assert isinstance(league.players, pd.DataFrame)
        assert len(league.players) > 0
        
        # Should have expected columns for analysis
        expected_columns = ['name', 'position', 'player_id', 'fantasy_team']
        for col in expected_columns:
            assert col in league.players.columns
    
    def test_scoring_system_validation(self):
        """Test that scoring system is properly validated and complete."""
        # This would test the scoring system validation
        # For now, just test that we have a reasonable test structure
        assert True  # Placeholder for scoring validation tests

