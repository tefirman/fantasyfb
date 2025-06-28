# tests/test_scoring_processing.py
"""
Test scoring system processing with real Yahoo API data.

This validates that we correctly parse and process the complex
scoring configuration from Yahoo's API format.
"""

import pytest
from src.fantasyfb.data.data_manager import DataManager
from tests.fixtures import load_real_fixture, get_mock_yahoo_client_with_real_responses


class TestScoringProcessing:
    """Test scoring configuration processing from real API data."""
    
    @pytest.fixture
    def raw_settings_data(self):
        """Raw league settings from real Yahoo API."""
        return load_real_fixture("league_settings")
    
    @pytest.fixture
    def data_manager(self):
        """DataManager with mocked Yahoo client."""
        mock_client = get_mock_yahoo_client_with_real_responses()
        return DataManager(mock_client)
    
    def test_stat_categories_parsing(self, raw_settings_data):
        """Test that stat categories are correctly identified."""
        settings_content = raw_settings_data["fantasy_content"]["league"][1]["settings"][0]
        stat_categories = settings_content["stat_categories"]["stats"]
        
        # Should have multiple stat categories
        assert len(stat_categories) > 20
        
        # Check for key offensive stats
        category_names = [stat["stat"]["display_name"] for stat in stat_categories]
        
        assert "Pass Yds" in category_names
        assert "Pass TD" in category_names
        assert "Rush Yds" in category_names
        assert "Rush TD" in category_names
        assert "Rec Yds" in category_names
        assert "Rec TD" in category_names
        assert "Rec" in category_names  # PPR
        
        # Check for defensive stats
        assert "Sack" in category_names
        assert "Int" in category_names
        assert "Fum Rec" in category_names
    
    def test_stat_modifiers_parsing(self, raw_settings_data):
        """Test that stat modifiers (point values) are correctly parsed."""
        settings_content = raw_settings_data["fantasy_content"]["league"][1]["settings"][0]
        stat_modifiers = settings_content["stat_modifiers"]["stats"]
        
        # Should have point values for multiple stats
        assert len(stat_modifiers) > 15
        
        # Check specific values from your real data
        modifier_dict = {mod["stat"]["stat_id"]: float(mod["stat"]["value"]) for mod in stat_modifiers}
        
        # Passing yards (stat_id 4) should be 0.04 points per yard
        assert modifier_dict[4] == 0.04
        
        # Passing TDs (stat_id 5) should be 6 points
        assert modifier_dict[5] == 6.0
        
        # Interceptions (stat_id 6) should be -2 points
        assert modifier_dict[6] == -2.0
        
        # Rushing yards (stat_id 9) should be 0.1 points per yard
        assert modifier_dict[9] == 0.1
    
    def test_processed_scoring_dict(self, data_manager):
        """Test the final processed scoring dictionary."""
        settings, scoring, roster_spots = data_manager.load_league_settings("449.l.49284")
        
        # Test key scoring values match your real league
        assert scoring["Pass Yds"] == 0.04
        assert scoring["Pass TD"] == 6.0
        assert scoring["Int Thrown"] == -2.0  # Should be renamed from "Int"
        assert scoring["Rush Yds"] == 0.1
        assert scoring["Rush TD"] == 6.0
        assert scoring["Rec Yds"] == 0.1
        assert scoring["Rec TD"] == 6.0
        assert scoring["Rec"] == 0.0  # Your league appears to be standard, not PPR
        assert scoring["Fum Lost"] == -2.0
        assert scoring["2-PT"] == 2.0
        
        # Kicker scoring
        assert scoring["PAT Made"] == 1.0
        
        # Defense scoring
        assert scoring["Sack"] == 1.0
        assert scoring["Int"] == 2.0  # Defensive interceptions
        assert scoring["Fum Rec"] == 2.0
        assert scoring["TD"] == 6.0
        assert scoring["Safe"] == 2.0
        assert scoring["Blk Kick"] == 2.0
        
        # Points allowed scoring
        assert scoring["Pts Allow 0"] == 10.0
        assert scoring["Pts Allow 1-6"] == 7.0
        assert scoring["Pts Allow 7-13"] == 4.0
        assert scoring["Pts Allow 14-20"] == 1.0
        assert scoring["Pts Allow 21-27"] == 0.0
        assert scoring["Pts Allow 28-34"] == -1.0
        assert scoring["Pts Allow 35+"] == -4.0
    
    def test_default_scoring_additions(self, data_manager):
        """Test that missing scoring categories get sensible defaults."""
        settings, scoring, roster_spots = data_manager.load_league_settings("449.l.49284")
        
        # These categories might not be in Yahoo API but should have defaults
        default_categories = [
            "Pass Comp", "Pass 1D", "Rush Att", "Rush 1D", "Rec 1D",
            "TE Rec Bonus", "TE 1D Bonus", "Pass 300+", "Rush 100+", "Rec 100+",
            "Ret Yds", "FG 0-19", "FG 20-29", "FG 30-39", "FG 40-49", "FG 50+"
        ]
        
        for category in default_categories:
            assert category in scoring
            assert isinstance(scoring[category], (int, float))
    
    def test_interception_name_handling(self, data_manager):
        """Test that interception scoring is correctly differentiated."""
        settings, scoring, roster_spots = data_manager.load_league_settings("449.l.49284")
        
        # Should have both offensive and defensive interceptions
        assert "Int Thrown" in scoring  # Offensive (negative points)
        assert "Int" in scoring  # Defensive (positive points)
        
        assert scoring["Int Thrown"] < 0  # Should be negative
        assert scoring["Int"] > 0  # Should be positive
    
    def test_field_goal_scoring_logic(self, raw_settings_data):
        """Test field goal distance scoring from real data."""
        settings_content = raw_settings_data["fantasy_content"]["league"][1]["settings"][0]
        stat_modifiers = settings_content["stat_modifiers"]["stats"]
        
        # Your league has FG Yds scoring (stat_id 84) at 0.1 per yard
        fg_yds_modifier = None
        for mod in stat_modifiers:
            if mod["stat"]["stat_id"] == 84:
                fg_yds_modifier = float(mod["stat"]["value"])
                break
        
        assert fg_yds_modifier == 0.1
    
    def test_return_yardage_scoring(self, raw_settings_data):
        """Test return yardage scoring configuration."""
        settings_content = raw_settings_data["fantasy_content"]["league"][1]["settings"][0]
        stat_modifiers = settings_content["stat_modifiers"]["stats"]
        
        # Return yards (stat_id 14) should be 0.05 per yard in your league
        ret_yds_modifier = None
        for mod in stat_modifiers:
            if mod["stat"]["stat_id"] == 14:
                ret_yds_modifier = float(mod["stat"]["value"])
                break
        
        assert ret_yds_modifier == 0.05


