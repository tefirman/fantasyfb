# `draft-prep`

Pre-draft analytics. Generates tier sheets, VORP-vs-ADP value
deltas, "trap" lists of overdrafted players, and mock-draft
simulations. Sub-command style — pick one of `tiers`, `values`,
`traps`, `mock`.

## Usage

```bash
draft-prep <subcommand> [options]
```

Every subcommand requires `--team`. Most accept `--output` to dump
the result to CSV. Every subcommand also accepts `--refresh-cache` to
bypass the local nflreadpy cache and force a fresh download of
stats/schedule/roster data for that run — see
[caching](../architecture.md#nflreadpy-caching).

## Subcommands

### `tiers`

Per-position tier sheet. Groups players into tiers using a z-score
gap heuristic so you can see where the cliffs are.

```bash
draft-prep tiers --team "My Team"
draft-prep tiers --team "My Team" --position RB --top 40
```

| Flag             | Default | Meaning                                                              |
| ---------------- | ------- | -------------------------------------------------------------------- |
| `--team`         | —       | Yahoo team name                                                      |
| `--position`     | all     | Restrict to one position (`QB`/`RB`/`WR`/`TE`/`K`/`DEF`)             |
| `--top`          | 30      | Rows per position                                                    |
| `--gap-z`        | 1.0     | Tier-break z-score threshold                                         |
| `--top-n`        | 30      | Players per position considered for tiering (rest get `tier=NaN`)    |
| `--max-per-tier` | 12      | Maximum players in a single tier before forcing a split              |
| `--output`       | —       | Optional CSV path                                                    |

### `values`

Biggest projection-vs-ADP deltas — players the model thinks you'll
get at a discount.

```bash
draft-prep values --team "My Team" --adp ADP.csv
draft-prep values --team "My Team" --adp ADP.csv --top 60 --min-vorp 1.5
```

`--adp` expects a CSV with `Player`, `POS`, and `AVG` columns (`Team`
is optional). See
[`examples/adp_sample.csv`](../../examples/adp_sample.csv) for the
expected shape — export ADP data from FantasyPros, Sleeper, or Yahoo
and rename columns to match if needed.

| Flag             | Default  | Meaning                                                              |
| ---------------- | -------- | -------------------------------------------------------------------- |
| `--team`         | —        | Yahoo team name                                                      |
| `--adp`          | required | Path to ADP CSV                                                      |
| `--top`          | 40       | Rows to show                                                         |
| `--gap-z`        | 1.0      | Tier-break z-score threshold                                         |
| `--top-n`        | 30       | Players per position considered for tiering                          |
| `--max-per-tier` | 12       | Maximum players in a single tier                                     |
| `--min-vorp`     | 0.0      | Minimum per-game VORP to include (default: above replacement only)   |
| `--exclude`      | `K,DEF`  | Comma-separated positions to exclude (convention-drafted regardless) |
| `--output`       | —        | Optional CSV path                                                    |

### `traps`

Inverse of `values` — players going earlier than the model thinks
they should. Used as an "avoid" list during the draft.

```bash
draft-prep traps --team "My Team" --adp ADP.csv
draft-prep traps --team "My Team" --adp ADP.csv --max-adp-round 8
```

Same flags as `values`, plus:

| Flag              | Default | Meaning                                                            |
| ----------------- | ------- | ------------------------------------------------------------------ |
| `--max-adp-round` | 10      | Only flag traps inside the first N rounds (later rounds are noise) |

### `mock`

Run mock drafts with ADP-based opponents.

```bash
draft-prep mock --team "My Team" --adp ADP.csv --my-pick 7
draft-prep mock --team "My Team" --adp ADP.csv --my-pick 7 --sims 50 --seed 42
```

| Flag             | Default          | Meaning                                                                                          |
| ---------------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `--team`         | —                | Yahoo team name                                                                                  |
| `--adp`          | required         | Path to ADP CSV                                                                                  |
| `--my-pick`      | required         | Your 1-indexed draft slot                                                                        |
| `--strategy`     | `vorp`           | User pick strategy: `bpa`, `vorp`, or `need`                                                     |
| `--sims`         | 1                | Number of mock drafts to run                                                                     |
| `--noise-slope`  | 0.1              | Per-pick growth of opponent ADP-noise stdev (pick 10 → stdev 1, pick 100 → stdev 10)             |
| `--noise-floor`  | 1.0              | Minimum opponent ADP-noise stdev at the top of the draft                                          |
| `--linear`       | off              | Use linear (non-snake) draft order                                                                |
| `--seed`         | —                | RNG seed for reproducibility                                                                      |
| `--output`       | —                | Optional CSV path                                                                                |

When `--sims > 1` the summary shows the top-3 most-frequently-drafted
players per round; useful for spotting tier patterns vs. one-off
outliers.

## See also

- [`snake-draft`](snake-draft.md) — once the draft is live.
- [API: `fantasyfb.drafts.tools`](../api/drafts.md) — `compute_vorp`,
  `assign_tiers`, `MockDraft` if you want to call them from Python.
