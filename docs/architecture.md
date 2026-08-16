# Architecture

How the package is laid out and how data flows from Yahoo + nflverse
through projections, simulation, and analysis.

## Subpackages

```
fantasyfb/
├── league.py              # Top-level League class
├── configs.py             # League / scoring presets (SFB, DraftKings, Underdog)
├── cli.py                 # argparse/optparse glue for the `fantasyfb` entry point
├── data/                  # Yahoo client + nflverse providers
├── scoring/               # FantasyScorer, LineupOptimizer, MatchupModel
├── projections/           # V2 projection engine + walk-forward fitter
├── sim/                   # SeasonSimulator, ScheduleManager, backtest harness
├── drafts/                # Snake, salary-cap, prep, shared draft math
├── analysis/              # WAR calculation, move analysis
└── io/                    # Excel export
```

| Subpackage              | What lives here                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------ |
| `fantasyfb.league`      | The `League` class — the user-facing entry point for everything                      |
| `fantasyfb.configs`     | Scoring + roster presets for non-Yahoo platforms (SFB, DK best-ball, Underdog)       |
| `fantasyfb.cli`         | `optparse` glue for the `fantasyfb` console script                                   |
| `fantasyfb.data`        | Yahoo Fantasy API client; pluggable NFL data providers (nflreadpy default)           |
| `fantasyfb.scoring`     | `FantasyScorer` (stats → points), `LineupOptimizer`, `MatchupModel`                  |
| `fantasyfb.projections` | `ProjectionEngineV2`, `model_fitter` (walk-forward LS weight fitting)                 |
| `fantasyfb.sim`         | `SeasonSimulator`, `ScheduleManager`, `backtest` harness                              |
| `fantasyfb.drafts`      | `snake.py`, `salary_cap.py`, `prep.py`, `tools.py`, `snake_cockpit.py`, `salary_cap_cockpit.py` |
| `fantasyfb.analysis`    | `WARCalculator`, `MoveAnalyzer`                                                      |
| `fantasyfb.io`          | `FantasyExcelExporter`                                                               |

## Data flow

```
┌─────────────────┐     ┌──────────────┐
│ Yahoo Fantasy   │     │ nflverse     │
│ API             │     │ (nflreadpy)  │
└────────┬────────┘     └──────┬───────┘
         │ rosters, scoring,   │ weekly stats,
         │ schedule, settings  │ schedule, depth
         ▼                     ▼
       ┌────────────────────────────┐
       │  League.__init__           │
       │  (data/yahoo_client,       │
       │   data/nflreadpy_provider) │
       └────────────┬───────────────┘
                    │ players DataFrame, roster_spots, scoring
                    ▼
       ┌────────────────────────────┐
       │  ProjectionEngineV2        │
       │  + MatchupModel            │
       │  (per-player rates →       │
       │   per-game projections)    │
       └────────────┬───────────────┘
                    │ points_avg, points_stdev per player
                    ▼
       ┌────────────────────────────┐
       │  LineupOptimizer           │
       │  (best lineup per team     │
       │   per week)                │
       └────────────┬───────────────┘
                    │
                    ▼
       ┌────────────────────────────┐
       │  SeasonSimulator           │
       │  (Monte Carlo over rest    │
       │   of season)               │
       └────────────┬───────────────┘
                    │ standings_sim, schedule_sim
                    ▼
       ┌────────────────────────────┐
       │  MoveAnalyzer              │
       │  (delta-earnings for adds/ │
       │   drops/trades)            │
       └────────────┬───────────────┘
                    │
                    ▼
       ┌────────────────────────────┐
       │  FantasyExcelExporter      │
       └────────────────────────────┘
```

The draft tooling shortcuts most of this: `draft-prep` and the
cockpits only need the projection step (for VORP) plus `MockDraft` /
board-building helpers from `drafts/`.

## Pluggable NFL data backend

`League(nfl_provider=...)` accepts any subclass of
[`NFLDataProvider`](api/data.md). The default is
[`NflreadpyProvider`](api/data.md). Anything that produces weekly
stats, schedules, and depth charts in the expected shape will work —
useful for testing without hitting the network or wiring in a
different data source.

## nflreadpy caching

`nflreadpy` downloads pre-built parquet files from nflverse's GitHub
releases and caches every download itself (`nflreadpy.cache`), but its
own default is an in-memory cache that's wiped when the process exits.
Since each `fantasyfb`/`draft-prep`/`snake-draft`/`salary-cap-draft`
invocation is a fresh process, that default bought nothing across
runs — a multi-hour draft-prep session re-downloaded the same
stats/schedule/roster parquet on every single command.

`NflreadpyProvider.__init__` switches nflreadpy to **filesystem**
caching by default (24h TTL, same as nflreadpy's own default duration),
so a pull made by one command is reused by the next one instead of
hitting the network again. In practice this means:

- The first pull of a session needs a live connection; every
  subsequent pull within the cache window can run offline.
- Past weeks' stats are immutable, so a stale cache is only a concern
  for the current week's in-progress data (live box scores) and depth
  charts, which change during the week.
- Pass `--refresh-cache` to `draft-prep`, `snake-draft`, or
  `salary-cap-draft` to bypass the cache and force a fresh download
  for that run (calls `nflreadpy.clear_cache()` under the hood).
- An explicit `NFLREADPY_CACHE` env var (or a prior
  `nflreadpy.update_config()` call) always wins over the
  filesystem-cache default — set it to `memory` or `off` to restore
  nflreadpy's out-of-the-box behavior, or construct
  `NflreadpyProvider(cache_mode=..., cache_duration=...)` directly for
  per-instance control.
- This only covers nflreadpy's normal download path. The rare
  `_pyarrow_fallback` used when polars rejects a parquet file for
  invalid UTF-8 (see the module docstring in `nflreadpy_provider.py`)
  downloads directly via `urllib` and is not cached.

## Projection engine

`ProjectionEngineV2` (`projections/engine_v2.py`) is the sole projection
engine. It decomposes each player's historical output into volume ×
efficiency rates, applies time decay and Bayesian shrinkage toward a
position prior, then multiplies by a Vegas-backed `MatchupModel` factor.

By default (`League(fit_matchup=True)`), the matchup weights are
ridge-fitted via walk-forward least squares on the prior season
(`model_fitter.fit_from_history`). A 2024 walk-forward backtest confirmed
the fitted weights beat both the hand-tuned defaults and the legacy V1
engine by 5–6% overall MAE — see issue
[#24](https://github.com/tefirman/fantasyfb/issues/24) for full results.

## See also

- [API reference](api/index.md) — auto-generated from docstrings.
- [Changelog](changelog.md) — version-by-version changes.
