"""Tests for salary_cap_cockpit view helpers.

Mirrors test_draft_cockpit.py for the salary cap side. The interactive
loop / Yahoo wiring stays untested; everything here is pure DataFrame
math against synthetic boards so the suite remains offline and fast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.drafts.salary_cap_cockpit import (
    build_board,
    compute_inflation,
    simulate_nomination,
    view_best,
    view_budget_status,
    view_lookup,
    view_nominate,
    view_roster,
    view_what_if,
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
def board(small_pool, standard_roster_spec) -> pd.DataFrame:
    b = build_board(small_pool, standard_roster_spec,
                    num_teams=12, salary_cap=200)
    b = b.copy()
    b["fantasy_team"] = pd.NA
    return b


# --------------------------------------------------------------------- #
# build_board
# --------------------------------------------------------------------- #


class TestBuildBoard:
    def test_drops_synthetic_avg_rows(self, standard_roster_spec):
        """avg_* synthetic rows the League injects for sim purposes
        should never appear on a draft board."""
        rows = [_make_projection(f"RB{i:02d}", "RB", 20 - i * 0.5)
                for i in range(20)]
        rows.append(_make_projection("avg", "RB", 100,
                                     player_id_sr="avg_rb_starter"))
        df = pd.DataFrame(rows)
        board = build_board(df, standard_roster_spec,
                            num_teams=12, salary_cap=200)
        assert not board["player_id_sr"].astype(str).str.startswith("avg_").any()

    def test_has_salary_and_bid_columns(self, board):
        """The two columns that distinguish a salary cap board from a
        snake board must be present and shaped correctly."""
        assert "salary_value" in board.columns
        assert "winning_bid" in board.columns
        assert board["winning_bid"].isna().all()
        assert (board["salary_value"] >= 1.0).all()

    def test_dedupes_by_player_id(self, standard_roster_spec):
        rows = [_make_projection("RB00", "RB", 20),
                _make_projection("RB00", "RB", 20)]  # duplicate
        for i in range(1, 50):
            rows.append(_make_projection(f"RB{i:02d}", "RB", 20 - i * 0.5))
        df = pd.DataFrame(rows)
        board = build_board(df, standard_roster_spec,
                            num_teams=12, salary_cap=200)
        assert (board["player_id_sr"] == "rb00").sum() == 1


# --------------------------------------------------------------------- #
# Inflation
# --------------------------------------------------------------------- #


class TestInflation:
    def test_starts_at_one(self, board):
        """No picks, no spending: inflation = 1.0 by definition."""
        assert compute_inflation(board, salary_cap=200, num_teams=12) == pytest.approx(
            1.0, abs=0.01,
        )

    def test_underspending_inflates(self, board):
        """If teams have been buying cheap, remaining players cost more."""
        b = board.copy()
        # Three picks for $1 each -- way below their salary_value.
        for i, name in enumerate(["RB00", "RB01", "WR00"]):
            mask = b["name"] == name
            b.loc[mask, "fantasy_team"] = f"team{i}"
            b.loc[mask, "winning_bid"] = 1
        assert compute_inflation(b, salary_cap=200, num_teams=12) > 1.0

    def test_overspending_deflates(self, board):
        """Owners have overpaid early; remaining money won't cover
        every player's listed value."""
        b = board.copy()
        # Top three RBs went for $150 each -- way above their value.
        for i, name in enumerate(["RB00", "RB01", "RB02"]):
            mask = b["name"] == name
            b.loc[mask, "fantasy_team"] = f"team{i}"
            b.loc[mask, "winning_bid"] = 150
        assert compute_inflation(b, salary_cap=200, num_teams=12) < 1.0


# --------------------------------------------------------------------- #
# view_best
# --------------------------------------------------------------------- #


