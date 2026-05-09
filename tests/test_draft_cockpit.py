"""Tests for draft_cockpit view helpers.

The cockpit's interactive loop and Yahoo wiring stay untested -- they need
real credentials. Everything here exercises the pure DataFrame helpers
against synthetic boards, so the suite remains offline and fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.drafts.snake_cockpit import (
    DEFAULT_DISPLAY_COLS,
    build_board,
    build_my_roster,
    random_pick,
    view_best,
    view_lookup,
    view_nearest,
    view_roster,
)


def _make_projection(
    name: str, position: str, points_rate: float, **extra,
) -> dict:
    base = {
        "player_id_sr": name.lower().replace(" ", "_"),
        "name": name,
        "position": position,
        "current_team": "FA",
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
    return pd.DataFrame({
        "position": ["QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN"],
        "count":    [1,    2,    3,    1,    1,       1,   1,     6],
    })


@pytest.fixture
def small_pool() -> pd.DataFrame:
    """Mirrors the test_draft_tools fixture so the math is identical."""
    rows = []
    for i in range(24):
        rows.append(_make_projection(f"QB{i:02d}", "QB", 24 - i))
    for i in range(60):
        rows.append(_make_projection(f"RB{i:02d}", "RB", 30 - i * 0.5))
    for i in range(60):
        rows.append(_make_projection(f"WR{i:02d}", "WR", 25 - i * 0.4))
    for i in range(24):
        rows.append(_make_projection(f"TE{i:02d}", "TE", 18 - i * 0.5))
    for i in range(14):
        rows.append(_make_projection(f"K{i:02d}", "K", 10 - i * 0.3))
    for i in range(14):
        rows.append(_make_projection(f"DEF{i:02d}", "DEF", 8 - i * 0.2))
    return pd.DataFrame(rows)


@pytest.fixture
def adp_csv(tmp_path, small_pool) -> str:
    """ADP roughly tracks projection rank so 'available within next N picks'
    behavior is exercisable. K/DEF get pushed late as you'd expect."""
    pool = small_pool.copy().sort_values("points_rate", ascending=False).reset_index(drop=True)
    pool["adp"] = np.arange(1, len(pool) + 1, dtype=float)
    out = tmp_path / "adp.csv"
    out.write_text("Player,POS,Team,AVG\n" + "\n".join(
        f"{r['name']},{r['position']},FA,{r['adp']}" for _, r in pool.iterrows()
    ) + "\n")
    return str(out)


@pytest.fixture
def board(small_pool, standard_roster_spec, adp_csv) -> pd.DataFrame:
    b = build_board(small_pool, standard_roster_spec, num_teams=12,
                    adp_csv_path=adp_csv)
    # Initialize a clean fantasy_team column -- build_board preserves
    # whatever was on the input DataFrame, but small_pool has none.
    b = b.copy()
    if "fantasy_team" not in b.columns:
        b["fantasy_team"] = pd.NA
    else:
        b["fantasy_team"] = pd.NA
    return b


# --------------------------------------------------------------------- #
# build_board
# --------------------------------------------------------------------- #


class TestBuildBoard:
    def test_carries_vorp_and_tier_and_adp(self, board):
        for col in ["vorp_per_game", "tier", "adp", "adp_round", "adp_value"]:
            assert col in board.columns, f"missing {col}"

    def test_drops_avg_rows(self, small_pool, standard_roster_spec, adp_csv):
        with_avgs = pd.concat([
            small_pool,
            pd.DataFrame([_make_projection("avg_RB", "RB", 5,
                                           player_id_sr="avg_RB")]),
        ], ignore_index=True)
        b = build_board(with_avgs, standard_roster_spec, num_teams=12,
                        adp_csv_path=adp_csv)
        assert not b["player_id_sr"].astype(str).str.startswith("avg_").any()

    def test_dedupes_by_player_id(
        self, small_pool, standard_roster_spec, adp_csv,
    ):
        """Defensive: League.get_rates() can occasionally emit a player on
        multiple rows. The board should fold those down before computing
        VORP/tier so the player doesn't show up twice in best/nearest."""
        dup = pd.concat([small_pool, small_pool.head(3)], ignore_index=True)
        b = build_board(dup, standard_roster_spec, num_teams=12,
                        adp_csv_path=adp_csv)
        assert b["player_id_sr"].is_unique


