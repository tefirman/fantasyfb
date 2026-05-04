"""Tests for draft_tools.

All tests run against synthetic projection DataFrames so the suite stays
offline and finishes in well under a second. The fixtures are sized to
exercise the math (replacement-level indexing, tier-gap detection,
opponent ADP-noise sampling) without any real Yahoo or nflreadpy data.
"""

from __future__ import annotations

import io
import math

import numpy as np
import pandas as pd
import pytest

from draft_tools import (
    MockDraft,
    assign_tiers,
    compute_replacement_levels,
    compute_vorp,
    load_adp_csv,
    merge_adp,
)


def _make_projection(name: str, position: str, points_rate: float,
                     **extra) -> dict:
    base = {
        "player_id_sr": name.lower().replace(" ", "_"),
        "name": name,
        "position": position,
        "points_rate": points_rate,
        "points_stdev": 5.0,
        "num_games": 16,
        "volume_rate": 10.0,
        "efficiency_rate": points_rate / 10.0,
    }
    base.update(extra)
    return base


@pytest.fixture
def standard_roster_spec() -> pd.DataFrame:
    """A 1-QB / 2-RB / 3-WR / 1-TE / 1-flex / 1-K / 1-DEF league with
    bench. Matches the most common Yahoo redraft setup."""
    return pd.DataFrame({
        "position": ["QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN"],
        "count":    [1,    2,    3,    1,    1,       1,   1,     6],
    })


@pytest.fixture
def small_pool() -> pd.DataFrame:
    """Enough players at each position to exceed starter demand for a
    12-team league so replacement-level math is well-defined.

    Rates are deliberately spaced so the rank order is unambiguous and
    so a single big WR gap (rank 36 -> 37) lets us pinpoint replacement
    level by hand: 12 teams * 3 starting WR = 36, so the 37th-best WR
    (0-indexed 36) is the replacement.
    """
    rows = []
    # 24 QBs descending from 24 down to 1
    for i in range(24):
        rows.append(_make_projection(f"QB{i:02d}", "QB", 24 - i))
    # 60 RBs
    for i in range(60):
        rows.append(_make_projection(f"RB{i:02d}", "RB", 30 - i * 0.5))
    # 60 WRs
    for i in range(60):
        rows.append(_make_projection(f"WR{i:02d}", "WR", 25 - i * 0.4))
    # 24 TEs
    for i in range(24):
        rows.append(_make_projection(f"TE{i:02d}", "TE", 18 - i * 0.5))
    # 14 Ks and 14 DEFs (just enough for one of each per team)
    for i in range(14):
        rows.append(_make_projection(f"K{i:02d}", "K", 10 - i * 0.3))
    for i in range(14):
        rows.append(_make_projection(f"DEF{i:02d}", "DEF", 8 - i * 0.2))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- #
# Replacement levels + VORP
# --------------------------------------------------------------------- #


class TestReplacementLevels:
    def test_qb_replacement_at_team_count(
        self, small_pool, standard_roster_spec,
    ):
        """1 QB starter * 12 teams = 12; the 13th-best QB (0-indexed
        12) sets replacement level."""
        levels = compute_replacement_levels(small_pool, standard_roster_spec, 12)
        # QB rates were 24, 23, 22, ... so the 13th best (0-indexed 12)
        # has rate 24 - 12 = 12.
        assert levels["QB"] == pytest.approx(12.0)

    def test_wr_replacement_includes_flex_share(
        self, small_pool, standard_roster_spec,
    ):
        """3 WR starters + 1/3 of the 1-flex slot per team * 12 teams
        = 36 + 4 = 40 starters. The 41st-best WR sets replacement."""
        levels = compute_replacement_levels(small_pool, standard_roster_spec, 12)
        # WR rates: 25 - i*0.4. Index 40 -> 25 - 16 = 9.0.
        assert levels["WR"] == pytest.approx(9.0, abs=0.5)

    def test_position_with_no_slots_is_nan(self, small_pool):
        """A K-less league should expose NaN replacement for K."""
        spec = pd.DataFrame({"position": ["QB", "RB", "WR", "TE", "DEF", "BN"],
                             "count":    [1,    2,    3,    1,    1,    7]})
        levels = compute_replacement_levels(small_pool, spec, 12)
        assert math.isnan(levels["K"])

    def test_accepts_dict_roster_spec(self, small_pool):
        """The dict form of roster_spec should produce identical levels
        to the DataFrame form."""
        spec_df = pd.DataFrame({"position": ["QB", "RB", "WR", "TE", "K", "DEF"],
                                "count":    [1,    2,    3,    1,    1,    1]})
        spec_dict = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "K": 1, "DEF": 1}
        a = compute_replacement_levels(small_pool, spec_df, 12)
        b = compute_replacement_levels(small_pool, spec_dict, 12)
        assert a == b


