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

from fantasyfb.drafts.tools import (
    MockDraft,
    MockSalaryCapDraft,
    assign_tiers,
    backtest_salary_values,
    compute_replacement_levels,
    compute_salary_values,
    compute_vorp,
    load_adp_csv,
    max_bid,
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
# Salary cap values
# --------------------------------------------------------------------- #


class TestSalaryValues:
    def test_money_conserved_across_drafted_picks(
        self, small_pool, standard_roster_spec,
    ):
        """Money conservation: summing salary_value across the top
        `num_teams * roster_size` players (the ones that will actually
        get drafted) should equal `num_teams * salary_cap`. This is the
        defining property of the valuation formula."""
        with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
        valued = compute_salary_values(
            with_vorp, standard_roster_spec, num_teams=12, salary_cap=200,
        )
        # 16 roster slots per team (1+2+3+1+1+1+1 starters + 6 bench) * 12 teams.
        drafted = valued.sort_values("salary_value", ascending=False).head(16 * 12)
        assert drafted["salary_value"].sum() == pytest.approx(12 * 200)

    def test_top_player_has_highest_value(
        self, small_pool, standard_roster_spec,
    ):
        with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
        valued = compute_salary_values(
            with_vorp, standard_roster_spec, num_teams=12, salary_cap=200,
        )
        # RB00 has the highest VORP in this pool (top RB, low RB
        # replacement level) so it should also get the highest value.
        top_by_vorp = valued.sort_values("vorp_season", ascending=False).iloc[0]
        top_by_value = valued.sort_values("salary_value", ascending=False).iloc[0]
        assert top_by_value["name"] == top_by_vorp["name"]

    def test_below_replacement_gets_min_bid(
        self, small_pool, standard_roster_spec,
    ):
        """Players with non-positive VORP fall outside the starter
        cohort and get exactly the min bid."""
        with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
        valued = compute_salary_values(
            with_vorp, standard_roster_spec,
            num_teams=12, salary_cap=200, min_bid=1,
        )
        worst_qb = valued.loc[valued["name"] == "QB23"].iloc[0]
        assert worst_qb["salary_value"] == 1.0

    def test_synthetic_avg_rows_excluded(self, standard_roster_spec):
        """avg_ synthetic rows should never receive an above-min value;
        they aren't real draftable players."""
        rows = []
        for i in range(20):
            rows.append(_make_projection(f"RB{i:02d}", "RB", 20 - i * 0.5))
        # Two synthetic average rows that would otherwise dominate VORP.
        rows.append(_make_projection("avg starter", "RB", 100,
                                     player_id_sr="avg_rb_starter"))
        rows.append(_make_projection("avg bench", "RB", 50,
                                     player_id_sr="avg_rb_bench"))
        df = pd.DataFrame(rows)
        with_vorp = compute_vorp(df, standard_roster_spec, 12)
        valued = compute_salary_values(
            with_vorp, standard_roster_spec, num_teams=12, salary_cap=200,
        )
        synthetic = valued[valued["player_id_sr"].str.startswith("avg_")]
        assert (synthetic["salary_value"] == 1.0).all()

    def test_too_small_cap_raises(self, small_pool, standard_roster_spec):
        """A cap that can't even cover min_bid * roster_size is a
        configuration error."""
        with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
        with pytest.raises(ValueError, match="too small"):
            compute_salary_values(
                with_vorp, standard_roster_spec,
                num_teams=12, salary_cap=10, min_bid=1,
            )

    def test_missing_vorp_raises(self, small_pool, standard_roster_spec):
        with pytest.raises(ValueError, match="vorp_season"):
            compute_salary_values(
                small_pool, standard_roster_spec,
                num_teams=12, salary_cap=200,
            )

    def test_accepts_dict_roster_spec(self, small_pool):
        """Dict and DataFrame roster_spec forms produce identical values."""
        spec_df = pd.DataFrame({
            "position": ["QB", "RB", "WR", "TE", "K", "DEF", "BN"],
            "count":    [1,    2,    3,    1,    1,    1,     6],
        })
        spec_dict = {"QB": 1, "RB": 2, "WR": 3, "TE": 1,
                     "K": 1, "DEF": 1, "BN": 6}
        a = compute_salary_values(
            compute_vorp(small_pool, spec_df, 12),
            spec_df, num_teams=12, salary_cap=200,
        )
        b = compute_salary_values(
            compute_vorp(small_pool, spec_dict, 12),
            spec_dict, num_teams=12, salary_cap=200,
        )
        assert (a["salary_value"].to_numpy()
                == b["salary_value"].to_numpy()).all()

    def test_all_negative_vorp_collapses_to_min_bid(self, standard_roster_spec):
        """If nobody has positive VORP (degenerate pool below replacement
        level), every player gets exactly min_bid -- no division by zero,
        no negative values."""
        rows = [_make_projection(f"WR{i:02d}", "WR", 1.0) for i in range(50)]
        df = pd.DataFrame(rows)
        with_vorp = compute_vorp(df, standard_roster_spec, 12)
        valued = compute_salary_values(
            with_vorp, standard_roster_spec,
            num_teams=12, salary_cap=200, min_bid=1,
        )
        assert (valued["salary_value"] == 1.0).all()


# --------------------------------------------------------------------- #
# Max bid
# --------------------------------------------------------------------- #


class TestMaxBid:
    def test_full_budget_full_roster(self):
        """$200 cap, 16 slots, $1 min bid: max bid = $200 - 15 = $185."""
        assert max_bid(200, 16) == 185

    def test_last_slot_uses_full_remaining_budget(self):
        """With one slot left, max bid is the entire remaining budget --
        no reserve needed for future picks."""
        assert max_bid(47, 1) == 47

    def test_zero_open_slots_returns_zero(self):
        """A full roster can't bid on anyone."""
        assert max_bid(50, 0) == 0

    def test_under_water_budget_returns_zero(self):
        """If the budget can't even cover min_bid for every remaining
        slot, the function caps at 0 rather than going negative."""
        assert max_bid(5, 10) == 0

    def test_custom_min_bid(self):
        """A $2 minimum reserves twice as much per remaining slot."""
        assert max_bid(200, 16, min_bid=2) == 200 - 15 * 2

    def test_exact_reserve_leaves_one_min_bid(self):
        """Edge case: budget equals exactly what's needed to bid min on
        each slot. Max bid is min_bid (we can bid the minimum on this
        slot and still cover the rest)."""
        assert max_bid(16, 16, min_bid=1) == 1


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

    def test_max_per_tier_splits_giant_blob(self):
        """Regression for the WR catchall case using the actual
        user-reported rates: top has clean breaks, then a 20-player
        descent with subtle but real seams. max_per_tier should split
        the blob at its biggest internal gap rather than leaving 20
        players in a single unreadable tier."""
        rates = [12.521, 11.264, 11.129, 10.628, 10.547, 10.142,
                 9.980, 9.748, 9.487, 9.482, 9.471, 9.469,
                 9.140, 9.054, 8.772, 8.719, 8.656, 8.629,
                 8.607, 8.516, 8.422, 8.307, 8.219, 8.027]
        rows = [_make_projection(f"WR{i:02d}", "WR", r)
                for i, r in enumerate(rates)]
        df = pd.DataFrame(rows)

        no_cap = assign_tiers(df, positions=["WR"], top_n=24,
                              max_per_tier=999, min_gap_z=1.0)
        capped = assign_tiers(df, positions=["WR"], top_n=24,
                              max_per_tier=10, min_gap_z=1.0)

        # Without the cap, one tier swallows most of the position.
        assert no_cap["tier"].value_counts().max() >= 18
        # With the cap, that same tier gets split at its biggest gap.
        assert capped["tier"].value_counts().max() < no_cap["tier"].value_counts().max()
        # And the biggest internal gap in the blob (London->Rice at
        # 9.469 -> 9.140, a 0.33 jump) should land on a tier boundary.
        london_tier = capped.loc[capped["name"] == "WR11", "tier"].iloc[0]
        rice_tier = capped.loc[capped["name"] == "WR12", "tier"].iloc[0]
        assert rice_tier > london_tier

    def test_max_per_tier_skips_uniform_gap_groups(self):
        """Safety rail: a tier whose players are uniformly spaced
        shouldn't fragment into singletons just because it's larger
        than max_per_tier."""
        rows = []
        # One elite at the top (forces tier 1), then 20 perfectly
        # evenly-spaced followers that should land in one tier despite
        # exceeding max_per_tier -- there's no "biggest gap" to split on.
        rows.append(_make_projection("Elite", "RB", 25.0))
        for i in range(20):
            rows.append(_make_projection(f"Even{i:02d}", "RB", 15.0 - i * 0.2))
        df = pd.DataFrame(rows)
        out = assign_tiers(df, positions=["RB"], top_n=21, max_per_tier=8)
        even_tiers = out.loc[out["name"].str.startswith("Even"), "tier"]
        # The 20 evenly-spaced players collapse into one tier despite
        # being more numerous than max_per_tier.
        assert even_tiers.nunique() == 1


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

    def test_uses_vorp_rank_when_present(
        self, small_pool, standard_roster_spec,
    ):
        """When VORP is on the input, adp_value uses vorp_rank rather
        than proj_rank. Critical for cross-position fairness: high
        absolute-points QBs shouldn't dominate the value list just
        because passing accumulates fast."""
        with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
        adp_df = pd.DataFrame({
            "name":     ["RB00"],
            "position": ["RB"],
            "adp":      [10.0],
        })
        merged = merge_adp(with_vorp, adp_df, num_teams=12)
        rb00 = merged.loc[merged["name"] == "RB00"].iloc[0]
        assert "vorp_rank" in merged.columns
        # adp_value must derive from vorp_rank, not proj_rank. RB00 is
        # the top player by points_rate (proj_rank=1) but several WRs
        # outrank him by VORP because the WR replacement level sits
        # lower in this roster -- so vorp_rank > 1, and adp_value
        # accordingly differs from adp - proj_rank.
        assert rb00["proj_rank"] == 1
        assert rb00["vorp_rank"] > 1
        assert rb00["adp_value"] == pytest.approx(10.0 - rb00["vorp_rank"])
        assert rb00["adp_value"] != pytest.approx(10.0 - rb00["proj_rank"])

    def test_proj_rank_used_when_vorp_absent(self, small_pool):
        """Without VORP on the input, adp_value falls back to using
        proj_rank so the function stays usable on bare projections."""
        adp_df = pd.DataFrame({
            "name": ["RB00"], "position": ["RB"], "adp": [10.0],
        })
        merged = merge_adp(small_pool, adp_df, num_teams=12)
        assert "vorp_rank" not in merged.columns
        rb00 = merged.loc[merged["name"] == "RB00"].iloc[0]
        assert rb00["adp_value"] == pytest.approx(10.0 - rb00["proj_rank"])


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
                       num_teams=12, my_pick=6, noise_slope=0.1)
        result = md.simulate(seed=42)
        # 1+2+3+1+1+1+1 starters + 6 bench = 16 per team * 12 teams
        assert len(result) == 16 * 12

    def test_no_player_drafted_twice(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=1, noise_slope=0.1)
        result = md.simulate(seed=7)
        assert result["name"].is_unique

    def test_snake_order_reverses_each_round(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=1, snake=True, noise_slope=0.1)
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
                       num_teams=12, my_pick=1, noise_slope=0.05,
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
                       num_teams=12, my_pick=12, noise_slope=0.02, noise_floor=0.3,
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
                       num_teams=12, my_pick=6, noise_slope=0.1)
        a = md.simulate_many(3, seed=99)
        b = md.simulate_many(3, seed=99)
        pd.testing.assert_frame_equal(a, b)
        assert a["sim"].nunique() == 3

    def test_availability_recovers_taken_vs_missing(
        self, draft_ready_pool, standard_roster_spec,
    ):
        md = MockDraft(draft_ready_pool, standard_roster_spec,
                       num_teams=12, my_pick=6, noise_slope=0.1)
        runs = md.simulate_many(5, seed=2)
        avail = md.availability(runs, pick_number=12)
        # Player taken in every sim before pick 12 should show 0%
        # availability; player whose avg pick is >> 12 should show high.
        always_taken_early = avail[avail["avg_pick_taken"] < 5]
        assert (always_taken_early["available_pct"] < 0.2).all()
        late = avail[avail["avg_pick_taken"] > 100]
        assert (late["available_pct"] > 0.8).all()


