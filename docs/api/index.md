# API reference

Auto-generated from docstrings via
[`mkdocstrings`](https://mkdocstrings.github.io/). For higher-level
context — what each subpackage does and how data flows — see the
[architecture page](../architecture.md).

## Public top-level exports

The most-used entry points are re-exported from the package root:

```python
from fantasyfb import (
    League,                            # main entry point
    FantasyScorer,                     # scoring rules -> points
    MatchupModel, ProjectionEngineV2,  # projection internals
    LineupOptimizer,
    SeasonSimulator, ScheduleManager,
    NflreadpyProvider,                 # default data backend
)
```

## Pages

- **[League](league.md)** — top-level `League` class.
- **[Projections](projections.md)** — `ProjectionEngineV2`,
  `MatchupModel`, `model_fitter`.
- **[Simulation](sim.md)** — `SeasonSimulator`, `ScheduleManager`,
  `backtest`.
- **[Drafts](drafts.md)** — `compute_vorp`, `assign_tiers`,
  `MockDraft`, snake cockpit views.
- **[Scoring](scoring.md)** — `FantasyScorer`, `LineupOptimizer`,
  `MatchupModel`.
- **[Data providers](data.md)** — Yahoo client, `NflreadpyProvider`.
- **[I/O](io.md)** — `FantasyExcelExporter`.

## Configs helper

```python
from fantasyfb import get_league_config, apply_default_scoring_categories
```

::: fantasyfb.configs.get_league_config

::: fantasyfb.configs.apply_default_scoring_categories
