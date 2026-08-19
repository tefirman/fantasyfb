"""Tests for the draft-prep CLI's --refresh-cache and --platform flags.

fantasyfb.drafts.prep has no dedicated CLI test file yet (test_draft_tools.py
only covers drafts/tools.py), so this covers just these flags and their
wiring into _build_league / main -- not the full argparse surface.
"""

from __future__ import annotations

from fantasyfb.drafts.prep import _build_league, build_parser, main


class TestRefreshCacheFlag:
    def test_defaults_to_false(self):
        parser = build_parser()
        args = parser.parse_args(["tiers", "--team", "X"])
        assert args.refresh_cache is False

    def test_flag_sets_true(self):
        parser = build_parser()
        args = parser.parse_args(["tiers", "--team", "X", "--refresh-cache"])
        assert args.refresh_cache is True

    def test_present_on_every_subcommand(self):
        parser = build_parser()
        for argv in (
            ["tiers", "--team", "X", "--refresh-cache"],
            ["values", "--team", "X", "--adp", "ADP.csv", "--refresh-cache"],
            ["traps", "--team", "X", "--adp", "ADP.csv", "--refresh-cache"],
            [
                "mock", "--team", "X", "--adp", "ADP.csv",
                "--my-pick", "1", "--refresh-cache",
            ],
        ):
            args = parser.parse_args(argv)
            assert args.refresh_cache is True


class TestBuildLeaguePassesRefreshThrough:
    def test_refresh_cache_reaches_nfl_provider(self, monkeypatch):
        captured = {}

        class _FakeProvider:
            def __init__(self, refresh=False):
                captured["refresh"] = refresh

        class _FakeLeague:
            def __init__(self, **kwargs):
                captured["league_kwargs"] = kwargs

        import fantasyfb as fb
        import fantasyfb.data.nflreadpy_provider as provider_mod
        monkeypatch.setattr(provider_mod, "NflreadpyProvider", _FakeProvider)
        monkeypatch.setattr(fb, "League", _FakeLeague)

        parser = build_parser()
        args = parser.parse_args(["tiers", "--team", "X", "--refresh-cache"])
        _build_league(args)

        assert captured["refresh"] is True
        assert isinstance(captured["league_kwargs"]["nfl_provider"], _FakeProvider)


class TestPlatformFlag:
    def test_defaults_to_generic(self):
        parser = build_parser()
        args = parser.parse_args(["tiers", "--team", "X"])
        assert args.platform == "generic"
        assert args.sleeper_league_id is None

    def test_present_on_every_subcommand(self):
        parser = build_parser()
        for argv in (
            ["tiers", "--team", "X", "--platform", "sleeper",
             "--sleeper-league-id", "123"],
            ["values", "--team", "X", "--adp", "ADP.csv",
             "--platform", "sleeper", "--sleeper-league-id", "123"],
            ["traps", "--team", "X", "--adp", "ADP.csv",
             "--platform", "sleeper", "--sleeper-league-id", "123"],
            ["mock", "--team", "X", "--adp", "ADP.csv", "--my-pick", "1",
             "--platform", "sleeper", "--sleeper-league-id", "123"],
        ):
            args = parser.parse_args(argv)
            assert args.platform == "sleeper"
            assert args.sleeper_league_id == "123"

    def test_main_rejects_sleeper_without_league_id(self, capsys):
        rc = main(["tiers", "--team", "X", "--platform", "sleeper"])
        assert rc == 1
        assert "--sleeper-league-id is required" in capsys.readouterr().out


class TestBuildLeaguePassesPlatformThrough:
    def test_platform_args_reach_league(self, monkeypatch):
        captured = {}

        class _FakeProvider:
            def __init__(self, refresh=False):
                pass

        class _FakeLeague:
            def __init__(self, **kwargs):
                captured["league_kwargs"] = kwargs

        import fantasyfb as fb
        import fantasyfb.data.nflreadpy_provider as provider_mod
        monkeypatch.setattr(provider_mod, "NflreadpyProvider", _FakeProvider)
        monkeypatch.setattr(fb, "League", _FakeLeague)

        parser = build_parser()
        args = parser.parse_args([
            "tiers", "--team", "X", "--platform", "sleeper",
            "--sleeper-league-id", "456", "--num-teams", "10",
            "--mock-scoring", "half_ppr",
        ])
        _build_league(args)

        assert captured["league_kwargs"]["platform"] == "sleeper"
        assert captured["league_kwargs"]["sleeper_league_id"] == "456"
        assert captured["league_kwargs"]["num_teams"] == 10
        assert captured["league_kwargs"]["mock_scoring"] == "half_ppr"

    def test_generic_defaults_applied(self, monkeypatch):
        captured = {}

        class _FakeProvider:
            def __init__(self, refresh=False):
                pass

        class _FakeLeague:
            def __init__(self, **kwargs):
                captured["league_kwargs"] = kwargs

        import fantasyfb as fb
        import fantasyfb.data.nflreadpy_provider as provider_mod
        monkeypatch.setattr(provider_mod, "NflreadpyProvider", _FakeProvider)
        monkeypatch.setattr(fb, "League", _FakeLeague)

        parser = build_parser()
        args = parser.parse_args(["tiers", "--team", "X"])
        _build_league(args)

        assert captured["league_kwargs"]["platform"] == "generic"
        assert captured["league_kwargs"]["num_teams"] == 12
        assert captured["league_kwargs"]["mock_scoring"] == "ppr"
