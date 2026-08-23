"""Tests for GenericClient, the fully synthetic (no Yahoo/Sleeper) mock-draft
backend (see issue #47).

get_current_week() is the only thing that touches the network (Sleeper's
public /state/nfl endpoint); it's mocked out here same as SleeperClient's
tests. Everything else is pure synthesis, so a small fake NflreadpyProvider
stands in for the player-pool source.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import requests

from fantasyfb.data.generic_client import GenericClient, _round_robin_pairings


class FakeNflProvider:
    """Minimal stand-in for NflreadpyProvider.get_rosters/team_aliases."""

    def __init__(self, rosters: pd.DataFrame):
        self._rosters = rosters

    def get_rosters(self, start_year, end_year):
        return self._rosters[
            (self._rosters["season"] >= start_year) & (self._rosters["season"] <= end_year)
        ].reset_index(drop=True)

    def team_aliases(self):
        return pd.DataFrame({
            "yahoo": ["KC", "SF", "Buf"],
            "real_abbrev": ["KC", "SF", "BUF"],
        })


ROSTERS = pd.DataFrame([
    {"name": "Patrick Mahomes", "current_team": "KC", "position": "QB",
     "player_id_sr": "00-001", "yahoo_id": "1", "season": 2025},
    {"name": "Christian McCaffrey", "current_team": "SF", "position": "RB",
     "player_id_sr": "00-002", "yahoo_id": "2", "season": 2025},
    {"name": "Some Longsnapper", "current_team": "BUF", "position": "LS",
     "player_id_sr": "00-003", "yahoo_id": "3", "season": 2025},
    # Same player shows up in both seasons -- newer season row should win.
    {"name": "Patrick Mahomes", "current_team": "KC", "position": "QB",
     "player_id_sr": "00-001", "yahoo_id": "1", "season": 2026},
])


class TestRoundRobinPairings:
    def test_even_teams_every_pair_once_per_cycle(self):
        rounds = _round_robin_pairings(["A", "B", "C", "D"])
        assert len(rounds) == 3
        all_pairs = {frozenset(p) for r in rounds for p in r}
        assert len(all_pairs) == 6  # C(4,2)

    def test_no_team_plays_itself(self):
        rounds = _round_robin_pairings(["A", "B", "C", "D", "E"])
        for round_pairs in rounds:
            for t1, t2 in round_pairs:
                assert t1 != t2

    def test_odd_teams_get_a_bye_each_round(self):
        rounds = _round_robin_pairings(["A", "B", "C"])
        for round_pairs in rounds:
            assert len(round_pairs) == 1  # one pair, one team on bye

    def test_single_team_has_no_pairings(self):
        rounds = _round_robin_pairings(["A"])
        assert all(not pairs for pairs in rounds)


class TestGetFantasyTeams:
    def test_synthesizes_default_names(self):
        client = GenericClient(num_teams=4)
        teams = client.get_fantasy_teams()
        assert [t["name"] for t in teams] == ["Team 1", "Team 2", "Team 3", "Team 4"]
        assert all(t["team_key"] for t in teams)

    def test_my_team_name_replaces_first_slot(self):
        client = GenericClient(num_teams=3, my_team_name="Dynasty Warriors")
        teams = client.get_fantasy_teams()
        assert teams[0]["name"] == "Dynasty Warriors"
        assert teams[0]["manager"] == "Dynasty Warriors"
        assert [t["name"] for t in teams[1:]] == ["Team 2", "Team 3"]


class TestGetMyTeamKey:
    def test_resolves_when_name_set(self):
        client = GenericClient(num_teams=4, my_team_name="Me")
        assert client.get_my_team_key() == "1"

    def test_none_when_name_not_set(self):
        client = GenericClient(num_teams=4)
        assert client.get_my_team_key() is None


class TestGetLeagueConfig:
    def test_defaults_to_ppr(self):
        client = GenericClient()
        config = client.get_league_config()
        assert config["scoring"]["Rec"] == 1.0

    def test_standard_has_no_reception_points(self):
        client = GenericClient(scoring="standard")
        config = client.get_league_config()
        assert config["scoring"]["Rec"] == 0.0

    def test_half_ppr(self):
        client = GenericClient(scoring="half_ppr")
        config = client.get_league_config()
        assert config["scoring"]["Rec"] == 0.5

    def test_roster_spots_match_fixed_shape(self):
        client = GenericClient()
        config = client.get_league_config()
        counts = config["roster_spots"].set_index("position")["count"].to_dict()
        assert counts == {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1,
            "W/R/T": 1, "K": 1, "DEF": 1, "BN": 7,
        }

    def test_settings_populated(self):
        client = GenericClient()
        config = client.get_league_config()
        assert config["settings"]["playoff_start_week"] >= 1
        assert config["settings"]["num_playoff_teams"] in (4, 6)
        assert config["settings"]["end_week"] >= config["settings"]["playoff_start_week"]

    def test_custom_roster_spots_override_default_shape(self):
        custom = pd.DataFrame({
            "position": ["QB", "RB", "WR", "W/R/T", "Q/W/R/T", "BN"],
            "count": [1, 2, 2, 2, 1, 6],
        })
        client = GenericClient(roster_spots=custom)
        config = client.get_league_config()
        counts = config["roster_spots"].set_index("position")["count"].to_dict()
        assert counts == {"QB": 1, "RB": 2, "WR": 2, "W/R/T": 2, "Q/W/R/T": 1, "BN": 6}

    def test_custom_roster_spots_does_not_affect_scoring(self):
        custom = pd.DataFrame({"position": ["QB"], "count": [1]})
        client = GenericClient(scoring="half_ppr", roster_spots=custom)
        config = client.get_league_config()
        assert config["scoring"]["Rec"] == 0.5

    def test_unknown_position_code_raises(self):
        bad = pd.DataFrame({"position": ["QB", "ZZ"], "count": [1, 1]})
        try:
            GenericClient(roster_spots=bad)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "ZZ" in str(exc)

    def test_none_falls_back_to_fixed_default(self):
        client = GenericClient(roster_spots=None)
        config = client.get_league_config()
        counts = config["roster_spots"].set_index("position")["count"].to_dict()
        assert counts == {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1,
            "W/R/T": 1, "K": 1, "DEF": 1, "BN": 7,
        }


class TestGetTeamRosters:
    def test_always_empty(self):
        client = GenericClient(num_teams=4)
        rosters = client.get_team_rosters(client.get_fantasy_teams(), week=1)
        assert rosters.empty
        assert list(rosters.columns) == ["player_id", "selected_position", "fantasy_team"]


class TestGetSchedule:
    def test_only_covers_regular_season(self):
        client = GenericClient(num_teams=4)
        teams = client.get_fantasy_teams()
        schedule = client.get_schedule(teams, current_week=1, playoff_start_week=15)
        assert schedule["week"].max() == 14
        assert schedule["week"].min() == 1

    def test_no_self_matchups(self):
        client = GenericClient(num_teams=6)
        teams = client.get_fantasy_teams()
        schedule = client.get_schedule(teams, current_week=1, playoff_start_week=15)
        assert (schedule["team_1"] != schedule["team_2"]).all()

    def test_scores_start_at_zero(self):
        client = GenericClient(num_teams=4)
        teams = client.get_fantasy_teams()
        schedule = client.get_schedule(teams, current_week=1, playoff_start_week=15)
        assert (schedule["score_1"] == 0.0).all()
        assert (schedule["score_2"] == 0.0).all()

    def test_columns_match_platform_client_contract(self):
        client = GenericClient(num_teams=4)
        teams = client.get_fantasy_teams()
        schedule = client.get_schedule(teams, current_week=1, playoff_start_week=15)
        assert list(schedule.columns) == ["week", "team_1", "team_2", "score_1", "score_2"]


class TestGetRosterPercentages:
    def test_always_none(self):
        client = GenericClient()
        assert client.get_roster_percentages(pd.DataFrame()) is None


class TestGetAllPlayers:
    def test_pulls_from_nfl_provider_and_filters_positions(self):
        client = GenericClient(season=2026, nfl_provider=FakeNflProvider(ROSTERS))
        players = client.get_all_players()
        offense = players[players["position"] != "DEF"]
        # LS filtered out; Mahomes deduped to the newer (2026) row.
        assert set(offense["name"]) == {"Patrick Mahomes", "Christian McCaffrey"}
        assert set(offense["position"]) <= {"QB", "RB", "WR", "TE", "K"}

    def test_includes_synthetic_def_rows(self):
        client = GenericClient(season=2026, nfl_provider=FakeNflProvider(ROSTERS))
        players = client.get_all_players()
        defense = players[players["position"] == "DEF"]
        assert set(defense["name"]) == {"KC", "SF", "BUF"}
        assert set(defense["player_id_sr"]) == {"KC", "SF", "BUF"}

    def test_expected_columns(self):
        client = GenericClient(season=2026, nfl_provider=FakeNflProvider(ROSTERS))
        players = client.get_all_players()
        assert list(players.columns) == [
            "player_id", "name", "position", "editorial_team_abbr",
            "status", "eligible_positions", "player_id_sr", "yahoo_id",
        ]

    def test_player_id_and_player_id_sr_are_the_same(self):
        client = GenericClient(season=2026, nfl_provider=FakeNflProvider(ROSTERS))
        players = client.get_all_players()
        assert (players["player_id"] == players["player_id_sr"]).all()


class TestGetCurrentWeek:
    @patch("fantasyfb.data.sleeper_client.fetch_nfl_state")
    def test_uses_sleeper_public_state_endpoint(self, mock_fetch):
        mock_fetch.return_value = {"week": 2, "display_week": 3}
        client = GenericClient()
        assert client.get_current_week() == 3

    @patch("fantasyfb.data.sleeper_client.fetch_nfl_state")
    def test_falls_back_to_one_when_unreachable(self, mock_fetch):
        mock_fetch.side_effect = requests.exceptions.RequestException("offline")
        client = GenericClient()
        assert client.get_current_week() == 1
