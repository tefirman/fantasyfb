# tests/fixtures.py
"""
Helper module for loading real API response fixtures in tests.

This module provides utilities to load captured real Yahoo API responses
for use in test mocks, ensuring tests use realistic data structures.
"""

import json
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock


def load_real_fixture(name: str) -> Dict[str, Any]:
    """
    Load a real API response fixture from the fixtures directory.
    
    Args:
        name: Name of the fixture file (without _real.json suffix)
        
    Returns:
        Dictionary containing the real API response
        
    Raises:
        FileNotFoundError: If the fixture file doesn't exist
        json.JSONDecodeError: If the fixture file contains invalid JSON
    """
    fixture_path = Path(__file__).parent / "fixtures" / f"{name}_real.json"
    
    if not fixture_path.exists():
        available_fixtures = list((Path(__file__).parent / "fixtures").glob("*_real.json"))
        available_names = [f.stem.replace("_real", "") for f in available_fixtures]
        raise FileNotFoundError(
            f"Fixture '{name}' not found. Available fixtures: {available_names}\n"
            f"Run 'python capture_fixtures.py' to generate fixtures."
        )
    
    with open(fixture_path) as f:
        return json.load(f)


def get_mock_yahoo_client_with_real_responses() -> Mock:
    """
    Create a mock YahooClient that returns real API responses.
    
    This is useful for integration-style tests that want to use realistic
    data without making actual API calls.
    
    Returns:
        Mock YahooClient configured with real response data
    """
    mock_client = Mock()
    
    # Load real responses
    try:
        user_leagues = load_real_fixture("user_leagues")
        league_settings = load_real_fixture("league_settings") 
        league_standings = load_real_fixture("league_standings")
        all_players = load_real_fixture("all_players")
        team_rosters = load_real_fixture("team_rosters")
        league_schedule = load_real_fixture("league_schedule")
        
        # Configure mock methods
        mock_client.get_user_leagues.return_value = user_leagues
        mock_client.get_league_settings.return_value = league_settings
        mock_client.get_league_standings.return_value = league_standings
        mock_client.get_all_players.return_value = all_players
        mock_client.get_league_rosters.return_value = team_rosters
        mock_client.get_league_schedule.return_value = league_schedule
        
        # Add other commonly mocked methods with sensible defaults
        mock_client.get_current_week.return_value = 10
        
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Cannot create mock with real responses: {e}\n"
            "Run 'python capture_fixtures.py' first to generate fixture data."
        ) from e
    
    return mock_client


def extract_sample_data_from_fixtures() -> Dict[str, Any]:
    """
    Extract useful sample data from real fixtures for test assertions.
    
    This analyzes the real fixture data and extracts commonly needed
    values for use in test assertions.
    
    Returns:
        Dictionary with sample data extracted from real fixtures
    """
    samples = {}
    
    try:
        # Extract from league settings
        settings = load_real_fixture("league_settings")
        settings_content = settings["fantasy_content"]["league"][1]["settings"][0]
        
        samples["playoff_start_week"] = int(settings_content["playoff_start_week"])
        samples["num_playoff_teams"] = int(settings_content["num_playoff_teams"])
        
        # Extract scoring categories
        stat_categories = settings_content["stat_categories"]["stats"]
        stat_modifiers = settings_content["stat_modifiers"]["stats"]
        
        samples["num_stat_categories"] = len(stat_categories)
        samples["num_stat_modifiers"] = len(stat_modifiers)
        
        # Extract roster positions
        roster_positions = settings_content["roster_positions"]
        samples["num_roster_positions"] = len(roster_positions)
        samples["roster_positions"] = [pos["roster_position"]["position"] for pos in roster_positions]
        
        # Extract from standings
        standings = load_real_fixture("league_standings")
        teams_info = standings["fantasy_content"]["league"][1]["standings"][0]["teams"]
        samples["num_teams"] = teams_info["count"]
        
        # Extract team names
        team_names = []
        for i in range(teams_info["count"]):
            team_data = teams_info[str(i)]["team"][0]
            team_names.append(team_data[2]["name"])  # Name is usually at index 2
        samples["team_names"] = team_names
        
    except (FileNotFoundError, KeyError, IndexError) as e:
        print(f"Warning: Could not extract all sample data: {e}")
    
    return samples


def validate_fixture_structure(fixture_name: str) -> bool:
    """
    Validate that a fixture has the expected Yahoo API structure.
    
    Args:
        fixture_name: Name of the fixture to validate
        
    Returns:
        True if structure is valid, False otherwise
    """
    try:
        fixture = load_real_fixture(fixture_name)
        
        # All Yahoo API responses should have this top-level structure
        if "fantasy_content" not in fixture:
            print(f"❌ {fixture_name}: Missing 'fantasy_content' key")
            return False
        
        if "league" not in fixture["fantasy_content"]:
            print(f"❌ {fixture_name}: Missing 'fantasy_content.league' key") 
            return False
        
        league_data = fixture["fantasy_content"]["league"]
        if not isinstance(league_data, list) or len(league_data) < 2:
            print(f"❌ {fixture_name}: 'league' should be a list with at least 2 elements")
            return False
        
        print(f"✅ {fixture_name}: Structure looks valid")
        return True
        
    except Exception as e:
        print(f"❌ {fixture_name}: Validation failed - {e}")
        return False


if __name__ == "__main__":
    """Quick validation of all available fixtures."""
    print("🔍 Validating fixture structures...")
    
    fixtures_dir = Path(__file__).parent / "fixtures"
    if not fixtures_dir.exists():
        print("❌ No fixtures directory found. Run 'python capture_fixtures.py' first.")
        exit(1)
    
    fixture_files = list(fixtures_dir.glob("*_real.json"))
    if not fixture_files:
        print("❌ No fixture files found. Run 'python capture_fixtures.py' first.")
        exit(1)
    
    all_valid = True
    for fixture_file in fixture_files:
        fixture_name = fixture_file.stem.replace("_real", "")
        if not validate_fixture_structure(fixture_name):
            all_valid = False
    
    if all_valid:
        print("\n🎉 All fixtures have valid structures!")
        
        # Show sample data
        print("\n📊 Sample data extracted from fixtures:")
        samples = extract_sample_data_from_fixtures()
        for key, value in samples.items():
            print(f"   {key}: {value}")
    else:
        print("\n💥 Some fixtures have invalid structures.")
        exit(1)
