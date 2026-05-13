"""Tests for the pure helpers in salary_cap_draft.

The interactive nomination/bid loop and Yahoo-credentialed pieces are
exercised manually -- nothing here pretends to drive the input loop.
We just lock down the bid/team validation, progress format handling,
team setup, and CLI parsing that we'd otherwise not catch until
draft night.
"""

from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest

from fantasyfb.drafts.salary_cap import (
    _HELP_TEXT,
    _PICK_COMMANDS,
    _apply_pick,
    _load_progress,
    _revert_pick,
    all_rosters_full,
    build_arg_parser,
    check_bid,
    check_team_name,
    compute_max_legal_bid,
    setup_teams,
)


# --------------------------------------------------------------------- #
# Fixtures: a minimal duck-typed League that setup_teams / pick helpers
# can mutate without needing Yahoo creds.
# --------------------------------------------------------------------- #


def _make_player(name, position, team_name=None, player_id=None, **extra):
    base = {
        "player_id_sr": player_id or name.lower().replace(" ", "_"),
        "name": name,
        "position": position,
        "current_team": "FA",
        "points_rate": 10.0,
        "fantasy_team": team_name,
    }
    base.update(extra)
    return base


@pytest.fixture
def fake_league():
    """Minimal duck-typed League. Has just the columns setup_teams /
    _apply_pick / _revert_pick touch -- enough for the helper tests
    without dragging in Yahoo wiring."""
    players = pd.DataFrame([
        _make_player("Justin Jefferson", "WR"),
        _make_player("Christian McCaffrey", "RB"),
        _make_player("Joe Burrow", "QB"),
        # Two synthetic avg rows so setup_teams has something to clone.
        _make_player("avg QB", "QB", player_id="avg_QB"),
        _make_player("avg RB", "RB", player_id="avg_RB"),
    ])
    schedule = pd.DataFrame({
        "team_1": ["My Cool Team", "Other A"],
        "team_2": ["Other A", "Other B"],
    })
    league = types.SimpleNamespace(
        name="My Cool Team",
        teams=[
            {"name": "My Cool Team", "manager": "Me"},
            {"name": "Other A", "manager": "Alice"},
            {"name": "Other B", "manager": "Bob"},
        ],
        players=players,
        schedule=schedule,
    )
    return league


