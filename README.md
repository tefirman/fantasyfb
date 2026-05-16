# fantasyfb

Fantasy football league simulation and optimization toolkit. Pulls
projections from [nflverse](https://github.com/nflverse) data, syncs
roster state from a Yahoo Fantasy league, and runs Monte Carlo season
simulations to value pickups, trades, and draft picks.

**Docs:** <https://tefirman.github.io/fantasyfb/>

## Install

```bash
pip install fantasyfb
```

For local development:

```bash
git clone https://github.com/tefirman/fantasyfb.git
cd fantasyfb
pip install -e ".[dev]"
```

Python 3.10+ is required.

## Quickstart

```python
import fantasyfb as fb

league = fb.League(name="My Team")
schedule_sim, standings_sim = league.season_sims(postseason=True)
print(standings_sim[["team", "wins_avg", "playoffs", "winner"]])
```

`fb.League(name=...)` reads from the Yahoo Fantasy API, so you'll need
`oauth2.json` (and `.env` with `CONSUMER_KEY` / `CONSUMER_SECRET`) set
up alongside the script. See the
[yahoo_oauth docs](https://github.com/josuebrunel/yahoo-oauth) for a
walkthrough.

## Command-line tools

After install, four entry points are on your PATH:

| Command            | Source                              | Use                                  |
| ------------------ | ----------------------------------- | ------------------------------------ |
| `fantasyfb`        | `fantasyfb.league:main`             | Weekly projections + lineup analysis |
| `snake-draft`      | `fantasyfb.drafts.snake:main`       | Live snake-draft cockpit             |
| `salary-cap-draft` | `fantasyfb.drafts.salary_cap:main`  | Live salary-cap (auction) draft tool |
| `draft-prep`       | `fantasyfb.drafts.prep:main`        | Pre-draft tiers / VORP / mocks       |

```bash
# Weekly run for a team
fantasyfb --team "My Team" --sims 1000 --adds --drops

# Pre-draft analytics
draft-prep tiers --team "My Team"
draft-prep mock --team "My Team" --adp ADP.csv --my-pick 7 --sims 50

# Draft-day cockpit
snake-draft --team "My Team" --adp ADP.csv
salary-cap-draft --team "My Team"
```

Run any command with `--help` for the full option list.

## Public API

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

Lower-level utilities live in submodules and can be imported directly:

```python
from fantasyfb.drafts.tools import compute_vorp, assign_tiers, MockDraft
from fantasyfb.drafts.snake_cockpit import build_board, view_best
from fantasyfb.sim.backtest import run_backtest, evaluate
from fantasyfb.io.excel_exporter import FantasyExcelExporter
```

| Subpackage              | Purpose                                    |
| ----------------------- | ------------------------------------------ |
| `fantasyfb.league`      | Top-level `League` class                   |
| `fantasyfb.configs`     | League / scoring presets                   |
| `fantasyfb.drafts`      | Snake, salary-cap, prep, shared draft math |
| `fantasyfb.data`        | Yahoo client + nflverse providers          |
| `fantasyfb.scoring`     | Scoring, lineup optimization, matchups     |
| `fantasyfb.projections` | V1 / V2 projection engines, fitter         |
| `fantasyfb.sim`         | Season simulation, backtests, schedule     |
| `fantasyfb.analysis`    | WAR, move analysis                         |
| `fantasyfb.io`          | Excel export                               |

## Development

```bash
pip install -e ".[dev]"
pytest                       # full test suite
python -m build              # produce sdist + wheel under dist/
```

The `tests/` directory pulls a small slice of nflverse parquet data on
first run; subsequent runs are cached locally.

## License

MIT. See [LICENSE](LICENSE).