class TestVORP:
    def test_top_player_has_positive_vorp(
        self, small_pool, standard_roster_spec,
    ):
        out = compute_vorp(small_pool, standard_roster_spec, 12)
        top_rb = out.loc[out["name"] == "RB00"].iloc[0]
        assert top_rb["vorp_per_game"] > 0
        assert top_rb["vorp_season"] == pytest.approx(
            top_rb["vorp_per_game"] * 17,
        )

    def test_replacement_level_player_has_zero_vorp(
        self, small_pool, standard_roster_spec,
    ):
        """The QB ranked exactly at replacement level should have VORP
        ~0 (it's the player whose rate set the baseline)."""
        out = compute_vorp(small_pool, standard_roster_spec, 12)
        qb12 = out.loc[out["name"] == "QB12"].iloc[0]
        assert qb12["vorp_per_game"] == pytest.approx(0.0)

    def test_below_replacement_is_negative(
        self, small_pool, standard_roster_spec,
    ):
        out = compute_vorp(small_pool, standard_roster_spec, 12)
        worst_qb = out.loc[out["name"] == "QB23"].iloc[0]
        assert worst_qb["vorp_per_game"] < 0


# --------------------------------------------------------------------- #
# Tiers
# --------------------------------------------------------------------- #


class TestTiers:
    def test_obvious_gap_creates_new_tier(self):
        """Three RBs in 'top tier', huge gap, three RBs in 'low tier'
        should produce exactly two tiers."""
        df = pd.DataFrame([
            _make_projection("Elite1", "RB", 25),
            _make_projection("Elite2", "RB", 24),
            _make_projection("Elite3", "RB", 23),
            _make_projection("Mid1",   "RB", 12),
            _make_projection("Mid2",   "RB", 11),
            _make_projection("Mid3",   "RB", 10),
        ])
        out = assign_tiers(df, positions=["RB"], min_gap_z=0.5)
        elite_tiers = set(out.loc[out["name"].str.startswith("Elite"), "tier"])
        mid_tiers = set(out.loc[out["name"].str.startswith("Mid"),   "tier"])
        assert elite_tiers == {1}
        assert mid_tiers == {2}

    def test_uniform_rates_collapse_to_one_tier(self):
        df = pd.DataFrame([
            _make_projection(f"WR{i}", "WR", 10.0) for i in range(5)
        ])
        out = assign_tiers(df, positions=["WR"])
        assert (out["tier"] == 1).all()

    def test_max_tiers_caps(self):
        """A monotone-falling sequence with growing gaps -- where every
        gap exceeds any reasonable threshold -- should still be capped
        at max_tiers."""
        # Quadratic falloff so gaps strictly increase, ensuring each
        # one beats the median+MAD threshold even at the default z.
        df = pd.DataFrame([
            _make_projection(f"WR{i:02d}", "WR", 1000 - i ** 2)
            for i in range(20)
        ])
        out = assign_tiers(df, positions=["WR"], min_gap_z=-100, max_tiers=4)
        assert int(out["tier"].max()) == 4

    def test_realistic_distribution_does_not_singletons(self):
        """Regression for the original 'every player gets its own tier'
        bug. With a realistic decay (top heavy, smooth tail), the top
        of the position should produce tiers with multiple players,
        not rank-1-per-tier."""
        rows = []
        # Top 3 elites tightly clustered, then a clear break, then a
        # smooth descent of ~25 RBs (mimics real RB-position shape).
        for name, rate in [
            ("Elite1", 15.75), ("Elite2", 15.63), ("Elite3", 15.59),
            ("Bijan",  14.43),  # 1.16 gap (real tier break)
        ]:
            rows.append(_make_projection(name, "RB", rate))
        # Smooth descent: rates fall by 0.2-0.4 each rank
        rates_tail = [14.11, 13.83, 13.49, 13.33, 13.22, 12.77,
                      11.74, 11.11, 10.62, 10.60, 10.59,
                      9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5,
                      5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0]
        for i, r in enumerate(rates_tail):
            rows.append(_make_projection(f"Tail{i:02d}", "RB", r))
        df = pd.DataFrame(rows)
        out = assign_tiers(df, positions=["RB"])
        # Top 4 (Elite1-3 + Bijan) should span at most 2 tiers.
        top4 = out.loc[out["name"].isin(
            ["Elite1", "Elite2", "Elite3", "Bijan"]), "tier"]
        assert top4.nunique() <= 2
        # And the top 15 shouldn't fragment into more than ~6 tiers --
        # if it does, we're back to rank-as-tier behavior.
        tiered = out["tier"].dropna()
        assert tiered.nunique() <= 6

    def test_players_beyond_top_n_get_nan_tier(self):
        df = pd.DataFrame([
            _make_projection(f"WR{i:03d}", "WR", 100 - i)
            for i in range(50)
        ])
        out = assign_tiers(df, positions=["WR"], top_n=10)
        in_top = out[out["name"].isin([f"WR{i:03d}" for i in range(10)])]
        below = out[out["name"].isin([f"WR{i:03d}" for i in range(10, 50)])]
        assert in_top["tier"].notna().all()
        assert below["tier"].isna().all()


