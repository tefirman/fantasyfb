"""Characterization tests for the interactive snake and salary cap draft loops.

Drives each CLI's ``main()`` end to end with scripted ``input()`` answers
against an offline League replayed from the generic snapshot, and checks the
saved progress CSV, the exit codes and the final output. They pin the behavior
the drafts have today so the loops can be restructured without changing it.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest
import snapshot_io

pytestmark = pytest.mark.skipif(
    not any(d.name.startswith("generic") for d in snapshot_io.snapshot_dirs()),
    reason="no recorded generic snapshot",
)

NUM_SIMS = 40


@pytest.fixture
def draft_env(replay_league_generic, monkeypatch, tmp_path):
    """Patch League construction to hand back a private copy of the replayed one."""
    import fantasyfb as fb
    import fantasyfb.data.nflreadpy_provider as provider_mod

    class _FakeProvider:
        def __init__(self, refresh=False):
            pass

    built = {}

    def _factory(**kwargs):
        league = copy.deepcopy(replay_league_generic)
        league.num_sims = NUM_SIMS
        # The real GenericClient starts every team with an empty roster, and the
        # user's team is named by --team; the recorded snapshot differs on both.
        league.players["fantasy_team"] = None
        old_name, new_name = league.teams[0]["name"], kwargs["name"]
        league.teams[0]["name"] = new_name
        league.schedule.loc[league.schedule.team_1 == old_name, "team_1"] = new_name
        league.schedule.loc[league.schedule.team_2 == old_name, "team_2"] = new_name
        league.name = new_name
        built["kwargs"] = kwargs
        built["league"] = league
        return league

    monkeypatch.setattr(provider_mod, "NflreadpyProvider", _FakeProvider)
    monkeypatch.setattr(fb, "League", _factory)
    monkeypatch.chdir(tmp_path)

    players = replay_league_generic.players
    real = players[~players.player_id_sr.astype(str).str.startswith("avg_")]
    real = real[real.position.isin(["QB", "RB", "WR", "TE", "K", "DEF"])]
    adp = real.sort_values("points_avg", ascending=False).head(250)[["name", "position", "current_team"]]
    adp = adp.rename(columns={"name": "Player", "position": "POS", "current_team": "Team"})
    adp["AVG"] = range(1, len(adp) + 1)
    adp_path = tmp_path / "adp.csv"
    adp.to_csv(adp_path, index=False)
    built["adp"] = str(adp_path)
    built["players"] = real
    built["tmp"] = tmp_path
    return built


@pytest.fixture
def script_input(monkeypatch):
    def _install(answers):
        remaining = list(answers)
        prompts = []

        def _input(prompt=""):
            prompts.append(prompt)
            if not remaining:
                raise AssertionError(f"ran out of scripted input at prompt {prompt!r}")
            return remaining.pop(0)

        monkeypatch.setattr("builtins.input", _input)
        return prompts

    return _install


def _snake_args(env, *extra):
    return [
        "--team", "My Team", "--adp", env["adp"], "--platform", "generic",
        "--num-teams", "12", "--mock-scoring", "ppr",
        "--roster-spots", "QB=1,RB=2,WR=2,TE=1,W/R/T=1,K=1,DEF=1,BN=2",
        *extra,
    ]


class TestSnakeLoop:
    def test_random_go_back_and_exit(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.snake import main

        script_input(["n", "3", "random", "random", "go back", "roster", "help", "exit"])
        assert main(_snake_args(draft_env)) == 0

        out = capsys.readouterr().out
        assert "Auto-drafting" in out
        assert "Exiting draft. Progress saved to DraftProgress.csv." in out
        progress = pd.read_csv(draft_env["tmp"] / "DraftProgress.csv")
        assert len(progress) == 1
        assert progress.fantasy_team.notna().all()

    def test_resume_restores_picks(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.snake import main

        script_input(["n", "3", "random", "random", "random", "exit"])
        main(_snake_args(draft_env))
        first = pd.read_csv(draft_env["tmp"] / "DraftProgress.csv")
        assert len(first) == 3

        path = str(draft_env["tmp"] / "DraftProgress.csv")
        script_input(["3", "random", "exit"])
        main(_snake_args(draft_env, "--inprogress", path))
        resumed = pd.read_csv(path)
        assert len(resumed) == 4
        assert resumed.name.tolist()[:3] == first.name.tolist()

    def test_full_draft_writes_results(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.snake import main

        script_input(["n", "3"] + ["random til me", "random"] * 20)
        assert main(_snake_args(draft_env)) == 0

        out = capsys.readouterr().out
        assert "winner" in out and "earnings" in out
        progress = pd.read_csv(draft_env["tmp"] / "DraftProgress.csv")
        spots = draft_env["league"].roster_spots
        assert len(progress) == 12 * spots.loc[spots.position != "IR", "count"].sum()
        assert progress.name.is_unique
        results = pd.read_csv(draft_env["tmp"] / "DraftResults.csv")
        assert len(results) == 12
        assert "My Team" in results.team.tolist()

    def test_bestball_full_draft_uses_bestball_sims(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.snake import main

        script_input(["n", "3"] + ["random til me", "random"] * 20)
        assert main(_snake_args(draft_env, "--bestball")) == 0
        assert draft_env["kwargs"]["bestball"] == "underdog"
        results = pd.read_csv(draft_env["tmp"] / "DraftResults.csv")
        assert len(results) == 12


def _cap_args(*extra):
    return [
        "--team", "My Team", "--platform", "generic", "--num-teams", "12",
        "--mock-scoring", "ppr",
        "--roster-spots", "QB=1,RB=2,WR=2,TE=1,W/R/T=1,K=1,DEF=1,BN=7",
        *extra,
    ]


class TestSalaryCapLoop:
    def test_random_go_back_and_exit(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.salary_cap import main

        script_input(["n", "random", "random", "go back", "roster", "budgets", "help", "exit"])
        assert main(_cap_args()) == 0

        out = capsys.readouterr().out
        assert "Auto-pick:" in out
        assert "Exiting draft. Progress saved to DraftProgressSalaryCap.csv." in out
        progress = pd.read_csv(draft_env["tmp"] / "DraftProgressSalaryCap.csv")
        assert len(progress) == 1
        assert progress.winning_bid.ge(1).all()

    def test_typed_nomination_records_winner_and_bid(self, draft_env, script_input):
        from fantasyfb.drafts.salary_cap import main

        players = draft_env["players"]
        target = players.loc[players.position == "QB"].sort_values("points_avg").iloc[-1]["name"]
        script_input(["n", target, "My Team", "37", "exit"])
        assert main(_cap_args()) == 0

        progress = pd.read_csv(draft_env["tmp"] / "DraftProgressSalaryCap.csv")
        assert progress.to_dict("records") == [
            {"name": target, "fantasy_team": "My Team", "winning_bid": 37},
        ]

    def test_resume_restores_picks(self, draft_env, script_input):
        from fantasyfb.drafts.salary_cap import main

        script_input(["n", "random", "random", "exit"])
        main(_cap_args())
        path = str(draft_env["tmp"] / "DraftProgressSalaryCap.csv")
        first = pd.read_csv(path)

        script_input(["random", "exit"])
        main(_cap_args("--inprogress", path))
        resumed = pd.read_csv(path)
        assert len(resumed) == len(first) + 1
        assert resumed.name.tolist()[:len(first)] == first.name.tolist()

    def test_random_til_full_writes_results(self, draft_env, script_input, capsys):
        from fantasyfb.drafts.salary_cap import main

        script_input(["n", "random til full"])
        assert main(_cap_args()) == 0

        progress = pd.read_csv(draft_env["tmp"] / "DraftProgressSalaryCap.csv")
        assert progress.name.is_unique
        assert (progress.groupby("fantasy_team").winning_bid.sum() <= 200).all()
        assert len(pd.read_csv(draft_env["tmp"] / "DraftResults.csv")) == 12
        assert "earnings" in capsys.readouterr().out
