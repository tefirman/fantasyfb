"""get_fantasy_teams must tolerate Yahoo reshuffling the empty-list padding in team info."""
from types import SimpleNamespace

import pytest

from fantasyfb.data.yahoo_client import YahooFantasyClient


def _client_with_standings(team_info: list) -> YahooFantasyClient:
    standings = {
        "fantasy_content": {
            "league": [
                {},
                {"standings": [{"teams": {"0": {"team": [team_info, {}]}, "count": 1}}]},
            ]
        }
    }
    client = object.__new__(YahooFantasyClient)
    client.lg_id = "470.l.1"
    client.lg = SimpleNamespace(
        yhandler=SimpleNamespace(get_standings_raw=lambda lg_id: standings)
    )
    return client


MANAGERS = {"managers": [{"manager": {"nickname": "Taylor"}}]}


@pytest.mark.parametrize(
    "team_info",
    [
        # Older shape: managers is the last element.
        [{"team_key": "470.l.1.t.1"}, {"team_id": "1"}, {"name": "A"}, [], MANAGERS],
        # Current shape: Yahoo appends a trailing empty list after managers.
        [{"team_key": "470.l.1.t.1"}, {"team_id": "1"}, {"name": "A"}, [], MANAGERS, []],
    ],
)
def test_get_fantasy_teams_handles_padding(team_info: list) -> None:
    teams = _client_with_standings(team_info).get_fantasy_teams()
    assert teams == [{"team_key": "470.l.1.t.1", "name": "A", "manager": "Taylor"}]
