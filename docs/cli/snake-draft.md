# `snake-draft`

Interactive snake-draft cockpit. Loads your league from Yahoo,
overlays a VORP/tier/ADP board, and presents an interactive REPL with
suggestions as the draft progresses. Persists pick history to a CSV
so you can pause and resume.

## Usage

```bash
snake-draft --team "My Team" --adp ADP.csv [options]
```

The first time it asks whether you want to provide a custom draft
order; subsequent resumes pick up the order from the in-progress CSV.

## Common recipes

```bash
# Live draft from scratch
snake-draft --team "My Team" --adp ADP.csv

# Resume a paused draft
snake-draft --team "My Team" --adp ADP.csv --inprogress DraftProgress.csv

# Pre-draft for an upcoming season (Yahoo defaults to last completed season)
snake-draft --team "My Team" --adp ADP.csv --season 2026

# Exclude players you'd never draft
snake-draft --team "My Team" --adp ADP.csv --exclude "Tom Brady,Cam Newton"
```

## Required flags

| Flag       | Meaning                                                                                                          |
| ---------- | ---------------------------------------------------------------------------------------------------------------- |
| `--team`   | Yahoo team name to draft for                                                                                     |
| `--adp`    | Path to ADP CSV. FantasyPros-style columns by default (`Player`, `POS`, `Team`, `AVG`) — see `--adp-*-col` below |

## Common flags

| Flag           | Default                | Meaning                                                                                                |
| -------------- | ---------------------- | ------------------------------------------------------------------------------------------------------ |
| `--season`     | most recent completed  | Yahoo season year. **Pass explicitly before the season starts** (e.g. `--season 2026` in May 2026)     |
| `--exclude`    | —                      | Comma-separated player names to filter out of views                                                    |
| `--inprogress` | —                      | Path to a `DraftProgress.csv` from a paused draft                                                      |
| `--output`     | `DraftProgress.csv` (or `--inprogress` path) | Where to save the running pick log                                            |
| `--payouts`    | —                      | Comma-separated 1st/2nd/3rd payouts for earnings projections                                           |

## ADP column overrides

If your ADP source uses different column names:

| Flag             | Default  |
| ---------------- | -------- |
| `--adp-name-col` | `Player` |
| `--adp-pos-col`  | `POS`    |
| `--adp-team-col` | `Team`   |
| `--adp-avg-col`  | `AVG`    |

## View tuning

| Flag                   | Default | Meaning                                                                                                                          |
| ---------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `--limit-per-position` | 5       | Rows per position in the `best` view                                                                                             |
| `--nearest-window`     | 2       | ADP window in rounds for the `nearest` view                                                                                       |
| `--random-pool-size`   | 8       | Size of the top-VORP pool the `random` / mock-opponent picks sample from. Smaller = more deterministic, larger = more chaos      |

## Interactive commands

Once running, the prompt accepts:

| Command          | What it does                                                                  |
| ---------------- | ----------------------------------------------------------------------------- |
| `<player name>`  | Tab-completes; commits the pick to whichever team is on the clock             |
| `best`           | Top-VORP players per position                                                  |
| `nearest`        | Players inside the ADP window of the current pick                              |
| `lookup`         | Look up an individual player                                                   |
| `roster`         | Your roster as drafted so far                                                  |
| `traps`          | Overdrafted players to avoid                                                   |
| `random`         | Auto-pick for the team on the clock (samples from `--random-pool-size`)        |
| `random til me`  | Auto-pick until it's your turn again                                           |
| `go back`        | Undo the last pick                                                             |
| `help`           | Full command list                                                              |
| `exit`           | Quit (progress is already saved on every pick)                                 |

Type `<command> --help` for per-command options.

## Output

`DraftProgress.csv` is rewritten on every pick. To resume after a
crash, pass that file via `--inprogress`. The format is stable across
runs; rotating between machines mid-draft works as long as you keep
the file in sync.

## See also

- [`draft-prep`](draft-prep.md) — run *before* the draft for tiers,
  values, and mock simulations.
- [`salary-cap-draft`](salary-cap-draft.md) — auction equivalent.
- [API: `fantasyfb.drafts`](../api/drafts.md) — board-building and
  view helpers exposed for scripting.