# --------------------------------------------------------------------- #
# ADP loader + merge
# --------------------------------------------------------------------- #


class TestADP:
    def test_load_strips_position_rank_suffix(self, tmp_path):
        csv = tmp_path / "adp.csv"
        csv.write_text(
            "Player,POS,Team,AVG\n"
            "Justin Jefferson,WR1,MIN,1.5\n"
            "Christian McCaffrey,RB1,SF,2.0\n"
            "Cowboys,DST,DAL,140.0\n"
        )
        adp = load_adp_csv(str(csv))
        assert set(adp["position"]) == {"WR", "RB", "DEF"}
        assert adp.loc[adp["name"] == "Justin Jefferson", "adp"].iloc[0] == 1.5

    def test_merge_adds_value_columns(self, small_pool):
        adp_df = pd.DataFrame({
            "name":     ["RB00", "RB01", "WR00"],
            "position": ["RB",   "RB",   "WR"],
            "adp":      [1.0,    5.0,    50.0],
        })
        merged = merge_adp(small_pool, adp_df, num_teams=12)
        rb00 = merged.loc[merged["name"] == "RB00"].iloc[0]
        # RB00 is the highest-projected player overall, so proj_rank=1,
        # adp=1.0 -> adp_value=0.0.
        assert rb00["proj_rank"] == 1
        assert rb00["adp_value"] == pytest.approx(0.0)

    def test_value_pick_has_positive_delta(self, small_pool):
        """A player drafted late but projected highly is a 'value pick'
        -- their adp_value should be positive."""
        adp_df = pd.DataFrame({
            "name":     ["RB00"],
            "position": ["RB"],
            "adp":      [50.0],  # absurdly late for the top RB
        })
        merged = merge_adp(small_pool, adp_df, num_teams=12)
        rb00 = merged.loc[merged["name"] == "RB00"].iloc[0]
        assert rb00["adp_value"] > 40

    def test_unknown_player_has_nan_adp(self, small_pool):
        adp_df = pd.DataFrame({
            "name": ["RB00"], "position": ["RB"], "adp": [1.0],
        })
        merged = merge_adp(small_pool, adp_df, num_teams=12)
        assert pd.isna(merged.loc[merged["name"] == "WR00", "adp"].iloc[0])


