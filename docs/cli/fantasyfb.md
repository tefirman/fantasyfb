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
| `--games`             | int  | —       | Number of prior games used as the per-player rate prior                                                  |
| `--basaloppstringtime`| str  | —       | Four comma-separated weights for the basal / opponent / depth-chart / time-decay rate factors            |
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
| `--deltas`   | flag | off     | Per-game delta sheet — how much each matchup outcome shifts everyone's earnings                       |

### Output

| Flag       | Type | Default               | Meaning                                                                                         |
| ---------- | ---- | --------------------- | ----------------------------------------------------------------------------------------------- |
| `--output` | str  | `~/Documents/<team>/` | Directory to write the spreadsheet into. Auto-creates `<team>/<season>/` subdirs if not present |
| `--payouts`| str  | `60,30,10`            | Comma-separated 1st/2nd/3rd payouts used for the earnings calculation                            |

## Output files

```
<output>/FantasyFootballProjections_<Weekday>Week<N>.xlsx
```

`_BestBall` is appended when `--bestball` is set.

The workbook always has **Rosters**, **Available**, and **Standings**
sheets. Other sheets appear conditionally based on the analysis flags
you passed.

## See also

- [API: `League`](../api/league.md) — the underlying class the CLI
  drives. Useful if you want to script bespoke analyses.
- [Architecture](../architecture.md) — where projections, simulation,
  and Yahoo I/O live in the package layout.
