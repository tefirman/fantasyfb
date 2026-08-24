"""Tests for the parts of PlayerDataManager that don't need Yahoo creds.

map_player_ids and add_bye_weeks do almost all the heavy lifting that is
data-source-coupled, so these are the highest-value targets for catching
regressions when the provider schema drifts.
"""

from __future__ import annotations

import datetime
import urllib.error

import pandas as pd
import pytest

from fantasyfb.data.player_data_manager import PlayerDataManager


@pytest.fixture
def manager(provider) -> PlayerDataManager:
    # client=None is fine here; the methods under test never reach for it.
    return PlayerDataManager(
        client=None, season=2024, current_week=4, nfl_provider=provider,
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

    def test_falls_back_to_name_team_when_yahoo_id_missing(
        self,
        manager: PlayerDataManager,
        rosters: pd.DataFrame,
        team_aliases: pd.DataFrame,
    ) -> None:
        """Regression: nflverse's yahoo_id cross-reference lags real
        roster additions (~half the 2025 rookie class as of mid-2026
        had null yahoo_id even though they played a full season). A
        Yahoo-shaped player whose only link to nflreadpy is name+team
        should still resolve to the right gsis_id.
        """
        yahoo_to_real = team_aliases.set_index("real_abbrev")["yahoo"].to_dict()
        # Pick a roster row with a populated gsis_id whose yahoo_id we
        # then null out on the input side, simulating nflverse not
        # having backfilled this player yet.
        target = (
            rosters.dropna(subset=["yahoo_id"])
            .iloc[0]
        )
        assert target["current_team"] in yahoo_to_real
        players = pd.DataFrame([{
            # Distinct yahoo player_id that won't match anything in
            # nflreadpy's yahoo_id column -- forces the fallback path.
            "player_id": 9999999,
            "name": target["name"],
            "position": target["position"],
            "editorial_team_abbr": yahoo_to_real[target["current_team"]],
            "status": "",
            "fantasy_team": None,
        }])
        mapped = manager.map_player_ids(players)
        assert mapped.iloc[0]["player_id_sr"] == target["player_id_sr"]


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


class FakeClientNoRosterPercentages:
    """Stands in for a client backend with no ownership-% concept (Sleeper)."""

    def get_roster_percentages(self, players_df, chunk_size=25):
        return None


class FakeClientWithRosterPercentages:
    """Stands in for a client backend that does return roster percentages (Yahoo)."""

    def __init__(self, roster_pcts: pd.DataFrame):
        self._roster_pcts = roster_pcts

    def get_roster_percentages(self, players_df, chunk_size=25):
        return self._roster_pcts


class TestAddRosterPercentages:
    def test_defaults_to_zero_when_client_returns_none(self, provider) -> None:
        manager = PlayerDataManager(
            client=FakeClientNoRosterPercentages(),
            season=2024, current_week=4, nfl_provider=provider,
        )
        players = pd.DataFrame({
            "player_id": [1, 2],
            "name": ["A", "B"],
            "player_id_sr": ["a", "b"],
            "fantasy_team": [None, None],
        })
        result = manager.add_roster_percentages(players)
        assert (result["pct_rostered"] == 0.0).all()

    def test_merges_percentages_when_client_returns_data(self, provider) -> None:
        roster_pcts = pd.DataFrame({"player_id": [1, 2], "pct_rostered": [0.9, 0.1]})
        manager = PlayerDataManager(
            client=FakeClientWithRosterPercentages(roster_pcts),
            season=2024, current_week=4, nfl_provider=provider,
        )
        players = pd.DataFrame({
            "player_id": [1, 2],
            "name": ["A", "B"],
            "player_id_sr": ["x", "y"],
            "fantasy_team": [None, None],
        })
        result = manager.add_roster_percentages(players)
        by_id = result.set_index("player_id")
        assert by_id.loc[1, "pct_rostered"] == 0.9
        assert by_id.loc[2, "pct_rostered"] == 0.1

    def test_missing_players_default_to_zero_pct(self, provider) -> None:
        roster_pcts = pd.DataFrame({"player_id": [1], "pct_rostered": [0.5]})
        manager = PlayerDataManager(
            client=FakeClientWithRosterPercentages(roster_pcts),
            season=2024, current_week=4, nfl_provider=provider,
        )
        players = pd.DataFrame({
            "player_id": [1, 2],
            "name": ["A", "B"],
            "player_id_sr": ["x", "y"],
            "fantasy_team": [None, None],
        })
        result = manager.add_roster_percentages(players)
        by_id = result.set_index("player_id")
        assert by_id.loc[2, "pct_rostered"] == 0.0


class FakeProviderWithDepthCharts:
    """Wraps a real provider but stubs get_depth_charts with fixed data,
    so tests can control team assignments deterministically instead of
    depending on whatever trades happened to be live when the test ran.
    """

    def __init__(self, real_provider, depth_charts: pd.DataFrame):
        self._real = real_provider
        self._depth_charts = depth_charts

    def get_depth_charts(self):
        return self._depth_charts

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestAddDepthCharts:
    """Regression coverage for issue #65: current_team must reflect the
    live depth chart, not the season-locked roster snapshot, so a player
    who changed teams in the offseason doesn't show up on their old team
    before any current-season stats exist.
    """

    def test_id_match_overrides_stale_current_team(self, provider) -> None:
        manager = PlayerDataManager(
            client=None, season=2026, current_week=1,
            nfl_provider=FakeProviderWithDepthCharts(provider, pd.DataFrame({
                "player_id_sr": ["diggs123"],
                "name": ["Stefon Diggs"],
                "position": ["WR"],
                "current_team": ["WAS"],
                "string": [1.0],
            })),
        )
        players = pd.DataFrame({
            "player_id_sr": ["diggs123"],
            "name": ["Stefon Diggs"],
            "position": ["WR"],
            "current_team": ["NE"],  # stale, from last season's roster snapshot
            "pct_rostered": [0.5],
            "fantasy_team": [None],
            "status": [""],
            "until": [None],
        })
        result = manager.add_depth_charts(players, week=1)
        assert result.iloc[0]["current_team"] == "WAS"

    def test_name_fallback_overrides_stale_current_team(self, provider) -> None:
        # No player_id_sr overlap, so this only resolves through the
        # name+position fallback join -- which used to also require
        # current_team to already match, defeating it for exactly the
        # players who changed teams.
        manager = PlayerDataManager(
            client=None, season=2026, current_week=1,
            nfl_provider=FakeProviderWithDepthCharts(provider, pd.DataFrame({
                "player_id_sr": [None],
                "name": ["Stefon Diggs"],
                "position": ["WR"],
                "current_team": ["WAS"],
                "string": [1.0],
            })),
        )
        players = pd.DataFrame({
            "player_id_sr": ["not-in-depth-chart"],
            "name": ["Stefon Diggs"],
            "position": ["WR"],
            "current_team": ["NE"],
            "pct_rostered": [0.5],
            "fantasy_team": [None],
            "status": [""],
            "until": [None],
        })
        result = manager.add_depth_charts(players, week=1)
        assert result.iloc[0]["current_team"] == "WAS"
        assert result.iloc[0]["string"] == 1.0

    def test_duplicate_name_position_in_depth_chart_does_not_fan_out_rows(
        self, provider
    ) -> None:
        # Rare but real (e.g. two same-named backups at the same
        # position on different teams) -- the name-fallback join must not
        # multiply rows in players when the depth chart has more than one
        # match for a given (name, position).
        manager = PlayerDataManager(
            client=None, season=2026, current_week=1,
            nfl_provider=FakeProviderWithDepthCharts(provider, pd.DataFrame({
                "player_id_sr": [None, None],
                "name": ["Jaylon Jones", "Jaylon Jones"],
                "position": ["CB", "CB"],
                "current_team": ["IND", "SEA"],
                "string": [1.0, 2.0],
            })),
        )
        players = pd.DataFrame({
            "player_id_sr": ["unmatched-id"],
            "name": ["Jaylon Jones"],
            "position": ["CB"],
            "current_team": ["IND"],
            "pct_rostered": [0.1],
            "fantasy_team": [None],
            "status": [""],
            "until": [None],
        })
        result = manager.add_depth_charts(players, week=1)
        assert len(result) == 1


class TestRemoteCsvOfflineFallback:
    """add_injuries fetches a CSV straight from raw.githubusercontent.com
    with no caching and, before this fix, no fallback -- unlike every
    nflreadpy-backed method, this network call is entirely outside
    NflreadpyProvider's persistent filesystem cache. A dead network
    (urllib.error.URLError, what pandas' default urllib backend raises for
    a DNS failure) must degrade to a no-op rather than crashing a
    draft-prep run that's otherwise working fully offline.
    """

    def test_injuries_skipped_when_unreachable(
        self, provider, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # add_injuries only hits the network for the *current* season (it
        # infers past-season status from stats instead), so the manager's
        # season has to match its own latest_season for this branch to run.
        # Mirrors PlayerDataManager.__init__'s own latest_season formula.
        latest_season = datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        current_manager = PlayerDataManager(
            client=None, season=latest_season, current_week=4, nfl_provider=provider,
        )

        def dead_read_csv(*a, **kw):
            raise urllib.error.URLError("simulated offline / DNS failure")

        monkeypatch.setattr(pd, "read_csv", dead_read_csv)
        players = pd.DataFrame({
            "player_id_sr": ["x"], "name": ["Some Player"], "position": ["QB"],
            "status": [""], "fantasy_team": [None],
        })
        with pytest.warns(UserWarning, match="injured_list"):
            result = current_manager.add_injuries(players, week=current_manager.current_week)
        assert "until" in result.columns
        assert result["until"].isna().all()