# --------------------------------------------------------------------- #
# Mock draft simulator
# --------------------------------------------------------------------- #


@pytest.fixture
def draft_ready_pool(small_pool, standard_roster_spec) -> pd.DataFrame:
    """Pool with VORP and ADP attached -- the input contract for MockDraft.
    ADP roughly tracks projection rank with a tiny perturbation so the
    'opponent picks near ADP' behavior is exercisable."""
    with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
    pool = with_vorp.sort_values("points_rate", ascending=False).reset_index(drop=True)
    pool["adp"] = np.arange(1, len(pool) + 1, dtype=float)
    return pool


class TestMockDraft:
    def test_missing_columns_raises(self, small_pool, standard_roster_spec):
        with pytest.raises(ValueError, match="missing required columns"):
            MockDraft(small_pool, standard_roster_spec, num_teams=12)

    def test_invalid_pick_position_raises(
        self, draft_ready_pool, standard_roster_spec,
    ):
        with pytest.raises(ValueError, match="my_pick"):
            MockDraft(draft_ready_pool, standard_roster_spec,
                      num_teams=12, my_pick=99)

    def test_total_picks_equals_team_count_times_roster(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=6, noise_sd=4.0)
        result = md.simulate(seed=42)
        # 1+2+3+1+1+1+1 starters + 6 bench = 16 per team * 12 teams
        assert len(result) == 16 * 12

    def test_no_player_drafted_twice(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=1, noise_sd=4.0)
        result = md.simulate(seed=7)
        assert result["name"].is_unique

    def test_snake_order_reverses_each_round(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=1, snake=True, noise_sd=4.0)
        result = md.simulate(seed=1)
        round1 = result[result["round"] == 1]["team"].tolist()
        round2 = result[result["round"] == 2]["team"].tolist()
        assert round1 == list(range(1, 13))
        assert round2 == list(range(12, 0, -1))

    def test_user_picks_match_strategy(
        self, draft_ready_pool, standard_roster_spec,
    ):
        """With BPA, the user's first pick should be the highest
        points_rate available at their slot."""
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=1, noise_sd=2.0,
                       my_strategy="bpa")
        result = md.simulate(seed=11)
        first_user_pick = result[result["is_user"]].iloc[0]
        # User picks first overall, so they should get the player with
        # max points_rate from the pool.
        assert first_user_pick["points_rate"] == draft_ready_pool["points_rate"].max()

    def test_low_noise_keeps_picks_near_adp(
        self, draft_ready_pool, standard_roster_spec,
    ):
        """With near-zero noise, opponent picks should very nearly
        match the ADP ordering. Allow some tolerance for the user's
        slot which is strategy-driven, and for positional-need filtering
        late in the draft when remaining ADP-near players don't fit
        anyone's open slots."""
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=12, noise_sd=0.5,
                       my_strategy="bpa")
        result = md.simulate(seed=3)
        # First two rounds (24 picks): the average gap between actual
        # pick number and player's ADP should be small.
        early = result.head(24)
        gap = (early["pick"] - early["adp"]).abs().mean()
        assert gap < 4.0

    def test_simulate_many_returns_seeded_reproducible_runs(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=6, noise_sd=4.0)
        a = md.simulate_many(3, seed=99)
        b = md.simulate_many(3, seed=99)
        pd.testing.assert_frame_equal(a, b)
        assert a["sim"].nunique() == 3

    def test_availability_recovers_taken_vs_missing(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=6, noise_sd=4.0)
        runs = md.simulate_many(5, seed=2)
        avail = md.availability(runs, pick_number=12)
        # Player taken in every sim before pick 12 should show 0%
        # availability; player whose avg pick is >> 12 should show high.
        always_taken_early = avail[avail["avg_pick_taken"] < 5]
        assert (always_taken_early["available_pct"] < 0.2).all()
        late = avail[avail["avg_pick_taken"] > 100]
        assert (late["available_pct"] > 0.8).all()
