"""Tests for the main fantasyfb CLI's --refresh-cache flag.

Regression coverage for a live-week discrepancy where League() always
built a plain NflreadpyProvider() with no way to force a fresh pull,
so a stale (up to 24h) filesystem cache could silently serve
mid-correction stats -- e.g. a player's just-played week missing
entirely from the cached parquet. See league.py main()'s
NflreadpyProvider(refresh=options.refresh_cache) wiring.
"""

from __future__ import annotations

import sys

from fantasyfb.cli import initialize_inputs


class TestRefreshCacheFlag:
    def test_defaults_to_false(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fantasyfb"])
        options = initialize_inputs()
        assert options.refresh_cache is False

    def test_flag_sets_true(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fantasyfb", "--refresh-cache"])
        options = initialize_inputs()
        assert options.refresh_cache is True
