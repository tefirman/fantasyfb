# `salary-cap-draft`

Interactive salary-cap (auction) draft tool. Loads your Yahoo league,
builds a roster pool with WAR + ADP, and lets you explore optimal
bid combinations and best-available lineups during the draft.

!!! info "V2 in progress"
    The salary-cap toolkit is mid-rewrite to feature parity with
    `snake-draft` — VORP-based valuation, drain-score nominations,
    cockpit views, and snake-style commands. Track issue
    [#11](https://github.com/tefirman/fantasyfb/issues/11) and the
    stacked PR series (#25-#28). This page documents the **current**
    `optparse`-based interface; flags and commands will change once
    V2 lands.

## Usage

```bash
salary-cap-draft --team "My Team" [options]
```

## Flags

| Flag           | Type | Default | Meaning                                                                  |
| -------------- | ---- | ------- | ------------------------------------------------------------------------ |
| `--team`       | str  | —       | Yahoo team name you're drafting                                          |
| `--budget`     | int  | 200     | Per-team auction budget                                                  |
| `--starterpct` | float| 0.875   | Fraction of budget allocated to starters (rest reserved for bench)       |
| `--limit`      | int  | 500     | Maximum top-lineup combinations considered per pick                      |
| `--keepers`    | str  | —       | Path to a CSV listing keeper players and their salaries                  |
| `--exclude`    | str  | —       | Comma-separated player names to exclude from consideration               |
| `--inprogress` | str  | —       | Path to a draft-in-progress CSV to resume from                           |
| `--output`     | str  | —       | Path to save the running draft-progress CSV                              |

## Pre-rewrite caveats

A few rough edges in the V1 interface that V2 fixes:

- Uses `optparse` instead of `argparse`, so `--help` formatting is
  older-style and some flag types are looser.
- The optimizer brute-forces lineup combinations via cartesian
  products — slow on rosters with many flex slots.
- ADP CSV path is hard-coded to a Yahoo redraft filename; you'll need
  to drop your salary-cap rankings CSV into the working directory
  under the expected name. V2 makes this configurable.

## See also

- Issue [#11](https://github.com/tefirman/fantasyfb/issues/11) — the
  V2 plan.
- [`snake-draft`](snake-draft.md) — the cockpit V2 already shipped
  for snake leagues; salary-cap is following its design.
