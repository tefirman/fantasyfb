#!/usr/bin/env python3
"""
Test suite for DataManager.

These tests focus on data loading, processing, and integration between
different data sources (Yahoo API, Pro Football Reference, etc.)
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch

from fantasyfb.data.data_manager import DataManager
from fantasyfb.data.yahoo_client import YahooClient
from tests.fixtures import load_real_fixture


class TestDataManagerInitialization:
    """Test DataManager creation and basic setup."""
    
    @pytest.fixture
    def mock_yahoo_client(self):
        """Mock YahooClient for testing."""
        return Mock(spec=YahooClient)
    
    @pytest.fixture
    def data_manager(self, mock_yahoo_client):
        """Create DataManager instance for testing."""
        return DataManager(mock_yahoo_client)
    
    def test_data_manager_creation(self, mock_yahoo_client):
        """Test that DataManager can be created with YahooClient."""
        dm = DataManager(mock_yahoo_client)
        assert dm.yahoo_client == mock_yahoo_client
        assert dm.cache is not None


class TestLeagueIdLoading:
    """Test league ID discovery and team selection."""
    
    @pytest.fixture
    def data_manager(self):
        with patch('fantasyfb.data.data_manager.DataCache'):
            return DataManager(Mock())
    
    def test_league_id_loading_single_team(self, data_manager):
        """Test league ID loading when user has one team."""
        # Mock cache miss
        data_manager.cache.get_cached_data.return_value = None
        
        # Use real API response structure
        real_response = load_real_fixture("user_leagues")
        data_manager.yahoo_client.get_user_leagues.return_value = real_response
        
        # Test the method
        lg_id, team = data_manager.load_league_id(2024, "The Algorithm")
        
        assert lg_id == "449.l.49284"
        assert len(team) > 0
        
        # Verify caching was called
        data_manager.cache.save_data.assert_called_once()
    
    def test_league_id_loading_multiple_teams(self, data_manager):
        """Test league ID loading when user has multiple teams."""
        data_manager.cache.get_cached_data.return_value = None
        
        # Use real API response structure
        real_response = load_real_fixture("user_leagues")
        data_manager.yahoo_client.get_user_leagues.return_value = real_response
        
        lg_id, team = data_manager.load_league_id(2024, "The Algorithm")
        
        assert lg_id == "449.l.49284"
    
    # def test_league_id_loading_team_not_found(self, data_manager):
    #     """Test error handling when team name is not found."""
    #     data_manager.cache.get_cached_data.return_value = None
        
    #     # Use real API response structure
    #     real_response = load_real_fixture("user_leagues")
    #     data_manager.yahoo_client.get_user_leagues.return_value = real_response
        
    #     # TODO: Add error handling for team not found
    #     # This should raise a ValueError if the team is not found
    #     with pytest.raises(ValueError, match="Can't find a team"):
    #         data_manager.load_league_id(2024, "Nonexistent Team")
    
    def test_league_id_loading_cache_hit(self, data_manager):
        """Test that cached results are returned when available."""
        cached_result = ("123.l.cached", [])
        data_manager.cache.get_cached_data.return_value = cached_result
        
        result = data_manager.load_league_id(2024, "Any Team")
        
        assert result == cached_result
        # Yahoo client should not be called when cache hits
        data_manager.yahoo_client.get_user_leagues.assert_not_called()


class TestLeagueSettingsProcessing:
    """Test processing of Yahoo league settings."""
    
    @pytest.fixture
    def data_manager(self):
        with patch('fantasyfb.data.data_manager.DataCache'):
            return DataManager(Mock())
    
    def test_load_league_settings(self, data_manager):
        """Test loading and processing league settings."""
        # Use real API response structure
        real_response = load_real_fixture("league_settings")

        data_manager.cache.get_cached_data.return_value = None
        data_manager.yahoo_client.get_league_settings.return_value = real_response
        
        settings, scoring, roster_spots = data_manager.load_league_settings("123.l.456789")
        
        # Check settings parsing
        assert settings["playoff_start_week"] == 15
        assert settings["num_playoff_teams"] == 6
        assert settings["max_teams"] == 12
        assert settings["trade_end_date"] == ""
        assert settings["waiver_type"] == "FR"
        
        # Check scoring parsing
        assert scoring["Pass Yds"] == 0.04
        assert scoring["Pass TD"] == 6.0
        assert scoring["Int"] == 2.0  # Defense INT (positive)
        assert scoring["Int Thrown"] == -2.0  # QB INT (negative, renamed)
        
        # Check that defaults are added
        assert "Pass Comp" in scoring
        assert scoring["Pass Comp"] == 0.0
        
        # Check roster spots
        assert len(roster_spots) == 9
        assert roster_spots.loc[roster_spots.position == "QB", "count"].iloc[0] == 1
        assert roster_spots.loc[roster_spots.position == "W/R/T", "count"].iloc[0] == 1
    
    def test_scoring_interception_handling(self, data_manager):
        """Test the tricky interception naming logic."""
        # Use real API response structure
        real_response = load_real_fixture("league_settings")
        
        data_manager.cache.get_cached_data.return_value = None
        data_manager.yahoo_client.get_league_settings.return_value = real_response
        
        _, scoring, _ = data_manager.load_league_settings("449.l.49284")
        
        # Should have both types
        assert "Int" in scoring and scoring["Int"] == 2.0  # Defense INT
        assert "Int Thrown" in scoring and scoring["Int Thrown"] == -2.0  # QB INT


class TestPlayerDataProcessing:
    """Test player data loading and processing."""
    
    @pytest.fixture
    def data_manager(self):
        with patch('fantasyfb.data.data_manager.DataCache'):
            return DataManager(Mock())
    
    @pytest.fixture
    def mock_players_raw(self):
        """Mock raw player data from Yahoo API."""
        return [
            {
                "player_id": 1,
                "name": "Josh Allen",
                "display_position": "QB",
                "status": "H",
                "editorial_team_abbr": "BUF",
                "eligible_positions": [{"position": "QB"}]
            },
            {
                "player_id": 2,
                "name": "Christian McCaffrey",
                "display_position": "RB",
                "status": "H",
                "editorial_team_abbr": "SF",
                "eligible_positions": [{"position": "RB"}]
            },
            {
                "player_id": 100024,  # Special defense ID that gets name correction
                "name": "Los Angeles",
                "display_position": "DEF",
                "status": "H",
                "editorial_team_abbr": "LAC",
                "eligible_positions": [{"position": "DEF"}]
            }
        ]
    
    @pytest.fixture
    def mock_rosters(self):
        """Mock roster data from Yahoo API."""
        return {
            "Team A": [
                {"player_id": 1, "name": "Josh Allen", "selected_position": "QB"},
                {"player_id": 2, "name": "Christian McCaffrey", "selected_position": "RB"}
            ],
            "Team B": [
                {"player_id": 100024, "name": "Los Angeles", "selected_position": "DEF"}
            ]
        }
    
    def test_load_players_basic(self, data_manager, mock_players_raw, mock_rosters):
        """Test basic player loading and processing."""
        # Mock cache miss
        data_manager.cache.get_cached_data.return_value = None
        
        # Mock Yahoo API calls
        data_manager.yahoo_client.get_all_players.return_value = mock_players_raw
        data_manager.yahoo_client.get_league_rosters.return_value = mock_rosters
        
        # Mock external data loading
        with patch.object(data_manager, '_add_external_player_data') as mock_external:
            mock_external.return_value = pd.DataFrame({
                "name": ["Josh Allen", "Christian McCaffrey", "Los Angeles Chargers"],
                "position": ["QB", "RB", "DEF"],
                "player_id": [1, 2, 100024],
                "fantasy_team": ["Team A", "Team A", "Team B"],
                "current_team": ["BUF", "SF", "LAC"]
            })
            
            players = data_manager.load_players("123.l.456789", 2024, 10)
            
            assert len(players) == 3
            assert players.loc[players.player_id == 1, "fantasy_team"].iloc[0] == "Team A"
            assert players.loc[players.player_id == 100024, "name"].iloc[0] == "Los Angeles Chargers"
    
    def test_process_players_roster_assignment(self, data_manager):
        """Test that roster assignments are correctly merged with player data."""
        players_raw = [
            {
                "player_id": 1, 
                "name": "Player 1", 
                "display_position": "QB", 
                "editorial_team_abbr": "BUF",
                "status": "H",
                "eligible_positions": [{"position": "QB"}]
            },
            {
                "player_id": 2, 
                "name": "Player 2", 
                "display_position": "RB", 
                "editorial_team_abbr": "SF",
                "status": "H", 
                "eligible_positions": [{"position": "RB"}]
            }
        ]
        
        rosters = {
            "Team A": [{"player_id": 1, "name": "Player 1", "selected_position": "QB"}],
            "Team B": []  # Empty roster
        }
        
        result = data_manager._process_players(players_raw, rosters)
        
        assert len(result) == 2
        assert result.loc[result.player_id == 1, "fantasy_team"].iloc[0] == "Team A"
        assert pd.isna(result.loc[result.player_id == 2, "fantasy_team"].iloc[0])
    
    def test_process_players_defense_name_corrections(self, data_manager):
        """Test that defense names get corrected properly."""
        players_raw = [
            {
                "player_id": 100014, 
                "name": "Los Angeles", 
                "display_position": "DEF", 
                "editorial_team_abbr": "LAR",
                "status": "H",
                "eligible_positions": [{"position": "DEF"}]
            },
            {
                "player_id": 100024, 
                "name": "Los Angeles", 
                "display_position": "DEF", 
                "editorial_team_abbr": "LAC",
                "status": "H",
                "eligible_positions": [{"position": "DEF"}]
            },
            {
                "player_id": 100020, 
                "name": "New York", 
                "display_position": "DEF", 
                "editorial_team_abbr": "NYJ",
                "status": "H",
                "eligible_positions": [{"position": "DEF"}]
            },
            {
                "player_id": 100019, 
                "name": "New York", 
                "display_position": "DEF", 
                "editorial_team_abbr": "NYG",
                "status": "H",
                "eligible_positions": [{"position": "DEF"}]
            },
        ]
        
        result = data_manager._process_players(players_raw, {})
        
        assert result.loc[result.player_id == 100014, "name"].iloc[0] == "Los Angeles Rams"
        assert result.loc[result.player_id == 100024, "name"].iloc[0] == "Los Angeles Chargers"
        assert result.loc[result.player_id == 100020, "name"].iloc[0] == "New York Jets"
        assert result.loc[result.player_id == 100019, "name"].iloc[0] == "New York Giants"
    
    def test_process_players_position_extraction(self, data_manager):
        """Test position extraction from display_position."""
        players_raw = [
            {
                "player_id": 1, 
                "name": "Player 1", 
                "display_position": "QB,RB", 
                "editorial_team_abbr": "BUF",
                "status": "H",
                "eligible_positions": [{"position": "QB"}, {"position": "RB"}]
            },
            {
                "player_id": 2, 
                "name": "Player 2", 
                "display_position": "WR,RB,TE", 
                "editorial_team_abbr": "SF",
                "status": "H",
                "eligible_positions": [{"position": "WR"}, {"position": "RB"}, {"position": "TE"}]
            },
            {
                "player_id": 3, 
                "name": "Player 3", 
                "display_position": "LB,S",  # Defensive positions not in our list
                "editorial_team_abbr": "KC",
                "status": "H",
                "eligible_positions": [{"position": "LB"}, {"position": "S"}]
            }
        ]
        
        result = data_manager._process_players(players_raw, {})
        
        assert result.loc[result.player_id == 1, "position"].iloc[0] == "QB"
        assert result.loc[result.player_id == 2, "position"].iloc[0] == "WR"
        assert result.loc[result.player_id == 3, "position"].iloc[0] == "UNKNOWN"
    
    def test_load_players_force_refresh(self, data_manager, mock_players_raw, mock_rosters):
        """Test that force_refresh bypasses cache."""
        # Setup cache with data
        cached_players = pd.DataFrame({"name": ["Cached Player"], "player_id": [999]})
        data_manager.cache.get_cached_data.return_value = cached_players
        
        # First call should return cached data
        players1 = data_manager.load_players("123.l.456789", 2024, 10, force_refresh=False)
        assert len(players1) == 1
        assert players1.iloc[0]["name"] == "Cached Player"
        
        # Force refresh should bypass cache
        data_manager.yahoo_client.get_all_players.return_value = mock_players_raw
        data_manager.yahoo_client.get_league_rosters.return_value = mock_rosters
        
        with patch.object(data_manager, '_add_external_player_data') as mock_external:
            mock_external.return_value = pd.DataFrame({
                "name": ["Fresh Player"],
                "player_id": [888]
            })
            
            players2 = data_manager.load_players("123.l.456789", 2024, 10, force_refresh=True)
            assert len(players2) == 1
            assert players2.iloc[0]["name"] == "Fresh Player"


class TestExternalDataIntegration:
    """Test integration with external data sources."""
    
    @pytest.fixture
    def data_manager(self):
        with patch('fantasyfb.data.data_manager.DataCache'):
            return DataManager(Mock())
    
    @pytest.fixture
    def sample_players(self):
        """Sample players DataFrame for testing external data addition."""
        return pd.DataFrame({
            "name": ["Josh Allen", "Christian McCaffrey", "Cooper Kupp"],
            "position": ["QB", "RB", "WR"],
            "player_id": [1, 2, 3],
            "editorial_team_abbr": ["BUF", "SF", "LAR"],
            "fantasy_team": ["Team A", "Team A", None]
        })
    
    @patch('pandas.read_csv')
    def test_apply_name_corrections(self, mock_read_csv, data_manager, sample_players):
        """Test name corrections between Yahoo and Pro Football Reference."""
        # Mock name corrections CSV
        mock_read_csv.return_value = pd.DataFrame({
            "name": ["Cooper Kupp"],
            "new_name": ["Cooper Kupp II"]  # Hypothetical correction
        })
        
        result = data_manager._apply_name_corrections(sample_players)
        
        # Should have applied the correction
        kupp_row = result.loc[result.player_id == 3]
        assert kupp_row.iloc[0]["name"] == "Cooper Kupp II"
        
        # Other names should be unchanged
        allen_row = result.loc[result.player_id == 1]
        assert allen_row.iloc[0]["name"] == "Josh Allen"
    
    def test_map_team_abbreviations(self, data_manager, sample_players):
        """Test mapping Yahoo team abbreviations to NFL standard."""
        # Mock NFL teams data
        nfl_teams = pd.DataFrame({
            "real_abbrev": ["BUF", "SF", "LAR"],
            "yahoo": ["BUF", "SF", "LAR"]
        })
        
        data_manager.load_nfl_teams = Mock(return_value=nfl_teams)
        
        result = data_manager._map_team_abbreviations(sample_players)
        
        assert "current_team" in result.columns
        assert result.loc[result.player_id == 1, "current_team"].iloc[0] == "BUF"
        assert result.loc[result.player_id == 2, "current_team"].iloc[0] == "SF"
    
    @patch('fantasyfb.data.data_manager.sr.get_bulk_rosters')
    @patch('fantasyfb.data.data_manager.sr.get_draft')
    def test_map_player_ids(self, mock_get_draft, mock_get_rosters, data_manager, sample_players):
        """Test mapping between Yahoo and SportsRef player IDs."""
        # Add current_team column (required for ID mapping)
        sample_players["current_team"] = ["BUF", "SF", "LAR"]
        
        # Mock NFL rosters data
        mock_get_rosters.return_value = pd.DataFrame({
            "player": ["Josh Allen", "Christian McCaffrey"],
            "player_id": ["AlleJo02", "McCaCh01"],
            "team": ["BUF", "SF"]
        })
        
        # Mock draft data
        mock_get_draft.return_value = pd.DataFrame({
            "player": ["Cooper Kupp"],
            "player_id": ["KuppCo00"],
            "team_abbrev": ["LAR"]
        })
        
        result = data_manager._map_player_ids(sample_players, 2024)
        
        # Should have mapped IDs for players found in rosters
        assert result.loc[result.name == "Josh Allen", "player_id_sr"].iloc[0] == "AlleJo02"
        assert result.loc[result.name == "Christian McCaffrey", "player_id_sr"].iloc[0] == "McCaCh01"
        
        # Should map from draft data for unmapped players
        assert result.loc[result.name == "Cooper Kupp", "player_id_sr"].iloc[0] == "KuppCo00"
    
    def test_add_bye_weeks(self, data_manager, sample_players):
        """Test adding bye week information."""
        # Add current_team column
        sample_players["current_team"] = ["BUF", "SF", "LAR"]
        
        # Mock NFL schedule
        nfl_schedule = pd.DataFrame({
            "season": [2024, 2024, 2024, 2024, 2024, 2024],
            "week": [1, 2, 1, 2, 1, 2],
            "team": ["BUF", "BUF", "SF", "SF", "LAR", "LAR"]
        })
        
        data_manager.load_nfl_schedule = Mock(return_value=nfl_schedule)
        
        result = data_manager._add_bye_weeks(sample_players, 2024)
        
        # Should have added bye_week column
        assert "bye_week" in result.columns
        # BUF plays weeks 1,2 so bye is week 3
        assert result.loc[result.current_team == "BUF", "bye_week"].iloc[0] == 3


class TestErrorHandling:
    """Test error handling in DataManager."""
    
    @pytest.fixture
    def data_manager(self):
        with patch('fantasyfb.data.data_manager.DataCache'):
            return DataManager(Mock())
    
    def test_load_players_api_failure(self, data_manager):
        """Test handling when Yahoo API fails."""
        data_manager.cache.get_cached_data.return_value = None
        data_manager.yahoo_client.get_all_players.side_effect = Exception("API Error")
        
        with pytest.raises(Exception, match="API Error"):
            data_manager.load_players("123.l.456789", 2024, 10)
    
    def test_missing_roster_players(self, data_manager, caplog):
        """Test warning when roster players are missing from main player list."""
        players_raw = [
            {
                "player_id": 1, 
                "name": "Player 1", 
                "display_position": "QB", 
                "editorial_team_abbr": "BUF",
                "status": "H",
                "eligible_positions": [{"position": "QB"}]
            }
        ]
        
        rosters = {
            "Team A": [
                {"player_id": 1, "name": "Player 1", "selected_position": "QB"},
                {"player_id": 999, "name": "Missing Player", "selected_position": "RB"}  # Not in main list
            ]
        }
        
        result = data_manager._process_players(players_raw, rosters)
        
        # Should log a warning about missing players
        assert "Some players missing from main list" in caplog.text
        assert "Missing Player" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