@pytest.fixture
def small_board():
    """A salary-cap-shaped board: players with salary_value,
    fantasy_team, winning_bid columns. Skips the VORP/tier columns
    since the helper tests don't read them."""
    rows = []
    for i in range(5):
        rows.append({
            "name": f"P{i}", "position": "RB", "current_team": "FA",
            "salary_value": 50.0 - i * 5,
            "fantasy_team": pd.NA, "winning_bid": np.nan,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- #
# check_bid
# --------------------------------------------------------------------- #


class TestCheckBid:
    def test_accepts_plain_integer(self):
        assert check_bid("42", max_legal=200) == 42

    def test_accepts_leading_dollar_sign(self):
        """Users typing '$50' rather than '50' shouldn't get a syntax
        error -- the prompt itself shows a $ for readability."""
        assert check_bid("$50", max_legal=200) == 50

    def test_strips_whitespace(self):
        assert check_bid("  17  ", max_legal=200) == 17

    def test_zero_is_legal(self):
        """A $0 bid is unusual but legal when min_bid is 0 -- the cap
        check is the only filter here."""
        assert check_bid("0", max_legal=200) == 0

    def test_rejects_above_max(self, capsys):
        assert check_bid("250", max_legal=200) is None
        assert "exceeds the maximum" in capsys.readouterr().out

    def test_rejects_non_numeric(self, capsys):
        assert check_bid("forty-two", max_legal=200) is None
        assert "non-negative integer" in capsys.readouterr().out

    def test_rejects_negative(self, capsys):
        """The isdigit check rejects the leading minus; bid still
        returns None with the same diagnostic as garbage input."""
        assert check_bid("-5", max_legal=200) is None
        assert "non-negative integer" in capsys.readouterr().out

    def test_rejects_none_input(self):
        assert check_bid(None, max_legal=200) is None


# --------------------------------------------------------------------- #
# check_team_name
# --------------------------------------------------------------------- #


class TestCheckTeamName:
    def test_canonical_name_passes_through(self, fake_league):
        assert check_team_name(fake_league, "Other A") == "Other A"

    def test_manager_handle_resolves_to_team(self, fake_league):
        """Typing the manager's name should map back to the team -- a
        common ergonomic in live drafts where you know the human."""
        assert check_team_name(fake_league, "Alice") == "Other A"

    def test_strips_whitespace(self, fake_league):
        assert check_team_name(fake_league, "  Other B  ") == "Other B"

    def test_unknown_name_returns_none(self, fake_league, capsys):
        assert check_team_name(fake_league, "Nobody") is None
        assert "Team name must be one of" in capsys.readouterr().out


# --------------------------------------------------------------------- #
# all_rosters_full
# --------------------------------------------------------------------- #


class TestAllRostersFull:
    def test_empty_board_is_not_full(self, small_board):
        assert not all_rosters_full(small_board, num_teams=2, roster_size=2)

    def test_partial_fill_not_full(self, small_board):
        b = small_board.copy()
        b.loc[0, "fantasy_team"] = "A"
        assert not all_rosters_full(b, num_teams=2, roster_size=2)

    def test_exact_fill_is_full(self, small_board):
        b = small_board.copy()
        for i, team in enumerate(["A", "A", "B", "B"]):
            b.loc[i, "fantasy_team"] = team
        assert all_rosters_full(b, num_teams=2, roster_size=2)


# --------------------------------------------------------------------- #
# compute_max_legal_bid
# --------------------------------------------------------------------- #


class TestComputeMaxLegalBid:
    def test_fresh_team_at_full_cap(self, small_board):
        """Fresh team, full roster open: max bid = cap - (slots - 1)."""
        assert compute_max_legal_bid(
            small_board, "A", salary_cap=200, roster_size=16,
        ) == 185

    def test_after_spending_drops_proportionally(self, small_board):
        b = small_board.copy()
        b.loc[0, "fantasy_team"] = "A"
        b.loc[0, "winning_bid"] = 50
        # $150 left, 15 slots open -> max = 150 - 14 = 136.
        assert compute_max_legal_bid(
            b, "A", salary_cap=200, roster_size=16,
        ) == 136

    def test_team_with_no_open_slots_returns_zero(self, small_board):
        b = small_board.copy()
        # Fill every slot for team A (roster_size=2 here).
        b.loc[0, "fantasy_team"] = "A"
        b.loc[0, "winning_bid"] = 10
        b.loc[1, "fantasy_team"] = "A"
        b.loc[1, "winning_bid"] = 10
        assert compute_max_legal_bid(
            b, "A", salary_cap=200, roster_size=2,
        ) == 0


# --------------------------------------------------------------------- #
# _apply_pick / _revert_pick
# --------------------------------------------------------------------- #


class TestApplyAndRevertPick:
    def test_apply_sets_team_and_bid_on_both(self, fake_league, small_board):
        # Add Joe Burrow to the board too so _apply_pick can find them.
        b = pd.concat([small_board, pd.DataFrame([{
            "name": "Joe Burrow", "position": "QB", "current_team": "FA",
            "salary_value": 40.0, "fantasy_team": pd.NA, "winning_bid": np.nan,
        }])], ignore_index=True)

        _apply_pick(fake_league, b, "Joe Burrow", "Other A", bid=35)

        league_row = fake_league.players.loc[
            fake_league.players.name == "Joe Burrow"
        ].iloc[0]
        board_row = b.loc[b["name"] == "Joe Burrow"].iloc[0]
        assert league_row["fantasy_team"] == "Other A"
        assert league_row["actual_salary"] == 35
        assert board_row["fantasy_team"] == "Other A"
        assert board_row["winning_bid"] == 35

    def test_apply_with_board_none_only_updates_league(self, fake_league):
        """Keepers / --inprogress restoration call _apply_pick before
        the board exists; board=None must not crash."""
        _apply_pick(fake_league, board=None, name="Joe Burrow",
                    team_name="Other A", bid=20)
        assert fake_league.players.loc[
            fake_league.players.name == "Joe Burrow", "fantasy_team"
        ].iloc[0] == "Other A"

    def test_revert_clears_both(self, fake_league, small_board):
        b = pd.concat([small_board, pd.DataFrame([{
            "name": "Joe Burrow", "position": "QB", "current_team": "FA",
            "salary_value": 40.0, "fantasy_team": pd.NA, "winning_bid": np.nan,
        }])], ignore_index=True)
        _apply_pick(fake_league, b, "Joe Burrow", "Other A", bid=35)
        _revert_pick(fake_league, b, "Joe Burrow")

        league_row = fake_league.players.loc[
            fake_league.players.name == "Joe Burrow"
        ].iloc[0]
        board_row = b.loc[b["name"] == "Joe Burrow"].iloc[0]
        assert pd.isna(league_row["fantasy_team"]) or league_row["fantasy_team"] is None
        assert pd.isna(board_row["fantasy_team"])
        assert pd.isna(board_row["winning_bid"])


# --------------------------------------------------------------------- #
# setup_teams
# --------------------------------------------------------------------- #


class TestSetupTeams:
    def test_user_team_renamed_to_my_team(self, fake_league):
        out = setup_teams(fake_league, customize=False)
        names = [t["name"] for t in out.teams]
        assert "My Team" in names
        assert "My Cool Team" not in names

    def test_user_team_first_in_order(self, fake_league):
        """The user's team gets sorted to slot 0 so views and the
        cockpit can always refer to it as 'My Team' without an extra
        lookup."""
        out = setup_teams(fake_league, customize=False)
        assert out.teams[0]["name"] == "My Team"

    def test_others_get_default_numbered_names(self, fake_league):
        out = setup_teams(fake_league, customize=False)
        # 3 teams: My Team in slot 0, then two synthetic 'Team #N' names.
        assert sorted(t["name"] for t in out.teams) == sorted(
            ["My Team", "Team #2", "Team #3"],
        )

    def test_schedule_rewritten(self, fake_league):
        """Schedule rows referring to the user's old team should be
        rewritten to reference 'My Team' so the season simulator sees
        the new name."""
        out = setup_teams(fake_league, customize=False)
        sched = out.schedule
        assert "My Team" in set(sched["team_1"]) | set(sched["team_2"])
        assert "My Cool Team" not in set(sched["team_1"]) | set(sched["team_2"])

    def test_avg_rows_seeded_per_team(self, fake_league):
        """Every team should get a copy of the avg_ template so
        season_sims can project unrostered slots before real picks."""
        out = setup_teams(fake_league, customize=False)
        avg = out.players[
            out.players.player_id_sr.astype(str).str.startswith("avg_")
        ]
        # Original 2 avg rows + 3 copies (one per team) = up to 8 rows
        # depending on the template size; minimum is 1+ per team.
        seeded = avg[avg["fantasy_team"].notna()]["fantasy_team"].unique()
        assert set(seeded) == {"My Team", "Team #2", "Team #3"}

    def test_uses_already_for_naming_when_provided(self, fake_league):
        """When --inprogress supplies a team list, those names override
        the default 'Team #N' fallback."""
        out = setup_teams(fake_league, customize=False,
                          already=["My Team", "Resumed A", "Resumed B"])
        names = [t["name"] for t in out.teams]
        assert names == ["My Team", "Resumed A", "Resumed B"]


# --------------------------------------------------------------------- #
# Progress file loading
# --------------------------------------------------------------------- #


class TestLoadProgress:
    def test_v2_format(self, tmp_path):
        csv = tmp_path / "progress.csv"
        csv.write_text(
            "name,fantasy_team,winning_bid\n"
            "Joe Burrow,Team A,30\n"
            "Justin Jefferson,Team B,55\n"
        )
        out = _load_progress(str(csv))
        assert list(out.columns) == ["name", "fantasy_team", "winning_bid"]
        assert len(out) == 2
        assert out.iloc[0]["winning_bid"] == 30

    def test_legacy_v1_salary_column_renamed(self, tmp_path):
        """Users resuming a V1 paused draft have CSVs with a 'salary'
        column. Accept those without forcing a manual rename."""
        csv = tmp_path / "v1_progress.csv"
        csv.write_text(
            "name,fantasy_team,salary\n"
            "Joe Burrow,Team A,30\n"
        )
        out = _load_progress(str(csv))
        assert "winning_bid" in out.columns
        assert "salary" not in out.columns
        assert out.iloc[0]["winning_bid"] == 30


# --------------------------------------------------------------------- #
# Arg parser
# --------------------------------------------------------------------- #


class TestArgParser:
    def test_requires_team(self):
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_minimal_args(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--team", "X"])
        assert args.team == "X"
        assert args.salary_cap == 200
        assert args.min_bid == 1
        assert args.limit_per_position == 5
        assert args.nominate_limit == 10
        assert args.season is None

    def test_salary_cap_and_min_bid_override(self):
        parser = build_arg_parser()
        args = parser.parse_args([
            "--team", "X", "--salary-cap", "500", "--min-bid", "2",
        ])
        assert args.salary_cap == 500
        assert args.min_bid == 2

    def test_season_override(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--team", "X", "--season", "2026"])
        assert args.season == 2026


# --------------------------------------------------------------------- #
# Command list / help alignment
# --------------------------------------------------------------------- #


class TestPickCommands:
    def test_commands_listed_in_help(self):
        """If someone adds a command without wiring it through both
        _PICK_COMMANDS and _HELP_TEXT, this catches it before
        draft night."""
        for cmd in ("best", "nominate", "whatif", "lookup", "roster",
                    "budgets", "exclude", "sim", "random",
                    "random til full", "go back", "help", "exit"):
            assert cmd in _PICK_COMMANDS, f"missing from _PICK_COMMANDS: {cmd}"
            assert cmd in _HELP_TEXT, f"missing from _HELP_TEXT: {cmd}"

    def test_help_text_is_nonempty(self):
        assert _HELP_TEXT.strip()
        assert "Player Up For Grabs" in _HELP_TEXT