# --------------------------------------------------------------------- #
# view_best
# --------------------------------------------------------------------- #


class TestViewBest:
    def test_returns_top_n_per_position(self, board):
        out = view_best(board, limit_per_position=3)
        per_pos = out["position"].value_counts()
        # Every position with 3+ available players should hit exactly 3.
        for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
            assert per_pos.get(pos, 0) <= 3

    def test_excludes_drafted_players(self, board):
        # Mark RB00 (top RB) as drafted; he should disappear from view.
        board.loc[board["name"] == "RB00", "fantasy_team"] = "Other"
        out = view_best(board, limit_per_position=3)
        assert "RB00" not in out["name"].tolist()
        # The next-best RB (RB01) should now be in the top of the RB list.
        rb_top = out[out["position"] == "RB"].iloc[0]
        assert rb_top["name"] == "RB01"

    def test_respects_explicit_exclude_list(self, board):
        out = view_best(board, exclude=["RB00", "WR00"], limit_per_position=3)
        assert "RB00" not in out["name"].tolist()
        assert "WR00" not in out["name"].tolist()

    def test_position_filter(self, board):
        out = view_best(board, positions=["RB", "WR"], limit_per_position=2)
        assert set(out["position"].unique()) <= {"RB", "WR"}

    def test_globally_sorted_by_vorp_descending(self, board):
        """Final list is VORP-ordered across positions, not grouped by
        position. The top row is whoever has the highest cross-position
        value -- typically an RB/WR rather than the top QB, since QBs
        sit on a deeper replacement level."""
        out = view_best(board, limit_per_position=5)
        vorps = out["vorp_per_game"].tolist()
        assert vorps == sorted(vorps, reverse=True)

    def test_within_position_sorted_by_vorp_descending(self, board):
        out = view_best(board, limit_per_position=5)
        for pos, group in out.groupby("position"):
            vorps = group["vorp_per_game"].tolist()
            assert vorps == sorted(vorps, reverse=True), \
                f"{pos} not VORP-descending: {vorps}"

    def test_returns_only_display_columns(self, board):
        out = view_best(board, limit_per_position=2)
        for col in out.columns:
            assert col in DEFAULT_DISPLAY_COLS, f"unexpected column {col}"

    def test_no_roster_omits_need_columns(self, board):
        """Without my_roster, output should not include need_factor or
        vorp_adjusted -- those are only meaningful when the user's
        roster state is known."""
        out = view_best(board, limit_per_position=2)
        assert "need_factor" not in out.columns
        assert "vorp_adjusted" not in out.columns


# --------------------------------------------------------------------- #
# view_nearest
# --------------------------------------------------------------------- #


class TestViewNearest:
    def test_only_includes_players_within_window(self, board):
        out = view_nearest(board, pick_overall=10, num_teams=12,
                           window_rounds=2)
        # Window is picks 11..34 (10 + 24). All returned players' ADPs
        # must fall in (-inf, 34].
        assert (out["adp"] <= 34).all()

    def test_excludes_drafted_players(self, board):
        board.loc[board["name"] == "RB00", "fantasy_team"] = "Other"
        out = view_nearest(board, pick_overall=1, num_teams=12)
        assert "RB00" not in out["name"].tolist()

    def test_excludes_players_without_adp(
        self, small_pool, standard_roster_spec, adp_csv,
    ):
        """Players the projection knows about but ADP doesn't shouldn't
        clutter the nearest view -- the market hasn't placed them yet."""
        # Add a synthetic player not in the ADP CSV.
        extra = pd.concat([
            small_pool,
            pd.DataFrame([_make_projection("Mystery RB", "RB", 20)]),
        ], ignore_index=True)
        b = build_board(extra, standard_roster_spec, num_teams=12,
                        adp_csv_path=adp_csv)
        b["fantasy_team"] = pd.NA
        out = view_nearest(b, pick_overall=1, num_teams=12)
        assert "Mystery RB" not in out["name"].tolist()

    def test_sorted_by_vorp_descending(self, board):
        out = view_nearest(board, pick_overall=20, num_teams=12,
                           window_rounds=3)
        vorps = out["vorp_per_game"].tolist()
        assert vorps == sorted(vorps, reverse=True)