class TestViewBest:
    def test_returns_dollar_columns(self, board, standard_roster_spec):
        out = view_best(
            board, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit_per_position=3,
        )
        for col in ("salary_value", "inflated_value", "max_my_bid"):
            assert col in out.columns

    def test_max_bid_capped_by_remaining_budget(
        self, board, standard_roster_spec,
    ):
        """A user who has already spent down to $50 should never see a
        max_my_bid above $50, even for elite players whose inflated
        value would otherwise be higher."""
        b = board.copy()
        # Spend $150 on a low-value RB (eats most of the budget without
        # using up many slots).
        mask = b["name"] == "RB10"
        b.loc[mask, "fantasy_team"] = "me"
        b.loc[mask, "winning_bid"] = 150
        out = view_best(
            b, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit_per_position=3,
        )
        # 15 slots open, $50 left, $1 min => max bid = $50 - 14 = $36.
        assert (out["max_my_bid"] <= 36).all()

    def test_need_scaling_demotes_filled_positions(
        self, board, standard_roster_spec,
    ):
        """After filling the QB starting slot, a top remaining QB
        should rank below a comparable starting-eligible RB even if
        its raw VORP is similar."""
        b = board.copy()
        # User already drafted the top QB.
        mask = b["name"] == "QB00"
        b.loc[mask, "fantasy_team"] = "me"
        b.loc[mask, "winning_bid"] = 30
        out = view_best(
            b, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit_per_position=10,
        )
        # The user's need_factor for QB should be lower than for RB.
        qb_rows = out[out["position"] == "QB"]
        rb_rows = out[out["position"] == "RB"]
        if not qb_rows.empty and not rb_rows.empty:
            assert qb_rows["need_factor"].iloc[0] < rb_rows["need_factor"].iloc[0]

    def test_excludes_drafted_players(self, board, standard_roster_spec):
        """Drafted players belong to someone, so they shouldn't show
        up in 'best available' targets."""
        b = board.copy()
        mask = b["name"] == "RB00"
        b.loc[mask, "fantasy_team"] = "other_team"
        b.loc[mask, "winning_bid"] = 60
        out = view_best(
            b, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit_per_position=10,
        )
        assert "RB00" not in set(out["name"])

    def test_positions_filter(self, board, standard_roster_spec):
        out = view_best(
            board, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec,
            positions=["RB", "WR"], limit_per_position=5,
        )
        assert set(out["position"]) <= {"RB", "WR"}


# --------------------------------------------------------------------- #
# view_nominate
# --------------------------------------------------------------------- #


class TestViewNominate:
    def test_drain_score_increases_with_value(
        self, board, standard_roster_spec,
    ):
        """A higher-valued player with similar fit should have a
        higher drain score -- they cost opponents more to win."""
        out = view_nominate(
            board, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit=20,
        )
        # Drain scores are sorted descending in the output.
        assert (out["drain_score"].diff().dropna() <= 0).all()

    def test_drain_score_demoted_for_user_needs(
        self, board, standard_roster_spec,
    ):
        """Top RB has high market value but user still needs RBs -- so
        it shouldn't be #1 in the drain list. A top K (user has 1 K
        slot but fills it cheap) makes a better drain target only
        after the user's K slot is filled."""
        b = board.copy()
        # Fill user's K slot so K becomes a pure drain candidate.
        mask = b["name"] == "K00"
        b.loc[mask, "fantasy_team"] = "me"
        b.loc[mask, "winning_bid"] = 1
        out = view_nominate(
            b, my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit=30,
        )
        # User has K filled -> K need_factor should be lower than RB/WR.
        # The drain_score formula multiplies by (1 - need_factor), so an
        # RB the user still needs gets a meaningfully smaller drain_score
        # than its raw value would suggest.
        top_rb = out[out["position"] == "RB"].head(1)
        if not top_rb.empty:
            assert top_rb["need_factor"].iloc[0] > 0.5


# --------------------------------------------------------------------- #
# view_what_if
# --------------------------------------------------------------------- #


class TestViewWhatIf:
    def test_does_not_mutate_input_board(self, board, standard_roster_spec):
        """The hypothetical scenario must operate on a copy."""
        before = board.copy()
        view_what_if(
            board, name="RB00", bid=60, winning_team="opponent",
            my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec,
        )
        pd.testing.assert_frame_equal(board, before)

    def test_drafted_player_disappears_from_targets(
        self, board, standard_roster_spec,
    ):
        """After the scenario, the named player belongs to winning_team
        and shouldn't appear in the user's recommended targets."""
        out = view_what_if(
            board, name="RB00", bid=60, winning_team="opponent",
            my_team="me", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec, limit_per_position=10,
        )
        assert "RB00" not in set(out["name"])

    def test_unknown_player_raises(self, board, standard_roster_spec):
        with pytest.raises(ValueError, match="not on the board"):
            view_what_if(
                board, name="NotARealPlayer", bid=10,
                winning_team="opponent", my_team="me",
                salary_cap=200, num_teams=12,
                roster_spec=standard_roster_spec,
            )


# --------------------------------------------------------------------- #
# view_lookup / view_roster
# --------------------------------------------------------------------- #


