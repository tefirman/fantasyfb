"""Manual smoke check: print real SleeperClient output for visual inspection.

Run directly:

    python scripts/inspect_sleeper_client.py [league_id]

Defaults to Scott Fish Bowl 16, the same public league the automated
smoke tests (tests/test_sleeper_client_smoke.py) target.
"""

from __future__ import annotations

import sys

import pandas as pd

from fantasyfb.data import sleeper_client

SFB16_LEAGUE_ID = "1367870433398915072"


def main() -> None:
    league_id = sys.argv[1] if len(sys.argv) > 1 else SFB16_LEAGUE_ID
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 160)

    print(f"--- League config ({league_id}) ---")
    config = sleeper_client.get_league_config(league_id)
    print("Scoring (sample):", dict(list(config["scoring"].items())[:5]))
    print(config["roster_spots"])

    client = sleeper_client.SleeperClient(league_id)

    week = client.get_current_week()
    print(f"\n--- Current week: {week} ---")

    teams = client.get_fantasy_teams()
    print(f"\n--- Teams ({len(teams)}) ---")
    for team in teams[:5]:
        print(team)
    if len(teams) > 5:
        print(f"... and {len(teams) - 5} more")

    print("\n--- Player pool ---")
    players = client.get_all_players()
    print(f"{players.shape[0]} players, columns: {list(players.columns)}")
    print(players.head())

    print("\n--- Rosters ---")
    rosters = client.get_team_rosters(teams, week)
    print(rosters.head(10))

    print("\n--- Schedule ---")
    schedule = client.get_schedule(teams, current_week=week, playoff_start_week=max(week + 1, 3))
    print(schedule.head(10))


if __name__ == "__main__":
    main()
