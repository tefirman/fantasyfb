# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fantasyfb` is a published PyPI package (src layout, `src/fantasyfb/`) for fantasy football league simulation and optimization. It pulls NFL data from nflverse (via `nflreadpy`), syncs league state from a fantasy platform (Yahoo, Sleeper, or a synthetic "generic" league), builds per-player projections, and runs Monte Carlo season simulations to value pickups, trades, and draft picks.

## Commands

```bash
pip install -e ".[dev]"            # dev install (a .venv with pytest/ruff already exists locally)
pytest -q                          # full suite, what CI runs on Python 3.10/3.11/3.12
pytest tests/test_matchup_model.py                      # one file
pytest tests/test_matchup_model.py::test_name -v        # one test
pytest -m smoke                    # only live-API smoke tests (Sleeper/Yahoo); they self-skip if unreachable
ruff check src tests               # lint (default rules; not enforced in CI and has pre-existing findings)
python -m build                    # sdist + wheel into dist/
mkdocs build                       # docs site (needs pip install -e ".[docs]")
```

Tests are not hermetic: the session-scoped fixtures in `tests/conftest.py` download real 2024 nflverse parquet data (weeks 1-4) on first use, so the first run needs network. `conftest.py` also puts `src/` on `sys.path`, so `pytest` works without an editable install. A smoke test reported as "skipped" verified nothing.

Console scripts (defined in `pyproject.toml`): `fantasyfb` (`league:main`, weekly projections/lineup/move analysis, Yahoo only), `snake-draft`, `salary-cap-draft`, `draft-prep` (all in `drafts/`, default to `--platform generic` so they run with no credentials).

## Architecture

`League` (`league.py`) is the orchestrator and the user-facing entry point. Its `__init__` does the whole pipeline eagerly, in this order: pick a platform client, load settings/teams/schedule from it, pull the player pool and rosters, load ~2 seasons of nflverse stats, enrich players via `PlayerDataManager` (ID mapping, depth charts, injuries), fit `MatchupModel` weights (`fit_matchup=True` by default, ~5-10s; tests often pass `fit_matchup=False`), then `get_rates()` (projections), `war_sim()`, `get_schedule()`, `starters(week)`. Constructing a `League` is therefore expensive and network-bound; downstream methods (`season_sims`, `bestball_sims`, `possible_adds/drops/trades`) operate on the resulting `players` DataFrame.

Data flow: platform client + nflverse provider -> `players` DataFrame -> `ProjectionEngineV2` x `MatchupModel` factor (`points_avg`, `points_stdev`) -> `LineupOptimizer` (best lineup per team per week, sets `starter`) -> `SeasonSimulator` -> `MoveAnalyzer` (earnings deltas for moves) -> `FantasyExcelExporter`. The draft tools only need the projection step plus the VORP/tier/mock helpers in `drafts/tools.py`; `*_cockpit.py` hold the testable board logic behind the interactive `snake.py` / `salary_cap.py` CLIs.

Two pluggable seams:
- **Fantasy platform**: `data/platform_client.py` defines the read-only `FantasyPlatformClient` ABC, implemented by `YahooFantasyClient`, `SleeperClient`, and `GenericClient` (synthetic rosters, round-robin schedule, real NFL player pool). `League(client=...)` injects one directly, which is the main testing hook. Nothing in the package writes to a platform.
- **NFL data**: `data/nfl_provider.py` defines `NFLDataProvider`; `NflreadpyProvider` is the default and the only real implementation.

The `players` DataFrame is the shared state that most bugs travel through. Recurring bug classes from the changelog worth checking when touching joins: rows fanning out into duplicates on a merge (depth charts have one row per player per role; names collide), silent `NaN`s from exact-string name joins (suffixes like Jr./III; prefer `yahoo_id`/`gsis_id`/`player_id_sr` joins), null `until` injury values compared against ints, and position-code mismatches between feeds (e.g. nflverse `PK` vs fantasyfb `K`).

### Data caching and external inputs

- `NflreadpyProvider` switches nflreadpy to a filesystem cache with a hard 24h TTL from download time. `--refresh-cache` on the draft CLIs clears it; the `NFLREADPY_CACHE` env var overrides the default. A `_pyarrow_fallback` path handles parquet files polars rejects for invalid UTF-8 and is uncached.
- `get_depth_charts()` defaults to the current calendar year's live feed (not the season clamp other methods use) and degrades to an empty frame when unavailable. Passing `(season, week)` does a historical lookup (pre-2025 schema only), used by `sim/backtest.py`.
- `get_schedule`/`get_rosters`/`get_player_stats` raise when offline with a cold cache; depth charts and injury overrides degrade with a warning instead.
- Manual injury return-week overrides come from `injured_list.csv` in the separate `tefirman/fantasy-data` repo (fetched from raw.githubusercontent.com by `PlayerDataManager.add_injuries`). The `/update-injuries` skill in `.claude/skills/` maintains that file (local checkout `~/fantasy-data`) and must never commit without explicit approval.
- Sleeper's player payload is cached at `~/.cache/fantasyfb/sleeper_players.json` for 24h.

### Live-week behavior

During an in-progress NFL week, `League._apply_live_week_actuals` replaces `points_avg` with actual points (and `points_stdev` with 0) for starters whose NFL game has finished, and `LineupOptimizer._handle_live_week_lineup` must mark already-played active players as `starter=True`. Changes to lineup or scoring code should preserve both.

## Credentials

Yahoo needs `oauth2.json` plus `.env` with `CONSUMER_KEY`/`CONSUMER_SECRET` in the working directory (both gitignored). Sleeper needs only a public league ID; generic needs nothing. `notes/yahoo_api_probe.py` is a go/no-go check for Yahoo Fantasy API access.

## Repo conventions

- `CHANGELOG.md` follows Keep a Changelog with an `[Unreleased]` section; fixes are written up in detail with the issue/PR number. `docs/changelog.md` pulls it in via a snippet include, so edit only `CHANGELOG.md`. Release notes drafts live in `notes/release_vX.Y.Z.md`.
- `notes/` and all `*.csv` files (except `examples/*.csv`) are gitignored; the CSVs at the repo root are local run outputs/inputs, not fixtures.
- Publishing to PyPI happens from `.github/workflows/publish.yml` on a GitHub release (TestPyPI on manual dispatch). Docs deploy to GitHub Pages on push to main.
- In user-facing text, say "salary cap draft" / "bidding", not "auction".
