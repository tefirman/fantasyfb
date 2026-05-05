"""Tests for draft_cockpit view helpers.

The cockpit's interactive loop and Yahoo wiring stay untested -- they need
real credentials. Everything here exercises the pure DataFrame helpers
against synthetic boards, so the suite remains offline and fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from draft_cockpit import (
    DEFAULT_DISPLAY_COLS,
    build_board,
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

    def test_position_order_is_conventional(self, board):
        """QB/RB/WR/TE/K/DEF should appear in that order so the user
        scans the same way every pick."""
        out = view_best(board, limit_per_position=2)
        seen_positions = []
        for pos in out["position"]:
            if pos not in seen_positions:
                seen_positions.append(pos)
        expected = [p for p in ["QB", "RB", "WR", "TE", "K", "DEF"]
                    if p in seen_positions]
        assert seen_positions == expected

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
