"""Tests for the parts of PlayerDataManager that don't need Yahoo creds.

map_player_ids and add_bye_weeks do almost all the heavy lifting that is
data-source-coupled, so these are the highest-value targets for catching
regressions when the provider schema drifts.
"""

from __future__ import annotations

import pandas as pd
import pytest

from player_data_manager import PlayerDataManager


@pytest.fixture
def manager(provider) -> PlayerDataManager:
    # yahoo_client=None is fine here; the methods under test never reach
    # for it.
    return PlayerDataManager(
        yahoo_client=None, season=2024, current_week=4, nfl_provider=provider,
    )


@pytest.fixture
def synthetic_yahoo_players(rosters: pd.DataFrame, team_aliases: pd.DataFrame) -> tuple:
    """Yahoo-shaped players DataFrame built from real nflreadpy rosters.

    Returns a (players_df, expected_gsis_by_yahoo_id) tuple. Round-tripping
    through map_player_ids should land each synthetic player back on the
    same gsis_id that seeded it.
    """
    yahoo_to_real = team_aliases.set_index("real_abbrev")["yahoo"].to_dict()
    sample = rosters.dropna(subset=["yahoo_id"]).head(20).copy()
    sample = sample[sample["current_team"].isin(yahoo_to_real)]

    players = pd.DataFrame({
        "player_id": sample["yahoo_id"].astype(int),
        "name": sample["name"],
        "position": sample["position"],
        "editorial_team_abbr": sample["current_team"].map(yahoo_to_real),
        "status": "",
        "fantasy_team": None,
    })
    expected = dict(zip(sample["yahoo_id"].astype(int), sample["player_id_sr"]))
    return players, expected


class TestMapPlayerIds:
    def test_links_every_synthesized_player(
        self, manager: PlayerDataManager, synthetic_yahoo_players
    ) -> None:
        players, _ = synthetic_yahoo_players
        mapped = manager.map_player_ids(players)
        linked = mapped.dropna(subset=["player_id_sr"])
        assert len(linked) == len(players)

    def test_yahoo_id_resolves_to_correct_gsis(
        self, manager: PlayerDataManager, synthetic_yahoo_players
    ) -> None:
        players, expected = synthetic_yahoo_players
        mapped = manager.map_player_ids(players)
        for _, row in mapped.iterrows():
            yid = int(row["player_id"])
            assert row["player_id_sr"] == expected[yid]


class TestAddByeWeeks:
    def test_every_team_has_bye(
        self,
        manager: PlayerDataManager,
        schedule: pd.DataFrame,
    ) -> None:
        # One synthetic player per NFL team, using the same team codes the
        # schedule uses. Pre-fix this would have silently dropped the eight
        # teams whose Yahoo->NFL alias differed (ARI, BAL, HOU, IND, LAC,
        # LA, LV, TEN).
        teams = sorted(schedule["team"].unique())
        players = pd.DataFrame({
            "name": teams, "position": "QB", "current_team": teams,
        })
        result = manager.add_bye_weeks(players, schedule)
        assert result["bye_week"].notna().all()
        assert len(result) == len(teams)

    def test_byes_in_plausible_range(
        self,
        manager: PlayerDataManager,
        schedule: pd.DataFrame,
    ) -> None:
        teams = sorted(schedule["team"].unique())
        players = pd.DataFrame({
            "name": teams, "position": "QB", "current_team": teams,
        })
        result = manager.add_bye_weeks(players, schedule)
        # NFL bye weeks fall between weeks 5 and 14.
        assert result["bye_week"].between(5, 14).all()