class TestViewLookup:
    def test_returns_single_player_row(self, board):
        out = view_lookup(board, "RB00")
        assert len(out) == 1
        assert out.iloc[0]["name"] == "RB00"

    def test_includes_team_and_bid_for_drafted_player(self, board):
        b = board.copy()
        mask = b["name"] == "RB00"
        b.loc[mask, "fantasy_team"] = "opponent"
        b.loc[mask, "winning_bid"] = 55
        out = view_lookup(b, "RB00")
        assert out.iloc[0]["fantasy_team"] == "opponent"
        assert out.iloc[0]["winning_bid"] == 55

    def test_omits_inflated_value_and_max_my_bid_without_context(self, board):
        out = view_lookup(board, "RB00")
        assert "inflated_value" not in out.columns
        assert "max_my_bid" not in out.columns

    def test_computes_max_my_bid_when_context_supplied(
        self, board, standard_roster_spec,
    ):
        out = view_lookup(
            board, "RB00",
            my_team="My Team", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec,
        )
        assert "inflated_value" in out.columns
        assert "max_my_bid" in out.columns
        # Pre-draft, inflation ≈ 1.0 (small drift from avg_ pseudo-rows
        # and rounding in compute_salary_values), so inflated_value
        # should hug salary_value.
        sv = out.iloc[0]["salary_value"]
        iv = out.iloc[0]["inflated_value"]
        assert abs(iv - sv) / sv < 0.01
        # And max_my_bid is clipped by the user's overall cap, which on
        # an empty roster is salary_cap - (roster_size - 1) * min_bid.
        assert out.iloc[0]["max_my_bid"] > 0
        assert out.iloc[0]["max_my_bid"] <= 200

    def test_max_my_bid_is_blank_for_already_drafted_player(
        self, board, standard_roster_spec,
    ):
        b = board.copy()
        mask = b["name"] == "RB00"
        b.loc[mask, "fantasy_team"] = "opponent"
        b.loc[mask, "winning_bid"] = 55
        out = view_lookup(
            b, "RB00",
            my_team="My Team", salary_cap=200, num_teams=12,
            roster_spec=standard_roster_spec,
        )
        assert pd.isna(out.iloc[0]["max_my_bid"])


class TestViewRoster:
    def test_empty_for_unrostered_team(self, board):
        out = view_roster(board, "nobody")
        assert out.empty

    def test_orders_by_position_then_vorp(self, board):
        b = board.copy()
        # Give one team a QB, two RBs, and a WR.
        for name in ["QB00", "RB00", "RB01", "WR00"]:
            mask = b["name"] == name
            b.loc[mask, "fantasy_team"] = "me"
            b.loc[mask, "winning_bid"] = 30
        out = view_roster(b, "me")
        # Conventional order: QB, RB, WR.
        assert out["position"].tolist() == ["QB", "RB", "RB", "WR"]
        # Within RB, higher VORP comes first.
        rbs = out[out["position"] == "RB"]
        assert rbs.iloc[0]["vorp_per_game"] >= rbs.iloc[1]["vorp_per_game"]

    def test_includes_winning_bid(self, board):
        b = board.copy()
        mask = b["name"] == "RB00"
        b.loc[mask, "fantasy_team"] = "me"
        b.loc[mask, "winning_bid"] = 70
        out = view_roster(b, "me")
        assert out.iloc[0]["winning_bid"] == 70


# --------------------------------------------------------------------- #
# view_budget_status
# --------------------------------------------------------------------- #


class TestBudgetStatus:
    def test_pre_draft_full_budgets(self, board, standard_roster_spec):
        """Before any picks every team is at full cap with 0 slots
        filled and the full roster open."""
        out = view_budget_status(
            board, ["team1", "team2", "team3"],
            salary_cap=200, roster_spec=standard_roster_spec,
        )
        assert (out["spent"] == 0).all()
        assert (out["remaining"] == 200).all()
        assert (out["slots_filled"] == 0).all()
        # 1+2+3+1+1+1+1 starters + 6 bench = 16 slots.
        assert (out["slots_open"] == 16).all()

    def test_max_bid_respects_min_reserve(
        self, board, standard_roster_spec,
    ):
        """A fresh team's max bid = 200 - 15 = 185 (with $1 min on the
        other 15 slots)."""
        out = view_budget_status(
            board, ["team1"],
            salary_cap=200, roster_spec=standard_roster_spec,
        )
        assert out.iloc[0]["max_bid"] == 185

    def test_sorted_by_remaining_desc(self, board, standard_roster_spec):
        """The team with the most spending power left should sit at
        the top -- that's typically who you're competing with on the
        next nomination."""
        b = board.copy()
        # team1 spends $100, team2 spends $50, team3 spends nothing.
        b.loc[b["name"] == "RB00", "fantasy_team"] = "team1"
        b.loc[b["name"] == "RB00", "winning_bid"] = 100
        b.loc[b["name"] == "WR00", "fantasy_team"] = "team2"
        b.loc[b["name"] == "WR00", "winning_bid"] = 50
        out = view_budget_status(
            b, ["team1", "team2", "team3"],
            salary_cap=200, roster_spec=standard_roster_spec,
        )
        assert out["team"].tolist() == ["team3", "team2", "team1"]

    def test_reflects_winning_bids(self, board, standard_roster_spec):
        b = board.copy()
        for name, bid in [("RB00", 60), ("WR00", 40)]:
            mask = b["name"] == name
            b.loc[mask, "fantasy_team"] = "team1"
            b.loc[mask, "winning_bid"] = bid
        out = view_budget_status(
            b, ["team1"],
            salary_cap=200, roster_spec=standard_roster_spec,
        )
        row = out.iloc[0]
        assert row["spent"] == 100
        assert row["remaining"] == 100
        assert row["slots_filled"] == 2
        assert row["slots_open"] == 14


