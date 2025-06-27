#!/usr/bin/env python3
"""
Test suite for League initialization.

These tests focus on the core League() setup process and ensure
the basic data loading pipeline works correctly.
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from fantasyfb.core.league import League
from fantasyfb.utils.config import LeagueConfig
from tests.fixtures import load_real_fixture


class TestLeagueInitialization:
    """Test League object creation and basic setup."""
    
    @pytest.fixture
    def mock_yahoo_client(self):
        """Mock Yahoo API client to avoid real API calls during testing."""
        mock_client = Mock()
        
        # Use real API response structure
        user_leagues = load_real_fixture("user_leagues")
        league_settings = load_real_fixture("league_settings")
        league_standings = load_real_fixture("league_standings")

        # Feed mock with realistic data
        mock_client.get_user_leagues.return_value = user_leagues
        mock_client.get_league_settings.return_value = league_settings
        mock_client.get_league_standings.return_value = league_standings
        mock_client.get_current_week.return_value = 10
        
        return mock_client
    
    @pytest.fixture 
    def mock_data_manager(self):
        """Mock DataManager to isolate League testing."""
        mock_dm = Mock()
        
        # Mock basic data loading methods
        mock_dm.load_league_id.return_value = ("123.l.456789", [])
        mock_dm.load_league_settings.return_value = (
            {"playoff_start_week": 14, "num_playoff_teams": 6},
            {"Pass Yds": 0.04, "Pass TD": 6.0, "Rec": 1.0},
            pd.DataFrame({
                "position": ["QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN"],
                "count": [1, 2, 2, 1, 1, 1, 1, 6]
            })
        )
        mock_dm.load_fantasy_teams.return_value = [
            {"team_key": "123.l.456789.t.1", "name": "The Algorithm"},
            {"team_key": "123.l.456789.t.2", "name": "Opponent Team"}
        ]
        mock_dm.get_current_week.return_value = 10
        mock_dm.load_nfl_teams.return_value = pd.DataFrame({
            "real_abbrev": ["SF", "KC"],
            "yahoo": ["SF", "KC"]
        })
        mock_dm.load_nfl_schedule.return_value = pd.DataFrame({
            "season": [2024],
            "week": [10], 
            "team": ["SF"],
            "elo_diff": [0.1]
        })
        
        return mock_dm

    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_basic_league_creation(self, mock_dm_class, mock_yahoo_class, 
                                   mock_yahoo_client, mock_data_manager):
        """Test that a League can be created with minimal parameters."""
        # Setup mocks
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        # Create league
        league = League(team_name="The Algorithm", season=2024, week=10)
        
        # Verify basic attributes are set
        assert league.team_name == "The Algorithm"
        assert league.season == 2024
        assert league.week == 10
        assert league.lg_id == "123.l.456789"
        
        # Verify data loading was called
        mock_data_manager.load_league_id.assert_called_once_with(2024, "The Algorithm")
        mock_data_manager.load_league_settings.assert_called_once_with("123.l.456789")
        mock_data_manager.load_fantasy_teams.assert_called_once_with("123.l.456789")
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_league_with_custom_config(self, mock_dm_class, mock_yahoo_class,
                                       mock_yahoo_client, mock_data_manager):
        """Test League creation with custom configuration."""
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        # Custom config
        config = LeagueConfig(num_teams=10, playoff_start_week=15)
        
        league = League(
            team_name="The Algorithm", 
            season=2024, 
            config=config
        )
        
        assert league.config.num_teams == 10
        assert league.config.playoff_start_week == 15
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_league_default_season_calculation(self, mock_dm_class, mock_yahoo_class,
                                               mock_yahoo_client, mock_data_manager):
        """Test that League correctly calculates current season when not provided."""
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        # Mock current date to test season calculation
        with patch('datetime.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 10, 1)  # October = current NFL season
            
            league = League(team_name="The Algorithm")
            
            assert league.season == 2024
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_league_settings_parsing(self, mock_dm_class, mock_yahoo_class,
                                     mock_yahoo_client, mock_data_manager):
        """Test that league settings are correctly parsed and stored."""
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        league = League(team_name="The Algorithm", season=2024)
        
        # Check settings were loaded
        assert league.settings["playoff_start_week"] == 14
        assert league.settings["num_playoff_teams"] == 6
        
        # Check scoring was loaded
        assert league.scoring["Pass Yds"] == 0.04
        assert league.scoring["Pass TD"] == 6.0
        
        # Check roster spots were loaded
        assert len(league.roster_spots) == 8
        assert league.roster_spots.loc[league.roster_spots.position == "QB", "count"].iloc[0] == 1
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_league_teams_loading(self, mock_dm_class, mock_yahoo_class,
                                  mock_yahoo_client, mock_data_manager):
        """Test that fantasy teams are correctly loaded."""
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        league = League(team_name="The Algorithm", season=2024)
        
        assert len(league.teams) == 2
        assert league.teams[0]["name"] == "The Algorithm"
        assert league.teams[1]["name"] == "Opponent Team"
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_league_lazy_loading_components(self, mock_dm_class, mock_yahoo_class,
                                            mock_yahoo_client, mock_data_manager):
        """Test that analysis components are lazy loaded."""
        mock_yahoo_class.return_value = mock_yahoo_client
        mock_dm_class.return_value = mock_data_manager
        
        league = League(team_name="The Algorithm", season=2024)
        
        # Components should not be initialized yet
        assert league._player_analyzer is None
        assert league._simulator is None
        assert league._trade_analyzer is None
        
        # Accessing should trigger initialization
        player_analyzer = league.player_analyzer
        assert league._player_analyzer is not None
        assert player_analyzer is league.player_analyzer  # Should return same instance
    
    @patch('fantasyfb.core.league.YahooClient')
    def test_data_manager_initialization_failure(self, mock_yahoo_class):
        """Test graceful handling when DataManager initialization fails."""
        mock_yahoo_class.return_value = Mock()
        
        # Mock DataManager to raise an exception during initialization
        with patch('fantasyfb.core.league.DataManager') as mock_dm_class:
            mock_dm = Mock()
            mock_dm.load_league_id.side_effect = Exception("API Error")
            mock_dm_class.return_value = mock_dm
            
            with pytest.raises(Exception) as exc_info:
                League(team_name="The Algorithm")
            
            assert "API Error" in str(exc_info.value)


class TestLeagueDataLoading:
    """Test League's data loading methods."""
    
    @pytest.fixture
    def mock_league(self):
        """Create a mock league for testing data loading."""
        with patch('fantasyfb.core.league.YahooClient'), \
             patch('fantasyfb.core.league.DataManager') as mock_dm_class:
            
            mock_dm = Mock()
            mock_dm.load_league_id.return_value = ("123.l.456789", [])
            mock_dm.load_league_settings.return_value = ({}, {}, pd.DataFrame())
            mock_dm.load_fantasy_teams.return_value = []
            mock_dm.get_current_week.return_value = 10
            mock_dm.load_nfl_teams.return_value = pd.DataFrame()
            mock_dm.load_nfl_schedule.return_value = pd.DataFrame()
            mock_dm_class.return_value = mock_dm
            
            league = League(team_name="Test")
            league.data_manager = mock_dm
            return league
    
    def test_load_players_caching(self, mock_league):
        """Test that load_players caches results correctly."""
        # Mock player data
        mock_players = pd.DataFrame({
            "name": ["Player 1", "Player 2"],
            "position": ["QB", "RB"],
            "fantasy_team": [None, "Test Team"]
        })
        
        # Mock the data manager and player analyzer
        mock_league.data_manager.load_players.return_value = mock_players
        
        # Mock the private attribute that backs the property
        mock_analyzer = Mock()
        mock_analyzer.process_players.return_value = mock_players
        mock_league._player_analyzer = mock_analyzer
        
        # First call should load data
        players1 = mock_league.load_players()
        
        # Second call should use cached data
        players2 = mock_league.load_players()
        
        # Should be the same object (cached)
        assert players1 is players2
        
        # Data manager should only be called once
        assert mock_league.data_manager.load_players.call_count == 1
    
    def test_load_players_force_refresh(self, mock_league):
        """Test that force_refresh bypasses cache."""
        mock_players = pd.DataFrame({
            "name": ["Player 1"],
            "position": ["QB"]
        })
        
        mock_league.data_manager.load_players.return_value = mock_players
        
        # Mock the private attribute that backs the property
        mock_analyzer = Mock()
        mock_analyzer.process_players.return_value = mock_players
        mock_league._player_analyzer = mock_analyzer
        
        # Load once
        mock_league.load_players()
        
        # Force refresh should call data manager again
        mock_league.load_players(force_refresh=True)
        
        assert mock_league.data_manager.load_players.call_count == 2


