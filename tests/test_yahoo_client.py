"""Live Yahoo Fantasy API smoke tests.

Skipped by default. Set RUN_YAHOO_TESTS=1 to opt in. Requires a valid
oauth2.json (and .env with CONSUMER_KEY/CONSUMER_SECRET) at the repo
root, plus a real league for the season under test.

Override the season via YAHOO_TEST_SEASON (defaults to the current NFL
season heuristic used by fantasyfb.py). Override the team name via
YAHOO_TEST_TEAM if the account has multiple teams in that league.
"""

from __future__ import annotations

import datetime
import os

import pandas as pd
import pytest

from yahoo_client import YahooFantasyClient


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_YAHOO_TESTS") != "1",
    reason="Set RUN_YAHOO_TESTS=1 to run live Yahoo API tests.",
)


def _default_season() -> int:
    now = datetime.datetime.now()
    return now.year - int(now.month < 6)


@pytest.fixture(scope="module")
def season() -> int:
    return int(os.environ.get("YAHOO_TEST_SEASON", _default_season()))


@pytest.fixture(scope="module")
def team_name() -> str | None:
    return os.environ.get("YAHOO_TEST_TEAM")


@pytest.fixture(scope="module")
def client(season: int, team_name: str | None) -> YahooFantasyClient:
    c = YahooFantasyClient()
    c.refresh_oauth()
    name, lg_id = c.connect_to_league(season, team_name)
    assert name, "connect_to_league returned an empty team name"
    assert lg_id, "connect_to_league returned an empty league id"
    return c


class TestConnection:
    def test_league_object_initialized(self, client: YahooFantasyClient) -> None:
        assert client.lg is not None
        assert client.lg_id is not None
        assert client.lg.current_week() >= 1


class TestSettings:
    def test_settings_shape(self, client: YahooFantasyClient) -> None:
        settings, roster_spots, scoring = client.get_league_settings()
        assert isinstance(settings, dict)
        assert settings["playoff_start_week"] >= 1
        assert settings["num_playoff_teams"] >= 1
        assert isinstance(roster_spots, pd.DataFrame)
        assert {"position", "count"}.issubset(roster_spots.columns)
        assert roster_spots["count"].sum() > 0
        assert isinstance(scoring, dict)
        assert len(scoring) > 0


class TestTeamsAndRosters:
    @pytest.fixture(scope="class")
    def teams(self, client: YahooFantasyClient) -> list[dict]:
        return client.get_fantasy_teams()

    def test_teams_returned(self, teams: list[dict]) -> None:
        assert len(teams) > 0
        required = {"team_key", "name", "manager"}
        for team in teams:
            assert required.issubset(team.keys())

    def test_rosters_for_week_one(
        self, client: YahooFantasyClient, teams: list[dict]
    ) -> None:
        # One team is enough to confirm the roster endpoint still parses.
        rosters = client.get_team_rosters(teams[:1], week=1)
        assert {"player_id", "selected_position", "fantasy_team"}.issubset(
            rosters.columns
        )
        assert len(rosters) > 0
