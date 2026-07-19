"""Tests for the pure helpers in snake_draft.

The interactive pick loop and Yahoo-credentialed pieces are exercised
manually -- nothing here pretends to drive the input loop. We just lock
down the small bits of pickorder math and CLI parsing that we'd otherwise
not notice breaking until draft night.
"""

from __future__ import annotations

import pytest

from fantasyfb.drafts.snake import (
    _HELP_TEXT,
    _PICK_COMMANDS,
    _completer,
    _set_completion_candidates,
    build_arg_parser,
    parse_payouts,
    snake_pick_slot,
)


class TestSnakePickSlot:
    def test_round_1_runs_forward(self):
        assert [snake_pick_slot(i, 12) for i in range(12)] == list(range(12))

    def test_round_2_reverses(self):
        # Picks 12..23 are round 2 in a 12-team draft.
        assert [snake_pick_slot(i, 12) for i in range(12, 24)] == list(range(11, -1, -1))

    def test_round_3_runs_forward_again(self):
        assert [snake_pick_slot(i, 12) for i in range(24, 36)] == list(range(12))

    def test_handles_non_12_team_leagues(self):
        # 10-team league: pick 11 (0-indexed 10) is start of round 2,
        # so slot 9.
        assert snake_pick_slot(10, 10) == 9
        assert snake_pick_slot(19, 10) == 0

    def test_reversal_round_zero_is_plain_snake(self):
        # Sleeper's "disabled" sentinel -- same as omitting the arg.
        picks = [snake_pick_slot(i, 12, reversal_round=0) for i in range(36)]
        plain = [snake_pick_slot(i, 12) for i in range(36)]
        assert picks == plain

    def test_third_round_reversal_repeats_round_2_direction(self):
        # Rounds 1-2 unaffected; round 3 (picks 24..35) repeats round 2's
        # reverse direction (12..1) instead of flipping back to 1..12.
        assert [snake_pick_slot(i, 12, reversal_round=3) for i in range(24, 36)] \
            == list(range(11, -1, -1))

    def test_third_round_reversal_flips_parity_from_round_4_on(self):
        # Round 4 (picks 36..47) then reverses *relative to round 3*,
        # landing back on forward order -- opposite of plain snake's
        # round 4 (which would be reverse).
        assert [snake_pick_slot(i, 12, reversal_round=3) for i in range(36, 48)] \
            == list(range(12))

    def test_reversal_round_matches_manual_trace_for_first_two_teams(self):
        # Hand-traced from the league-slot perspective (see conversation):
        # slot 0 (1st overall) picks #1, #24, #36 under TRR@3.
        # slot 11 (12th overall) picks #12, #13, #25 under TRR@3.
        picks = [snake_pick_slot(i, 12, reversal_round=3) for i in range(36)]
        slot0_picks = [i + 1 for i, s in enumerate(picks) if s == 0]
        slot11_picks = [i + 1 for i, s in enumerate(picks) if s == 11]
        assert slot0_picks == [1, 24, 36]
        assert slot11_picks == [12, 13, 25]


class TestParsePayouts:
    def test_default_when_blank(self):
        out = parse_payouts(None, num_teams=12)
        assert out == [720.0, 360.0, 120.0]

    def test_parses_three_values(self):
        out = parse_payouts("400,200,100", num_teams=12)
        assert out == [400.0, 200.0, 100.0]

    def test_truncates_to_three(self, capsys):
        out = parse_payouts("100,80,60,40,20", num_teams=12)
        assert out == [100.0, 80.0, 60.0]
        assert "Only using top three" in capsys.readouterr().out

    def test_falls_back_on_garbage(self, capsys):
        out = parse_payouts("first,second,third", num_teams=10)
        # Defaults scale with team count.
        assert out == [600.0, 300.0, 100.0]
        assert "standard payouts" in capsys.readouterr().out


class TestArgParser:
    def test_requires_teamname_and_adp(self):
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])
        with pytest.raises(SystemExit):
            parser.parse_args(["--team", "X"])

    def test_minimal_args_succeed(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--team", "X", "--adp", "ADP.csv"])
        assert args.team == "X"
        assert args.adp == "ADP.csv"
        assert args.limit_per_position == 5
        assert args.nearest_window == 2
        assert args.season is None

    def test_season_override(self):
        """--season threads through to League so pre-draft runs can
        target the upcoming season instead of the auto-detected
        most-recently-completed one."""
        parser = build_arg_parser()
        args = parser.parse_args([
            "--team", "X", "--adp", "ADP.csv", "--season", "2026",
        ])
        assert args.season == 2026

    def test_adp_column_overrides(self):
        parser = build_arg_parser()
        args = parser.parse_args([
            "--team", "X", "--adp", "ADP.csv",
            "--adp-name-col", "FullName",
            "--adp-pos-col", "Pos",
            "--adp-avg-col", "Avg",
        ])
        assert args.adp_name_col == "FullName"
        assert args.adp_pos_col == "Pos"
        assert args.adp_avg_col == "Avg"


class TestPickCommands:
    def test_known_commands_listed(self):
        """Sanity check that the in-loop dispatch exception list and the
        help text stay aligned -- if someone adds a command without
        wiring it through both, this catches it."""
        for cmd in ("best", "lookup", "exclude", "roster",
                    "sim", "simadd", "random", "random til me", "go back",
                    "help", "exit"):
            assert cmd in _PICK_COMMANDS, f"missing from _PICK_COMMANDS: {cmd}"
            assert cmd in _HELP_TEXT, f"missing from _HELP_TEXT: {cmd}"

    def test_help_text_is_nonempty(self):
        assert _HELP_TEXT.strip()
        assert "Commands during the draft" in _HELP_TEXT


class TestCompletion:
    """Sanity checks on the readline completer hook. The hook itself
    can't be exercised in pytest (no terminal), but the candidate-pool
    logic and the completer's prefix matching are pure functions."""

    def test_returns_unique_sorted_candidates(self):
        _set_completion_candidates(["Joe Burrow", "Joe Burrow", "Saquon Barkley"])
        # state=0 returns first match; subsequent states walk forward.
        assert _completer("Joe", 0) == "Joe Burrow"
        # Dedupe: second 'Joe' wasn't kept.
        assert _completer("Joe", 1) is None

    def test_case_insensitive_prefix_match(self):
        _set_completion_candidates(["Justin Jefferson", "Cooper Kupp"])
        assert _completer("just", 0) == "Justin Jefferson"
        assert _completer("JUST", 0) == "Justin Jefferson"

    def test_no_match_returns_none(self):
        _set_completion_candidates(["best", "nearest"])
        assert _completer("zzz", 0) is None

    def test_walks_through_all_matches(self):
        _set_completion_candidates(["random", "random til me"])
        results = []
        state = 0
        while True:
            r = _completer("ra", state)
            if r is None:
                break
            results.append(r)
            state += 1
        assert results == ["random", "random til me"]

    def test_drops_falsy_candidates(self):
        """None / empty-string entries shouldn't crash the completer --
        league.players.name can carry NaN for synthetic average rows."""
        _set_completion_candidates(["Joe Burrow", None, "", "Saquon Barkley"])
        # Only the two real names should be in the pool.
        all_matches = []
        state = 0
        while True:
            r = _completer("", state)
            if r is None:
                break
            all_matches.append(r)
            state += 1
        assert all_matches == ["Joe Burrow", "Saquon Barkley"]