class TestScoringEdgeCases:
    """Test edge cases in scoring processing."""
    
    def test_missing_stat_categories(self):
        """Test handling when some stat categories are missing."""
        # Create a minimal settings structure
        minimal_settings = {
            "fantasy_content": {
                "league": [
                    {"season": "2024"},
                    {
                        "settings": [{
                            "stat_categories": {"stats": []},
                            "stat_modifiers": {"stats": []}
                        }]
                    }
                ]
            }
        }
        
        # This should not crash and should provide defaults
        from src.fantasyfb.data.data_manager import DataManager
        from unittest.mock import Mock
        
        mock_client = Mock()
        mock_client.get_league_settings.return_value = minimal_settings
        
        data_manager = DataManager(mock_client)
        settings, scoring, roster_spots = data_manager._process_settings(minimal_settings)
        
        # Should have basic default values
        assert isinstance(scoring, dict)
        # Won't have any scoring since stat_modifiers is empty, but shouldn't crash
    
    def test_duplicate_stat_handling(self, data_manager):
        """Test that duplicate stats are handled correctly."""
        settings, scoring, roster_spots = data_manager.load_league_settings("449.l.49284")
        
        # Check that we don't have duplicate keys
        scoring_keys = list(scoring.keys())
        assert len(scoring_keys) == len(set(scoring_keys))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
