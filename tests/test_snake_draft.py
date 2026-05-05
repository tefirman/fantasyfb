"""Tests for the pure helpers in snake_draft.

The interactive pick loop and Yahoo-credentialed pieces are exercised
manually -- nothing here pretends to drive the input loop. We just lock
down the small bits of pickorder math and CLI parsing that we'd otherwise
not notice breaking until draft night.
"""

from __future__ import annotations

import pytest

from snake_draft import (
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
            parser.parse_args(["--teamname", "X"])

    def test_minimal_args_succeed(self):
        parser = build_arg_parser()
        args = parser.parse_args(["--teamname", "X", "--adp", "ADP.csv"])
        assert args.teamname == "X"
        assert args.adp == "ADP.csv"
        assert args.limit_per_position == 5
        assert args.nearest_window == 2

    def test_adp_column_overrides(self):
        parser = build_arg_parser()
        args = parser.parse_args([
            "--teamname", "X", "--adp", "ADP.csv",
            "--adp-name-col", "FullName",
            "--adp-pos-col", "Pos",
            "--adp-avg-col", "Avg",
        ])
        assert args.adp_name_col == "FullName"
        assert args.adp_pos_col == "Pos"
        assert args.adp_avg_col == "Avg"