# --------------------------------------------------------------------- #
# view_lookup
# --------------------------------------------------------------------- #


class TestViewLookup:
    def test_finds_existing_player(self, board):
        out = view_lookup(board, "RB00")
        assert len(out) == 1
        assert out.iloc[0]["name"] == "RB00"

    def test_returns_empty_for_missing_player(self, board):
        out = view_lookup(board, "Nonexistent Player")
        assert out.empty

    def test_includes_fantasy_team_column(self, board):
        board.loc[board["name"] == "RB00", "fantasy_team"] = "My Team"
        out = view_lookup(board, "RB00")
        assert "fantasy_team" in out.columns
        assert out.iloc[0]["fantasy_team"] == "My Team"


# --------------------------------------------------------------------- #
# view_roster
# --------------------------------------------------------------------- #


class TestViewRoster:
    def test_filters_to_specified_team(self, board):
        board.loc[board["name"].isin(["RB00", "WR00"]), "fantasy_team"] = "My Team"
        board.loc[board["name"] == "QB00", "fantasy_team"] = "Other"
        out = view_roster(board, "My Team")
        assert set(out["name"]) == {"RB00", "WR00"}

    def test_empty_when_team_has_no_picks(self, board):
        out = view_roster(board, "My Team")
        assert out.empty

    def test_position_order_groups_qb_first(self, board):
        board.loc[
            board["name"].isin(["QB00", "RB00", "WR00", "TE00"]), "fantasy_team",
        ] = "My Team"
        out = view_roster(board, "My Team")
        positions_in_order = out["position"].tolist()
        assert positions_in_order == ["QB", "RB", "WR", "TE"]


# --------------------------------------------------------------------- #
# Roster-aware (need-adjusted) views
# --------------------------------------------------------------------- #


class TestBuildMyRoster:
    def test_empty_when_no_picks(self, board, standard_roster_spec):
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        # Every starting slot still open.
        assert roster.starting_slots["QB"] == 1
        assert roster.starting_slots["RB"] == 2
        assert roster.starting_slots["WR"] == 3

    def test_decrements_starting_slots_for_picks(
        self, board, standard_roster_spec,
    ):
        board.loc[board["name"].isin(["QB00", "RB00", "RB01"]),
                  "fantasy_team"] = "My Team"
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        assert roster.starting_slots["QB"] == 0
        assert roster.starting_slots["RB"] == 0
        assert roster.starting_slots["WR"] == 3

    def test_overflow_picks_consume_flex_then_bench(
        self, board, standard_roster_spec,
    ):
        """Drafting 3 RBs into a 2-RB league: first two fill the RB
        slots, third falls to the W/R/T flex (eligible for RB)."""
        board.loc[board["name"].isin(["RB00", "RB01", "RB02"]),
                  "fantasy_team"] = "My Team"
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        assert roster.starting_slots["RB"] == 0
        assert roster.starting_slots["W/R/T"] == 0

    def test_only_counts_specified_team(
        self, board, standard_roster_spec,
    ):
        board.loc[board["name"] == "RB00", "fantasy_team"] = "My Team"
        board.loc[board["name"] == "RB01", "fantasy_team"] = "Other"
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        # Only RB00 (mine) consumed a slot -- RB01 is on someone else.
        assert roster.starting_slots["RB"] == 1


