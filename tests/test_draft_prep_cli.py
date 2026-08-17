"""Tests for the draft-prep CLI's --refresh-cache flag.

fantasyfb.drafts.prep has no dedicated CLI test file yet (test_draft_tools.py
only covers drafts/tools.py), so this covers just the new flag and its
wiring into _build_league -- not the full argparse surface.
"""

from __future__ import annotations

from fantasyfb.drafts.prep import _build_league, build_parser


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