class TestLeagueErrorHandling:
    """Test error handling in League initialization."""
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_missing_team_name_error(self, mock_dm_class, mock_yahoo_class):
        """Test handling when team name is not found."""
        mock_yahoo = Mock()
        mock_dm = Mock()
        
        # Simulate team not found error
        mock_dm.load_league_id.side_effect = ValueError("Can't find team")
        
        mock_yahoo_class.return_value = mock_yahoo
        mock_dm_class.return_value = mock_dm
        
        with pytest.raises(ValueError, match="Can't find team"):
            League(team_name="Nonexistent Team")
    
    @patch('fantasyfb.core.league.YahooClient')
    @patch('fantasyfb.core.league.DataManager')
    def test_invalid_season_error(self, mock_dm_class, mock_yahoo_class):
        """Test handling of invalid season parameter."""
        mock_yahoo = Mock()
        mock_dm = Mock()
        
        # Setup proper return values
        mock_dm.load_league_id.return_value = ("123.l.456789", [])
        mock_dm.load_league_settings.return_value = ({}, {}, pd.DataFrame())
        mock_dm.load_fantasy_teams.return_value = []
        mock_dm.get_current_week.return_value = 10
        mock_dm.load_nfl_teams.return_value = pd.DataFrame()
        mock_dm.load_nfl_schedule.return_value = pd.DataFrame()
        
        mock_yahoo_class.return_value = mock_yahoo
        mock_dm_class.return_value = mock_dm
        
        # This should work - League should handle any reasonable season
        league = League(team_name="Test", season=2030)
        assert league.season == 2030


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