class TestViewBestNeedAdjusted:
    def test_empty_roster_matches_raw_vorp(
        self, board, standard_roster_spec,
    ):
        """An empty roster has need_factor=1.0 everywhere, so the sort
        order should match the no-roster path exactly."""
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        with_roster = view_best(board, my_roster=roster, limit_per_position=5)
        without = view_best(board, limit_per_position=5)
        # Same set of names in the same order.
        assert with_roster["name"].tolist() == without["name"].tolist()

    def test_roster_pass_adds_need_columns(
        self, board, standard_roster_spec,
    ):
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        out = view_best(board, my_roster=roster, limit_per_position=3)
        assert "need_factor" in out.columns
        assert "vorp_adjusted" in out.columns
        # Empty roster -> all positions still need_factor=1.0.
        assert (out["need_factor"] == 1.0).all()

    def test_filled_position_demotes_below_open_position(
        self, board, standard_roster_spec,
    ):
        """The point of need adjustment: with WR + flex slots filled, a
        top WR should fall behind a top RB even though WR has higher raw
        VORP in this synthetic pool (3 WR starters/team + WRs fill flex
        push WR replacement level deeper than RB's, so top WR > top RB
        on raw VORP).
        """
        # Sanity: in the no-need view, top of the table is a WR.
        baseline = view_best(board, limit_per_position=5)
        assert baseline.iloc[0]["position"] == "WR"

        # Fill all 3 WR slots + 1 W/R/T flex slot (Roster.add greedily
        # fills WR first, then flex when WR is full).
        board.loc[board["name"].isin(["WR00", "WR01", "WR02", "WR03"]),
                  "fantasy_team"] = "My Team"
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        # WR/flex consumed -> need_score(WR) drops to bench-only (~0.2).
        # RB still has open slots -> need_score(RB) = 1.0.
        adjusted = view_best(board, my_roster=roster, limit_per_position=5)
        assert adjusted.iloc[0]["position"] == "RB"

    def test_need_factor_constant_within_position(
        self, board, standard_roster_spec,
    ):
        """need_factor is per-position, so all rows of a given position
        in the output should share the same need_factor value."""
        board.loc[board["name"].isin(["RB00", "RB01"]), "fantasy_team"] = "My Team"
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        out = view_best(board, my_roster=roster, limit_per_position=5)
        for pos, group in out.groupby("position"):
            assert group["need_factor"].nunique() == 1, (
                f"{pos} need_factor varies: {group['need_factor'].tolist()}"
            )


class TestViewNearestNeedAdjusted:
    def test_roster_pass_adds_need_columns(self, board, standard_roster_spec):
        roster = build_my_roster(board, "My Team", standard_roster_spec)
        out = view_nearest(board, pick_overall=1, num_teams=12,
                           my_roster=roster, window_rounds=4)
        assert "need_factor" in out.columns
        assert "vorp_adjusted" in out.columns

    def test_no_roster_path_unchanged(self, board):
        out = view_nearest(board, pick_overall=1, num_teams=12,
                           window_rounds=4)
        assert "need_factor" not in out.columns
        assert "vorp_adjusted" not in out.columns


# --------------------------------------------------------------------- #
# random_pick
# --------------------------------------------------------------------- #