# --------------------------------------------------------------------- #
# Salary cap mock auction simulator
# --------------------------------------------------------------------- #


@pytest.fixture
def salary_ready_pool(small_pool, standard_roster_spec) -> pd.DataFrame:
    """Pool with VORP + salary_value attached -- the input contract
    for MockSalaryCapDraft."""
    with_vorp = compute_vorp(small_pool, standard_roster_spec, 12)
    return compute_salary_values(
        with_vorp, standard_roster_spec, num_teams=12, salary_cap=200,
    )


class TestMockSalaryCapDraft:
    def test_missing_columns_raises(self, small_pool, standard_roster_spec):
        with pytest.raises(ValueError, match="missing required columns"):
            MockSalaryCapDraft(small_pool, standard_roster_spec, num_teams=12)

    def test_invalid_my_team_idx_raises(
        self, salary_ready_pool, standard_roster_spec,
    ):
        with pytest.raises(ValueError, match="my_team_idx"):
            MockSalaryCapDraft(
                salary_ready_pool, standard_roster_spec,
                num_teams=12, my_team_idx=99,
            )

    def test_unknown_strategy_raises(
        self, salary_ready_pool, standard_roster_spec,
    ):
        with pytest.raises(ValueError, match="my_strategy"):
            MockSalaryCapDraft(
                salary_ready_pool, standard_roster_spec,
                num_teams=12, my_strategy="wild",
            )

    def test_fills_every_roster(
        self, salary_ready_pool, standard_roster_spec,
    ):
        """A successful simulation drafts every team to a full roster
        -- 16 picks per team * 12 teams = 192 picks total."""
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
        )
        result = sim.simulate(seed=7)
        assert len(result) == 16 * 12
        assert (result["team"].value_counts() == 16).all()

    def test_no_player_drafted_twice(
        self, salary_ready_pool, standard_roster_spec,
    ):
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
        )
        result = sim.simulate(seed=3)
        assert result["name"].is_unique

    def test_no_team_exceeds_cap(
        self, salary_ready_pool, standard_roster_spec,
    ):
        """The Vickrey resolution + max_bid clipping must keep every
        team's total spend at or below the cap."""
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
            salary_cap=200,
        )
        result = sim.simulate(seed=11)
        per_team = result.groupby("team")["winning_bid"].sum()
        assert (per_team <= 200).all()

    def test_every_bid_at_least_min(
        self, salary_ready_pool, standard_roster_spec,
    ):
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
            min_bid=1,
        )
        result = sim.simulate(seed=5)
        assert (result["winning_bid"] >= 1).all()

    def test_reproducible_with_seed(
        self, salary_ready_pool, standard_roster_spec,
    ):
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
        )
        a = sim.simulate(seed=42)
        b = sim.simulate(seed=42)
        pd.testing.assert_frame_equal(a, b)

    def test_aggressive_strategy_spends_more_than_conservative(
        self, salary_ready_pool, standard_roster_spec,
    ):
        """Across many sims the user's spend should track their
        strategy multiplier -- aggressive bidders end up paying more
        than conservative bidders for the same role players."""
        agg = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
            my_team_idx=1, my_strategy="aggressive",
        ).simulate_many(8, seed=1)
        con = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
            my_team_idx=1, my_strategy="conservative",
        ).simulate_many(8, seed=1)
        agg_spend = agg.loc[agg["is_user"]].groupby("sim")["winning_bid"].sum().mean()
        con_spend = con.loc[con["is_user"]].groupby("sim")["winning_bid"].sum().mean()
        assert agg_spend > con_spend

    def test_simulate_many_seeds_are_reproducible(
        self, salary_ready_pool, standard_roster_spec,
    ):
        sim = MockSalaryCapDraft(
            salary_ready_pool, standard_roster_spec, num_teams=12,
        )
        a = sim.simulate_many(3, seed=99)
        b = sim.simulate_many(3, seed=99)
        pd.testing.assert_frame_equal(a, b)
        assert a["sim"].nunique() == 3


