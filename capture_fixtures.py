#!/usr/bin/env python3
"""
Script to capture real Yahoo API responses for test fixtures.

This script makes real API calls to Yahoo Fantasy Sports API and saves
the raw JSON responses to files that can be used as realistic test fixtures.

Usage:
    python capture_fixtures.py

Prerequisites:
    - Valid Yahoo OAuth credentials in .env file
    - Active fantasy league for the current season
"""

import json
import os
from pathlib import Path
from fantasyfb.core.league import League


def create_fixtures_directory():
    """Create the fixtures directory if it doesn't exist."""
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    return fixtures_dir


def capture_league_settings(league: League, fixtures_dir: Path):
    """Capture league settings API response."""
    print("📥 Capturing league settings...")
    
    try:
        # Get the raw response from Yahoo API
        settings_response = league.yahoo_client.get_league_settings(league.lg_id)
        
        # Save to file
        output_file = fixtures_dir / "league_settings_real.json"
        with open(output_file, "w") as f:
            json.dump(settings_response, f, indent=2)
        
        print(f"✅ League settings saved to {output_file}")
        
        # Print some basic info about what we captured
        settings_content = settings_response["fantasy_content"]["league"][1]["settings"][0]
        print(f"   - Playoff start week: {settings_content['playoff_start_week']}")
        print(f"   - Number of playoff teams: {settings_content['num_playoff_teams']}")
        print(f"   - Stat categories: {len(settings_content['stat_categories']['stats'])}")
        print(f"   - Roster positions: {len(settings_content['roster_positions'])}")
        
    except Exception as e:
        print(f"❌ Failed to capture league settings: {e}")
        raise


def capture_user_leagues(league: League, fixtures_dir: Path):
    """Capture user leagues API response."""
    print("📥 Capturing user leagues...")
    
    try:
        # Get the raw response from Yahoo API
        leagues_response = league.yahoo_client.get_user_leagues()
        
        # Save to file
        output_file = fixtures_dir / "user_leagues_real.json"
        with open(output_file, "w") as f:
            json.dump(leagues_response, f, indent=2)
        
        print(f"✅ User leagues saved to {output_file}")
        print(f"   - Number of leagues: {leagues_response['count']}")
        
    except Exception as e:
        print(f"❌ Failed to capture user leagues: {e}")
        raise


def capture_league_standings(league: League, fixtures_dir: Path):
    """Capture league standings API response."""
    print("📥 Capturing league standings...")
    
    try:
        # Get the raw response from Yahoo API
        standings_response = league.yahoo_client.get_league_standings(league.lg_id)
        
        # Save to file
        output_file = fixtures_dir / "league_standings_real.json"
        with open(output_file, "w") as f:
            json.dump(standings_response, f, indent=2)
        
        print(f"✅ League standings saved to {output_file}")
        
        # Print some basic info
        teams_info = standings_response["fantasy_content"]["league"][1]["standings"][0]["teams"]
        print(f"   - Number of teams: {teams_info['count']}")
        
    except Exception as e:
        print(f"❌ Failed to capture league standings: {e}")
        raise


def capture_player_data(league: League, fixtures_dir: Path):
    """Capture all players API response."""
    print("📥 Capturing player data...")
    
    try:
        # Get the raw response from Yahoo API
        # This is the expensive call that gets all NFL players
        players_response = league.yahoo_client.get_all_players(league.lg_id)
        
        # Save to file
        output_file = fixtures_dir / "all_players_real.json"
        with open(output_file, "w") as f:
            json.dump(players_response, f, indent=2)
        
        print(f"✅ Player data saved to {output_file}")
        print(f"   - Total players: {len(players_response)}")
        
        # Show breakdown by position
        positions = {}
        for player in players_response:
            pos = player.get('display_position', 'Unknown').split(',')[0]
            positions[pos] = positions.get(pos, 0) + 1
        
        print("   - Position breakdown:")
        for pos, count in sorted(positions.items()):
            print(f"     {pos}: {count}")
        
    except Exception as e:
        print(f"❌ Failed to capture player data: {e}")
        raise


def capture_roster_data(league: League, fixtures_dir: Path):
    """Capture team rosters API response."""
    print("📥 Capturing roster data...")
    
    try:
        # Get rosters for current week
        rosters_response = league.yahoo_client.get_league_rosters(league.lg_id, league.week)
        
        # Save to file
        output_file = fixtures_dir / "team_rosters_real.json"
        with open(output_file, "w") as f:
            json.dump(rosters_response, f, indent=2)
        
        print(f"✅ Roster data saved to {output_file}")
        print(f"   - Teams with rosters: {len(rosters_response)}")
        
        # Show roster sizes
        for team_name, roster in rosters_response.items():
            print(f"     {team_name}: {len(roster)} players")
        
    except Exception as e:
        print(f"❌ Failed to capture roster data: {e}")
        raise


def capture_schedule_data(league: League, fixtures_dir: Path):
    """Capture fantasy league schedule."""
    print("📥 Capturing schedule data...")
    
    try:
        # Get schedule data
        schedule_response = league.yahoo_client.get_league_schedule(
            league.lg_id, 
            league.teams, 
            league.season, 
            league.week
        )
        
        # Convert DataFrame to dict for JSON serialization
        if hasattr(schedule_response, 'to_dict'):
            schedule_dict = schedule_response.to_dict('records')
        else:
            schedule_dict = schedule_response
        
        # Save to file
        output_file = fixtures_dir / "league_schedule_real.json"
        with open(output_file, "w") as f:
            json.dump(schedule_dict, f, indent=2)
        
        print(f"✅ Schedule data saved to {output_file}")
        print(f"   - Total matchups: {len(schedule_dict)}")
        
        # Show weeks covered
        weeks = set()
        for matchup in schedule_dict:
            if 'week' in matchup:
                weeks.add(matchup['week'])
        print(f"   - Weeks covered: {sorted(weeks)}")
        
    except Exception as e:
        print(f"❌ Failed to capture schedule data: {e}")
        raise


def main():
    """Main function to capture API responses."""
    print("🚀 Starting API response capture for test fixtures...")
    print("=" * 60)
    
    # Create fixtures directory
    fixtures_dir = create_fixtures_directory()
    print(f"📁 Fixtures will be saved to: {fixtures_dir.absolute()}")
    
    try:
        # Initialize league (this will make real API calls)
        print("\n🔧 Initializing league connection...")
        league = League(team_name="The Algorithm", season=2024, week=10)
        print(f"✅ Connected to league: {league.lg_id}")
        print(f"   - Team name: {league.team_name}")
        print(f"   - Season: {league.season}")
        print(f"   - Current week: {league.week}")
        
        # Capture different API responses
        print("\n📡 Capturing API responses...")
        capture_user_leagues(league, fixtures_dir)
        capture_league_settings(league, fixtures_dir)
        capture_league_standings(league, fixtures_dir)
        capture_player_data(league, fixtures_dir)
        capture_roster_data(league, fixtures_dir)
        capture_schedule_data(league, fixtures_dir)
        
        print("\n🎉 All API responses captured successfully!")
        print("\nNext steps:")
        print("1. Review the captured JSON files in tests/fixtures/")
        print("2. Update your test fixtures to use these real structures")
        print("3. Run tests to ensure they work with realistic data")
        
    except Exception as e:
        print(f"\n💥 Capture failed: {e}")
        print("\nTroubleshooting tips:")
        print("- Make sure your .env file has valid Yahoo OAuth credentials")
        print("- Ensure you have an active fantasy league for 2024")
        print("- Check that 'The Algorithm' is the correct team name")
        print("- Try running the manual_test.py script first to verify setup")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