# --------------------------------------------------------------------- #
# simulate_nomination
# --------------------------------------------------------------------- #


class TestSimulateNomination:
    def test_returns_valid_tuple(self, board, standard_roster_spec):
        name, winner, bid = simulate_nomination(
            board, team_names=["My Team", "B", "C"],
            salary_cap=200, roster_spec=standard_roster_spec,
            rng=np.random.default_rng(42),
        )
        assert isinstance(name, str)
        assert winner in {"My Team", "B", "C"}
        assert bid >= 1
        # Player must exist on the board.
        assert name in set(board["name"])

    def test_winner_must_have_open_slots(self, board, standard_roster_spec):
        """Even with the user picking aggressively, simulate_nomination
        must not award the player to a team with a full roster."""
        b = board.copy()
        # Pretend team B already filled their 16-slot roster.
        spec = standard_roster_spec
        roster_size = int(spec.loc[spec["position"] != "IR", "count"].sum())
        # Use 16 distinct existing players for the synthetic fills.
        fillers = b[b["fantasy_team"].isna()]["name"].head(roster_size).tolist()
        for n in fillers:
            b.loc[b["name"] == n, "fantasy_team"] = "B"
            b.loc[b["name"] == n, "winning_bid"] = 1
        name, winner, bid = simulate_nomination(
            b, team_names=["My Team", "B"],
            salary_cap=200, roster_spec=standard_roster_spec,
            rng=np.random.default_rng(1),
        )
        assert winner != "B"

    def test_bid_respects_min_and_max(self, board, standard_roster_spec):
        """The winning bid must be at least min_bid and never exceed
        the winner's max_bid (cap minus reserve for open slots)."""
        name, winner, bid = simulate_nomination(
            board, team_names=["My Team", "B", "C"],
            salary_cap=200, roster_spec=standard_roster_spec,
            min_bid=1, rng=np.random.default_rng(99),
        )
        assert bid >= 1
        # Fresh teams (no picks yet): max_bid = 200 - 15*1 = 185.
        assert bid <= 185

    def test_raises_when_all_rosters_full(self, board, standard_roster_spec):
        """If every team's roster is already full, no nomination is
        possible. The CLI catches this to end the auto-pilot loop."""
        b = board.copy()
        spec = standard_roster_spec
        roster_size = int(spec.loc[spec["position"] != "IR", "count"].sum())
        fillers = b[b["fantasy_team"].isna()]["name"].head(
            2 * roster_size,
        ).tolist()
        for i, n in enumerate(fillers):
            b.loc[b["name"] == n, "fantasy_team"] = ["My Team", "B"][i % 2]
            b.loc[b["name"] == n, "winning_bid"] = 1
        with pytest.raises(ValueError, match="full rosters"):
            simulate_nomination(
                b, team_names=["My Team", "B"],
                salary_cap=200, roster_spec=standard_roster_spec,
            )

    def test_reproducible_with_seed(self, board, standard_roster_spec):
        a = simulate_nomination(
            board, team_names=["My Team", "B", "C"],
            salary_cap=200, roster_spec=standard_roster_spec,
            rng=np.random.default_rng(42),
        )
        b = simulate_nomination(
            board, team_names=["My Team", "B", "C"],
            salary_cap=200, roster_spec=standard_roster_spec,
            rng=np.random.default_rng(42),
        )
        assert a == b