# --------------------------------------------------------------------- #
# Backtest harness
# --------------------------------------------------------------------- #


class TestBacktestSalaryValues:
    def test_per_team_totals(self):
        history = pd.DataFrame([
            {"name": "A", "fantasy_team": "T1", "winning_bid": 50},
            {"name": "B", "fantasy_team": "T1", "winning_bid": 30},
            {"name": "C", "fantasy_team": "T2", "winning_bid": 40},
        ])
        values = pd.DataFrame([
            {"name": "A", "salary_value": 45},
            {"name": "B", "salary_value": 35},
            {"name": "C", "salary_value": 30},
        ])
        out = backtest_salary_values(history, values)
        t1 = out[out["team"] == "T1"].iloc[0]
        assert t1["total_spent"] == 80
        assert t1["total_value"] == 80
        # Surplus = total_value - total_spent; T1 broke even.
        assert t1["surplus"] == 0
        t2 = out[out["team"] == "T2"].iloc[0]
        # T2 paid $40 for a $30-valued player; surplus = -10.
        assert t2["surplus"] == -10

    def test_sorted_by_surplus_desc(self):
        """The team that got the best deals (highest surplus) should
        sit at the top."""
        history = pd.DataFrame([
            {"name": "A", "fantasy_team": "Bargain", "winning_bid": 10},
            {"name": "B", "fantasy_team": "Overpay", "winning_bid": 80},
        ])
        values = pd.DataFrame([
            {"name": "A", "salary_value": 50},
            {"name": "B", "salary_value": 40},
        ])
        out = backtest_salary_values(history, values)
        assert out.iloc[0]["team"] == "Bargain"
        assert out.iloc[-1]["team"] == "Overpay"

    def test_overpay_pct_signals_systematic_bias(self):
        """A team that overpays on every pick by ~50% should have
        avg_overpay_pct ~ 0.5."""
        history = pd.DataFrame([
            {"name": n, "fantasy_team": "Big Spender", "winning_bid": 30}
            for n in ["A", "B", "C"]
        ])
        values = pd.DataFrame([
            {"name": "A", "salary_value": 20},
            {"name": "B", "salary_value": 20},
            {"name": "C", "salary_value": 20},
        ])
        out = backtest_salary_values(history, values)
        assert out.iloc[0]["avg_overpay_pct"] == pytest.approx(0.5)

    def test_missing_value_falls_back_to_median(self):
        """Players the valuation engine didn't price get the median
        value of the cohort, so a single coverage gap doesn't
        artificially inflate surplus."""
        history = pd.DataFrame([
            {"name": "A", "fantasy_team": "T1", "winning_bid": 50},
            {"name": "Mystery", "fantasy_team": "T1", "winning_bid": 20},
        ])
        values = pd.DataFrame([{"name": "A", "salary_value": 40}])
        out = backtest_salary_values(history, values)
        t1 = out.iloc[0]
        # Median of {40} = 40, so Mystery gets value 40.
        assert t1["total_value"] == 80
        assert t1["total_spent"] == 70

    def test_missing_columns_raises(self):
        with pytest.raises(ValueError, match="name"):
            backtest_salary_values(
                pd.DataFrame({"fantasy_team": ["T1"], "winning_bid": [10]}),
                pd.DataFrame({"name": ["A"], "salary_value": [10]}),
            )
        with pytest.raises(ValueError, match="winning_bid"):
            backtest_salary_values(
                pd.DataFrame({"name": ["A"], "fantasy_team": ["T1"]}),
                pd.DataFrame({"name": ["A"], "salary_value": [10]}),
            )

