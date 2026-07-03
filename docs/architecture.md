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
