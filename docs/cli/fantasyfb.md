# `fantasyfb`

In-season weekly analysis. Pulls your league state from Yahoo, runs
Monte Carlo season simulations, and writes an Excel workbook with
rosters, projected standings, and optionally add/drop/trade analysis.

## Usage

```bash
fantasyfb --team "My Team" [options]
```

## Common recipes

```bash
# Basic weekly run
fantasyfb --team "My Team" --sims 1000

# Add waiver-wire analysis and drop suggestions
fantasyfb --team "My Team" --sims 1000 --adds --drops

# Trade workshop: every trade involving Justin Jefferson
fantasyfb --team "My Team" --sims 1000 --trades "Justin Jefferson"

# Multi-player trade: lock CMC in, search complementary pieces
fantasyfb --team "My Team" --sims 1000 --trades all --given "Christian McCaffrey"

# Best-ball league
fantasyfb --team "My Team" --sims 5000 --bestball
```

## Flags

### Identifying the team / week

| Flag        | Type | Default                  | Meaning                                                            |
| ----------- | ---- | ------------------------ | ------------------------------------------------------------------ |
| `--team`    | str  | required if ambiguous    | Yahoo fantasy team name                                            |
| `--season`  | int  | most recent              | Season year, e.g. `2026`                                           |
| `--week`    | int  | current week             | Week to project from                                               |

### Simulation knobs

| Flag                  | Type | Default | Meaning                                                                                                  |
| --------------------- | ---- | ------- | -------------------------------------------------------------------------------------------------------- |
| `--sims`              | int  | —       | Number of Monte Carlo season simulations. More = smoother estimates, longer runs. 1,000-10,000 is typical |
| `--injurytries`       | int  | 10      | Retries on flaky Yahoo injury-status calls                                                               |
| `--earliest`          | int  | —       | Earliest week to pull stats from, as `YYYYWW` (e.g. `202407`)                                            |
| `--bestball`          | flag | off     | Score the league as best-ball (bench contributes per-week max)                                           |

### Analysis sheets

All optional — turn on the ones you want.

| Flag         | Type | Default | Meaning                                                                                              |
| ------------ | ---- | ------- | ---------------------------------------------------------------------------------------------------- |
| `--adds`     | flag | off     | Sheet: every viable add, with expected earnings delta                                                |
| `--drops`    | flag | off     | Sheet: ranked drops by lowest earnings cost                                                          |
| `--pickups`  | str  | —       | Focused waiver analysis. Pass a comma-separated player list or `all`                                 |
| `--trades`   | str  | —       | Trade explorer. Pass player names or `all`                                                            |
| `--given`    | str  | —       | Players locked into the trade when using `--trades` (for multi-player builds)                         |
| `--deltas`   | flag | off     | Per-game deltas: how much each matchup outcome shifts everyone's earnings (Deltas sheet in Excel, Rooting guide tab in HTML) |

### Output

| Flag       | Type | Default               | Meaning                                                                                         |
| ---------- | ---- | --------------------- | ----------------------------------------------------------------------------------------------- |
| `--output` | str  | `~/Documents/<team>/` | Directory to write the report(s) into. Auto-creates `<team>/<season>/` subdirs if not present |
| `--format` | str  | `excel`               | `excel`, `html` (one self-contained interactive report), or `both`                               |
| `--drop-safe-threshold`  | float | `-4`      | HTML report: a drop whose expected-earnings change is above this is labelled "Safe to cut"       |
| `--drop-depth-threshold` | float | `-12`     | HTML report: above this (but not safe to cut) is "Depth", anything lower is "Keep"               |
| `--payouts`| str  | `60,30,10`            | Comma-separated 1st/2nd/3rd payouts used for the earnings calculation                            |

## Output files

```
<output>/FantasyFootballProjections_<Weekday>Week<N>.xlsx
```

`_BestBall` is appended when `--bestball` is set. With `--format html` (or
`both`) the same name is used with an `.html` extension.

The HTML report is a single file with everything inlined, so it opens
offline and can be emailed. Use the **Viewing** menu to scope it to any
team in the league, and the tabs to move between your week, standings,
the league schedule, roster moves, and free agents. The Moves tab only
appears when at least one of `--adds`, `--pickups`, `--drops` or
`--trades` was passed.

The workbook always has **Rosters**, **Available**, and **Standings**
sheets. Other sheets appear conditionally based on the analysis flags
you passed.

## See also

- [API: `League`](../api/league.md) — the underlying class the CLI
  drives. Useful if you want to script bespoke analyses.
- [Architecture](../architecture.md) — where projections, simulation,
  and Yahoo I/O live in the package layout.