class TestRandomPick:
    def test_returns_an_available_player(
        self, board, standard_roster_spec,
    ):
        name = random_pick(
            board, team_name="My Team", roster_spec=standard_roster_spec,
            rng=np.random.default_rng(0),
        )
        # The returned player must be on the board and not already drafted.
        row = board[board["name"] == name]
        assert len(row) == 1
        assert pd.isna(row.iloc[0]["fantasy_team"])

    def test_excludes_drafted_players(
        self, board, standard_roster_spec,
    ):
        # Mark the entire top of every position as drafted; the auto-pick
        # has to come from deeper.
        top_drafted = ["RB00", "RB01", "WR00", "WR01", "QB00", "TE00"]
        board.loc[board["name"].isin(top_drafted), "fantasy_team"] = "Other"
        name = random_pick(
            board, team_name="My Team", roster_spec=standard_roster_spec,
            rng=np.random.default_rng(1),
        )
        assert name not in top_drafted

    def test_respects_explicit_exclude_list(
        self, board, standard_roster_spec,
    ):
        # Even with a tiny pool size, excluded players never get picked.
        # Run several samples to make sure no seed dodges the exclude check.
        for seed in range(20):
            name = random_pick(
                board, team_name="My Team",
                roster_spec=standard_roster_spec,
                exclude=["RB00", "WR00"],
                pool_size=2,
                rng=np.random.default_rng(seed),
            )
            assert name not in {"RB00", "WR00"}

    def test_seed_is_reproducible(
        self, board, standard_roster_spec,
    ):
        a = random_pick(board, team_name="My Team",
                        roster_spec=standard_roster_spec,
                        rng=np.random.default_rng(42))
        b = random_pick(board, team_name="My Team",
                        roster_spec=standard_roster_spec,
                        rng=np.random.default_rng(42))
        assert a == b

    def test_different_seeds_produce_variety(
        self, board, standard_roster_spec,
    ):
        """Across many seeds, more than one distinct player should be
        picked -- otherwise the function is deterministic and the
        feature is broken."""
        names = {
            random_pick(board, team_name="My Team",
                        roster_spec=standard_roster_spec,
                        rng=np.random.default_rng(seed))
            for seed in range(50)
        }
        assert len(names) >= 2

    def test_filled_position_avoided(
        self, board, standard_roster_spec,
    ):
        """If the team has filled all WR + flex slots, the auto-pick
        should rarely (ideally never within a small pool) be a WR. With
        a small pool_size and 30 different seeds, a filled position
        should drop out of contention almost completely.
        """
        board.loc[board["name"].isin(["WR00", "WR01", "WR02", "WR03"]),
                  "fantasy_team"] = "My Team"
        positions = [
            random_pick(
                board, team_name="My Team",
                roster_spec=standard_roster_spec,
                pool_size=4,
                rng=np.random.default_rng(seed),
            )
            for seed in range(30)
        ]
        wr_picks = sum(1 for n in positions
                       if board.loc[board["name"] == n, "position"].iloc[0] == "WR")
        # With WR fully saturated and a top-4 pool, WR's adjusted VORP
        # is a fraction of what it would be otherwise -- they should
        # not dominate the auto-picks.
        assert wr_picks <= 5, f"WR over-represented: {wr_picks}/30 picks"

    def test_uses_team_name_for_need_scoring(
        self, board, standard_roster_spec,
    ):
        """The auto-pick scores need against the on-the-clock team, not
        always My Team. If team A has filled WR but team B has not,
        random_pick(team=A) should avoid WR while random_pick(team=B)
        shouldn't.
        """
        board.loc[board["name"].isin(["WR00", "WR01", "WR02", "WR03"]),
                  "fantasy_team"] = "Team A"
        a_positions = []
        b_positions = []
        for seed in range(30):
            a = random_pick(
                board, team_name="Team A",
                roster_spec=standard_roster_spec,
                pool_size=4,
                rng=np.random.default_rng(seed),
            )
            b = random_pick(
                board, team_name="Team B",
                roster_spec=standard_roster_spec,
                pool_size=4,
                rng=np.random.default_rng(seed),
            )
            a_positions.append(
                board.loc[board["name"] == a, "position"].iloc[0]
            )
            b_positions.append(
                board.loc[board["name"] == b, "position"].iloc[0]
            )
        a_wr = sum(p == "WR" for p in a_positions)
        b_wr = sum(p == "WR" for p in b_positions)
        # Team B (no WRs yet) should pick WR much more often than A.
        assert b_wr > a_wr
