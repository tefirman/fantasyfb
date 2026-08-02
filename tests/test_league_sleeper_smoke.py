"""Smoke test for a Sleeper-backed League against the live, public Sleeper API.

Run directly:

    pytest tests/test_league_sleeper_smoke.py -v -m smoke

This is the end-to-end proof that League(platform="sleeper", ...) works --
teams, rosters, schedule, scoring, and the full player-data pipeline (name
mapping, injuries, bye weeks, depth charts) all wired through SleeperClient
instead of YahooFantasyClient. See tests/test_sleeper_client_smoke.py for
the equivalent client-level smoke tests this builds on.

Targets Scott Fish Bowl 16 (sleeper.com/leagues/1367870433398915072), the
same public league test_sleeper_client_smoke.py uses -- a stable, known-good
league ID that needs no throwaway test league or Sleeper account.

Assertions are intentionally loose (shapes/types, not exact values): league
state changes over the season, and this should stay green whenever it's
run, not just today. Self-skips (rather than fails) if Sleeper is
unreachable -- if this test is reported "skipped", nothing was verified.

fit_matchup=False skips the ~5-10s walk-forward matchup-weight refit (see
League.refit_matchup_weights's docstring) since this test only needs to
confirm construction succeeds, not that the fitted weights are optimal.
"""

from __future__ import annotations

import pytest
import requests

from fantasyfb.data import sleeper_client
from fantasyfb.league import League

SFB16_LEAGUE_ID = "1367870433398915072"

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def league() -> League:
    try:
        sleeper_client.fetch_nfl_state()
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"Sleeper API unreachable from this environment: {exc}")
    return League(
        platform="sleeper",
        sleeper_league_id=SFB16_LEAGUE_ID,
        fit_matchup=False,
    )


class TestSleeperBackedLeagueConstructs:
    def test_teams_are_populated(self, league: League):
        assert league.teams
        assert all({"team_key", "name", "manager"} <= set(t.keys()) for t in league.teams)

    def test_schedule_has_expected_shape(self, league: League):
        assert list(league.schedule.columns) == [
            "week", "team_1", "team_2", "score_1", "score_2",
        ]

    def test_players_are_populated_with_expected_columns(self, league: League):
        assert league.players.shape[0] > 500
        assert {"player_id_sr", "position", "current_team", "pct_rostered"} <= set(
            league.players.columns
        )
        assert set(league.players["position"].dropna().unique()) <= {
            "QB", "RB", "WR", "TE", "K", "DEF",
        }

    def test_settings_are_sane(self, league: League):
        assert league.settings["playoff_start_week"] >= 1
        assert league.settings["num_playoff_teams"] >= 2
        assert league.settings["end_week"] >= league.settings["playoff_start_week"]

    def test_no_ownership_percentage_leaves_pct_rostered_at_zero(self, league: League):
        # Sleeper has no roster-percentage concept -- confirms the
        # PlayerDataManager None-branch actually engaged, not just that
        # the column happens to exist. Excludes the synthetic Average_*
        # league-baseline rows get_rates() adds, which never go through
        # add_roster_percentages and so are NaN rather than 0.0.
        real_players = league.players[~league.players["player_id_sr"].str.startswith("avg_")]
        assert (real_players["pct_rostered"] == 0.0).all()
