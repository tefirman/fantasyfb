"""Tests for the NflreadpyProvider data backend.

These exercise the canonical schema fantasyfb expects from any
NFLDataProvider, plus a handful of value-level invariants (spread sign
convention, team-code consistency between schedule and team_aliases) that
have bitten us during the sportsref_nfl -> nflreadpy migration.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasyfb.data import nflreadpy_provider as mod
from fantasyfb.data.nflreadpy_provider import _clamp_seasons, _load_pandas


REQUIRED_STAT_COLS = {
    "player_id_sr", "name", "position", "team", "opponent",
    "season", "week", "game_id", "points_allowed",
    "rush_yds", "rush_att", "rush_td", "rush_first_down",
    "rec", "rec_yds", "rec_td", "rec_first_down",
    "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
    "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
    "kick_ret_td", "punt_ret_td", "xpm", "fgm",
    "sacks", "def_int", "fumbles_rec", "def_int_td", "fumbles_rec_td",
}

REQUIRED_SCHEDULE_COLS = {
    "season", "week", "date", "team", "home_away",
    "opp_team", "elo_diff", "opp_elo",
}


class TestPlayerStats:
    def test_returns_rows(self, stats: pd.DataFrame) -> None:
        assert len(stats) > 500

    def test_required_columns_present(self, stats: pd.DataFrame) -> None:
        missing = REQUIRED_STAT_COLS - set(stats.columns)
        assert not missing, f"missing columns: {missing}"

    def test_six_fantasy_positions_present(self, stats: pd.DataFrame) -> None:
        assert {"QB", "RB", "WR", "TE", "K", "DEF"}.issubset(stats.position.unique())

    def test_defenses_have_points_allowed(self, stats: pd.DataFrame) -> None:
        defenses = stats[stats.position == "DEF"]
        assert len(defenses) >= 32
        assert defenses["points_allowed"].notna().all()

    def test_defense_sacks_in_plausible_range(self, stats: pd.DataFrame) -> None:
        defenses = stats[stats.position == "DEF"]
        assert defenses["sacks"].between(0, 12).all()

    def test_yyyyww_range_respected(self, stats: pd.DataFrame) -> None:
        as_of = stats.season * 100 + stats.week
        assert as_of.min() >= 202401
        assert as_of.max() <= 202404


class TestSchedule:
    def test_returns_rows(self, schedule: pd.DataFrame) -> None:
        assert len(schedule) > 500

    def test_required_columns_present(self, schedule: pd.DataFrame) -> None:
        missing = REQUIRED_SCHEDULE_COLS - set(schedule.columns)
        assert not missing, f"missing columns: {missing}"

    def test_home_and_away_rows_balanced(self, schedule: pd.DataFrame) -> None:
        home = (schedule.home_away == "Home").sum()
        away = (schedule.home_away == "Away").sum()
        assert home == away

    def test_home_favorite_has_positive_elo_diff(self, schedule: pd.DataFrame) -> None:
        # KC hosted BAL in 2024 W1 as a 3-point favorite. The legacy
        # convention is positive elo_diff for the favored team.
        kc_w1 = schedule[
            (schedule.season == 2024) & (schedule.week == 1) & (schedule.team == "KC")
        ]
        assert not kc_w1.empty
        assert float(kc_w1.iloc[0]["elo_diff"]) > 0

    def test_vegas_columns_present(self, schedule: pd.DataFrame) -> None:
        for col in ["spread_line", "total_line", "implied_total", "opp_implied_total"]:
            assert col in schedule.columns

    def test_implied_totals_sum_to_over_under(self, schedule: pd.DataFrame) -> None:
        # By construction: home_implied + away_implied == total_line. Pick
        # one game per week to spot-check this identity.
        sample = schedule[(schedule.season == 2024) & (schedule.total_line > 0)]
        sample = sample.drop_duplicates(subset=["season", "week", "team"]).head(20)
        for _, row in sample.iterrows():
            assert row["implied_total"] + row["opp_implied_total"] == pytest.approx(row["total_line"])

    def test_home_favorite_has_higher_implied_total(self, schedule: pd.DataFrame) -> None:
        kc_w1 = schedule[
            (schedule.season == 2024) & (schedule.week == 1) & (schedule.team == "KC")
        ].iloc[0]
        bal_w1 = schedule[
            (schedule.season == 2024) & (schedule.week == 1) & (schedule.team == "BAL")
        ].iloc[0]
        # KC was favored by 3, so KC's implied total should beat BAL's by 3.
        assert kc_w1["implied_total"] - bal_w1["implied_total"] == pytest.approx(3.0)


class TestRosters:
    def test_returns_rows(self, rosters: pd.DataFrame) -> None:
        assert len(rosters) > 1000

    def test_yahoo_id_column_present(self, rosters: pd.DataFrame) -> None:
        assert "yahoo_id" in rosters.columns

    def test_yahoo_id_populated_for_majority(self, rosters: pd.DataFrame) -> None:
        # The whole point of the swap was to get yahoo_id directly. If the
        # population rate craters, the cleanest signal that nflverse
        # changed its roster schema again.
        assert rosters["yahoo_id"].notna().mean() > 0.5

    def test_player_id_in_gsis_format(self, rosters: pd.DataFrame) -> None:
        gsis_match = rosters["player_id_sr"].astype(str).str.match(r"^00-\d{7}$")
        assert gsis_match.mean() > 0.9


class TestDepthCharts:
    def test_returns_rows(self, depth_charts: pd.DataFrame) -> None:
        assert len(depth_charts) > 100

    def test_required_columns_present(self, depth_charts: pd.DataFrame) -> None:
        required = {"name", "current_team", "position", "string", "player_id_sr"}
        assert required.issubset(depth_charts.columns)

    def test_string_column_populated_and_numeric(self, depth_charts: pd.DataFrame) -> None:
        assert depth_charts["string"].notna().all()
        assert pd.api.types.is_numeric_dtype(depth_charts["string"])

    def test_fantasy_positions_present(self, depth_charts: pd.DataFrame) -> None:
        positions = set(depth_charts["position"].dropna().unique())
        assert {"QB", "RB", "WR", "TE"}.issubset(positions)


class TestTeamAliases:
    def test_returns_thirty_two_teams(self, team_aliases: pd.DataFrame) -> None:
        assert len(team_aliases) == 32

    def test_required_columns_present(self, team_aliases: pd.DataFrame) -> None:
        assert {"yahoo", "real_abbrev"}.issubset(team_aliases.columns)

    def test_alias_codes_match_schedule_codes(
        self, team_aliases: pd.DataFrame, schedule: pd.DataFrame
    ) -> None:
        # This is the regression that bit us during the swap: legacy
        # team_abbrevs.csv used PFR-style real_abbrev (CRD, RAV, ...) while
        # nflreadpy uses standard NFL codes (ARI, BAL, ...). Asserting
        # equality keeps that class of bug from coming back.
        schedule_teams = set(schedule["team"].unique())
        alias_teams = set(team_aliases["real_abbrev"].unique())
        assert schedule_teams == alias_teams, (
            f"in schedule not aliases: {schedule_teams - alias_teams}; "
            f"in aliases not schedule: {alias_teams - schedule_teams}"
        )


class TestDraft:
    def test_returns_rows(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert len(draft) >= 200

    def test_required_columns_present(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert {"name", "current_team", "player_id_sr"}.issubset(draft.columns)

    def test_first_overall_pick(self, provider) -> None:
        draft = provider.get_draft(2024)
        assert "Caleb Williams" in draft["name"].tolist()


class TestClampSeasons:
    """Pre-draft callers ask for an upcoming season before nflverse has
    uploaded its parquet for it. _clamp_seasons silently drops the
    unavailable years (with a warning) and only fails when the entire
    requested range is past the cutoff.
    """

    def test_passes_through_when_all_available(self):
        out = _clamp_seasons([2023, 2024, 2025], available_max=2025,
                             context="stats")
        assert out == [2023, 2024, 2025]

    def test_drops_future_seasons_with_warning(self):
        with pytest.warns(UserWarning, match="2026"):
            out = _clamp_seasons([2024, 2025, 2026], available_max=2025,
                                 context="stats")
        assert out == [2024, 2025]

    def test_raises_when_no_seasons_available(self):
        with pytest.raises(ValueError, match="No available seasons"):
            _clamp_seasons([2026, 2027], available_max=2025, context="stats")

    def test_no_warning_when_nothing_dropped(self, recwarn):
        _clamp_seasons([2024], available_max=2025, context="stats")
        assert len(recwarn) == 0


class TestCacheConfig:
    """NflreadpyProvider.__init__ configures nflreadpy's own caching layer.

    nflreadpy already caches every download, but defaults to an in-memory
    cache that's wiped at process exit -- useless across the separate CLI
    invocations that make up a draft-prep session. We switch it to
    filesystem caching by default so pulls persist across runs, enabling
    offline operation after the first successful pull. These tests stub
    out `_nfl_update_config`/`nfl.clear_cache` so they exercise only our
    decision logic, not nflreadpy's real config singleton or the network.
    """

    def test_defaults_to_filesystem_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: calls.append(kw))
        monkeypatch.delenv("NFLREADPY_CACHE", raising=False)
        mod.NflreadpyProvider()
        assert calls == [{"cache_mode": "filesystem"}]

    def test_explicit_cache_mode_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: calls.append(kw))
        mod.NflreadpyProvider(cache_mode="off")
        assert calls == [{"cache_mode": "off"}]

    def test_respects_existing_cache_env_var(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # If the user (or their shell profile) already set NFLREADPY_CACHE,
        # our default shouldn't clobber it.
        calls = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: calls.append(kw))
        monkeypatch.setenv("NFLREADPY_CACHE", "memory")
        mod.NflreadpyProvider()
        assert calls == []

    def test_cache_duration_passed_through_with_default_mode(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: calls.append(kw))
        monkeypatch.delenv("NFLREADPY_CACHE", raising=False)
        mod.NflreadpyProvider(cache_duration=3600)
        assert calls == [{"cache_mode": "filesystem", "cache_duration": 3600}]

    def test_refresh_clears_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cleared = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: None)
        monkeypatch.setattr(mod.nfl, "clear_cache", lambda: cleared.append(True))
        mod.NflreadpyProvider(refresh=True)
        assert cleared == [True]

    def test_no_refresh_does_not_clear_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cleared = []
        monkeypatch.setattr(mod, "_nfl_update_config", lambda **kw: None)
        monkeypatch.setattr(mod.nfl, "clear_cache", lambda: cleared.append(True))
        mod.NflreadpyProvider()
        assert cleared == []


class TestDepthChartsOfflineFallback:
    """get_depth_charts, unlike get_schedule/get_rosters/get_player_stats,
    never goes through _clamp_seasons -- it always asks for the current
    calendar year's depth chart file directly, which nflverse may not have
    published yet, or which may be unreachable if offline with a cold
    cache. Confirms it degrades to an empty frame instead of raising in
    both cases, matching the empty-dataframe fallback already used when
    nflreadpy legitimately has no rows for a season.
    """

    def test_connection_error_on_latest_season_falls_back_to_prior_year(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []

        def loader(**kwargs):
            season = kwargs["seasons"][0]
            calls.append(season)
            if season == mod.pd.Timestamp.now(tz="UTC").year:
                raise ConnectionError("simulated offline / cache miss")
            raise ValueError("unexpectedly reached second fallback")

        monkeypatch.setattr(mod.nfl, "load_depth_charts", loader)
        provider = mod.NflreadpyProvider.__new__(mod.NflreadpyProvider)
        out = provider._try_load_depth_charts(mod.pd.Timestamp.now(tz="UTC").year)
        assert out.empty
        assert calls == [mod.pd.Timestamp.now(tz="UTC").year]

    def test_get_depth_charts_returns_empty_frame_when_fully_unreachable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def loader(**kwargs):
            raise ConnectionError("simulated offline / cache miss")

        monkeypatch.setattr(mod.nfl, "load_depth_charts", loader)
        provider = mod.NflreadpyProvider.__new__(mod.NflreadpyProvider)
        out = provider.get_depth_charts()
        assert out.empty
        assert list(out.columns) == [
            "name", "current_team", "position", "string", "player_id_sr",
        ]

    def test_missing_season_file_falls_back_without_raising(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # nflreadpy raises ValueError (not the polars-UTF8 flavor _load_pandas
        # special-cases) when a requested season's parquet doesn't exist
        # upstream yet -- e.g. depth charts for a season that hasn't
        # started. That must also degrade gracefully, not propagate.
        def loader(**kwargs):
            raise ValueError("404: season not published")

        monkeypatch.setattr(mod.nfl, "load_depth_charts", loader)
        provider = mod.NflreadpyProvider.__new__(mod.NflreadpyProvider)
        out = provider._try_load_depth_charts(2099)
        assert out.empty


class TestLoadPandasFallback:
    """`_load_pandas` shields callers from the polars-strict UTF-8 error
    nflverse intermittently triggers (see provider module-level comment).
    These tests stub the loader and the network so the helper logic can
    be exercised hermetically.
    """

    _PARSE_ERR = (
        "Failed to parse data from https://example.test/games.parquet: "
        "parquet: File out of specification: String data contained invalid UTF-8"
    )

    def test_passthrough_when_loader_succeeds(self) -> None:
        def loader(**kwargs):
            class _Frame:
                @staticmethod
                def to_pandas():
                    return pd.DataFrame({"season": [2024], "x": [1]})
            return _Frame()
        out = _load_pandas(loader, seasons=[2024])
        assert out["x"].tolist() == [1]

    def test_unrelated_value_error_propagates(self) -> None:
        def loader(**kwargs):
            raise ValueError("some other failure")
        with pytest.raises(ValueError, match="some other failure"):
            _load_pandas(loader, seasons=[2024])

    def test_single_file_fallback_applies_season_filter(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        full = pd.DataFrame({"season": [2022, 2023, 2024], "x": [1, 2, 3]})
        called = {}

        def fake_fallback(url: str) -> pd.DataFrame:
            called["url"] = url
            return full

        monkeypatch.setattr(
            "fantasyfb.data.nflreadpy_provider._pyarrow_fallback", fake_fallback,
        )

        def loader(**kwargs):
            raise ValueError(self._PARSE_ERR)

        out = _load_pandas(loader, seasons=[2023, 2024])
        assert called["url"] == "https://example.test/games.parquet"
        assert out["season"].tolist() == [2023, 2024]

    def test_per_season_fallback_only_replaces_broken_year(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        good_years = {2022, 2023}
        broken_year = 2024

        def fake_fallback(url: str) -> pd.DataFrame:
            return pd.DataFrame({"season": [broken_year], "x": [99]})

        monkeypatch.setattr(
            "fantasyfb.data.nflreadpy_provider._pyarrow_fallback", fake_fallback,
        )

        def loader(**kwargs):
            seasons = kwargs["seasons"]
            # The multi-season call mimics nflreadpy bailing on the broken
            # year mid-loop. The per-season retries succeed for the good
            # years and fail (triggering fallback) for the broken one.
            if len(seasons) > 1 or seasons[0] == broken_year:
                raise ValueError(self._PARSE_ERR)
            season = seasons[0]
            assert season in good_years
            class _Frame:
                def to_pandas(self):
                    return pd.DataFrame({"season": [season], "x": [season]})
            return _Frame()

        out = _load_pandas(
            loader, per_season=True, seasons=[2022, 2023, broken_year],
        )
        assert sorted(out["season"].tolist()) == [2022, 2023, 2024]
        assert out.loc[out.season == broken_year, "x"].iloc[0] == 99

    def test_pyarrow_fallback_emits_warning_and_returns_pandas(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from contextlib import contextmanager

        import pyarrow as pa

        from fantasyfb.data import nflreadpy_provider as mod

        @contextmanager
        def fake_urlopen(url):
            class _Resp:
                @staticmethod
                def read():
                    return b"<bytes>"
            yield _Resp()

        # Build an Arrow table whose string column carries a raw 0xE2
        # byte that Python can't decode as UTF-8 -- mirrors the
        # `Levi's<bad byte> Stadium` value nflverse ships. Without the
        # sanitize step, .to_pandas() raises on Python 3.10.
        bad_string = pa.array(
            [b"Levi's\xe2 Stadium"], type=pa.binary(),
        ).cast(pa.string(), safe=False)
        table = pa.table({"season": pa.array([2024]), "stadium": bad_string})

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(mod.pq, "read_table", lambda _bio: table)

        with pytest.warns(UserWarning, match="invalid UTF-8"):
            out = mod._pyarrow_fallback("https://example.test/games.parquet")
        assert out["season"].tolist() == [2024]
        # The bad byte should have been replaced with U+FFFD, not raised.
        assert "�" in out["stadium"].iloc[0]
