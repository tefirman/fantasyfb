"""Smoke tests for SleeperClient against the live, public Sleeper API.

Unlike test_sleeper_client.py (unit tests against mocked HTTP responses),
everything here makes real network calls -- run this file directly to
confirm the client actually talks to Sleeper end-to-end:

    pytest tests/test_sleeper_client_smoke.py -v

They target Scott Fish Bowl 16 (sleeper.com/leagues/1367870433398915072),
a stable, known-good public league ID to sanity check against instead of
requiring a throwaway test league.

Assertions here are intentionally loose (shapes/types, not exact values):
league state (current week, rosters, scores) changes over the season, and
these tests should stay green whenever they're run, not just today.

These self-skip (rather than fail) if Sleeper is unreachable, since some
sandboxed/offline dev environments block arbitrary outbound hosts. That
also means a green run here isn't proof of connectivity by itself -- if
every test in this file is reported "skipped", Sleeper wasn't reachable
and nothing was actually verified.
"""

from __future__ import annotations

import pytest
import requests

from fantasyfb.data import sleeper_client

SFB16_LEAGUE_ID = "1367870433398915072"


@pytest.fixture(scope="module")
def client() -> sleeper_client.SleeperClient:
    try:
        sleeper_client.fetch_nfl_state()
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"Sleeper API unreachable from this environment: {exc}")
    return sleeper_client.SleeperClient(SFB16_LEAGUE_ID)


@pytest.fixture(scope="module")
def teams(client: sleeper_client.SleeperClient) -> list:
    teams = client.get_fantasy_teams()
    assert teams, "SFB16 returned no teams -- league ID may be stale/wrong"
    return teams


pytestmark = pytest.mark.smoke


class TestGetLeagueConfigLive:
    def test_pulls_real_scoring_and_roster_settings(self, client):
        config = sleeper_client.get_league_config(SFB16_LEAGUE_ID)
        assert config["scoring"]["Pass TD"] > 0
        assert config["roster_spots"]["count"].sum() > 0


class TestGetCurrentWeekLive:
    def test_returns_a_plausible_week_number(self, client):
        week = client.get_current_week()
        assert isinstance(week, int)
        assert 0 <= week <= 22


class TestGetFantasyTeamsLive:
    def test_returns_all_teams_with_expected_shape(self, teams):
        for team in teams:
            assert set(team.keys()) == {"team_key", "name", "manager"}
            assert team["team_key"]
            assert team["name"]

    def test_team_keys_are_unique(self, teams):
        keys = [team["team_key"] for team in teams]
        assert len(keys) == len(set(keys))


class TestGetAllPlayersLive:
    def test_returns_a_full_player_pool(self, client):
        players = client.get_all_players()
        assert players.shape[0] > 500
        assert set(players["position"].unique()) <= {"QB", "RB", "WR", "TE", "K", "DEF"}
        assert (players["position"] == "QB").any()
        assert (players["position"] == "DEF").any()

    def test_gsis_bridge_resolves_for_some_players(self, client):
        # player_id_sr comes straight from Sleeper's gsis_id -- confirms
        # the field that lets a future NflreadpyProvider join work at all.
        players = client.get_all_players()
        assert players["player_id_sr"].notna().any()


class TestGetTeamRostersLive:
    def test_returns_well_formed_rosters(self, client, teams):
        week = client.get_current_week()
        rosters = client.get_team_rosters(teams, week)
        assert list(rosters.columns) == ["player_id", "selected_position", "fantasy_team"]
        if not rosters.empty:
            team_names = {team["name"] for team in teams}
            assert set(rosters["fantasy_team"].unique()) <= team_names


class TestGetScheduleLive:
    def test_returns_well_formed_schedule(self, client, teams):
        week = client.get_current_week()
        schedule = client.get_schedule(
            teams, current_week=week, playoff_start_week=max(week + 1, 3)
        )
        assert list(schedule.columns) == ["week", "team_1", "team_2", "score_1", "score_2"]
        if not schedule.empty:
            assert schedule["score_1"].dtype == float
            assert schedule["score_2"].dtype == float
            team_names = {team["name"] for team in teams}
            assert set(schedule["team_1"]) <= team_names
            assert set(schedule["team_2"]) <= team_names
