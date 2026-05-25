# `salary-cap-draft`

Interactive salary-cap (auction) draft cockpit (V2). Loads your Yahoo
league, builds a board with VORP-driven dollar values + market
inflation, and presents a snake-parity REPL: nomination drain-score,
hypothetical bid analysis, per-team budget tracking, and an
auto-pilot mock simulator. Persists pick history to a CSV so you can
pause and resume.

## Usage

```bash
salary-cap-draft --team "My Team" [options]
```

The first time it asks whether you want to use your Yahoo team names
or customize them; subsequent resumes pick up team names from the
in-progress CSV.

## Common recipes

```bash
# Live auction from scratch, default $200 cap
salary-cap-draft --team "My Team"

# Custom cap and minimum bid
salary-cap-draft --team "My Team" --salary-cap 300 --min-bid 2

# Pre-draft for an upcoming season
salary-cap-draft --team "My Team" --season 2026

# Keeper league: CSV with name,fantasy_team,salary (last year's price)
# Final keeper price = salary + --keeper-surcharge (default $5)
salary-cap-draft --team "My Team" --keepers keepers.csv

# Resume a paused draft
salary-cap-draft --team "My Team" --inprogress DraftProgressSalaryCap.csv
```

## Required flags

| Flag      | Meaning                                          |
| --------- | ------------------------------------------------ |
| `--team`  | Yahoo team name to draft for                     |

## Common flags

| Flag                 | Default                              | Meaning                                                                                                                       |
| -------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `--salary-cap`       | 200                                  | Per-team auction cap                                                                                                          |
| `--min-bid`          | 1                                    | Minimum bid per player                                                                                                        |
| `--season`           | most recent completed                | Yahoo season year. **Pass explicitly before the season starts** (e.g. `--season 2026` in May 2026)                            |
| `--keepers`          | —                                    | Path to keepers CSV. Columns: `name`, `fantasy_team`, `salary` (last year's winning price)                                    |
| `--keeper-surcharge` | 5                                    | Dollars added to each keeper's last-year salary. Set to `0` to treat the CSV `salary` as the final keeper price                |
| `--exclude`          | —                                    | Comma-separated player names to filter out of views                                                                            |
| `--inprogress`       | —                                    | Path to a `DraftProgressSalaryCap.csv` from a paused draft. Also accepts the legacy V1 format (`salary` column)                |
| `--output`           | `DraftProgressSalaryCap.csv` (or `--inprogress` path) | Where to save the running pick log                                                                       |
| `--payouts`          | —                                    | Comma-separated 1st/2nd/3rd payouts                                                                                            |

## View tuning

| Flag                   | Default | Meaning                                                                  |
| ---------------------- | ------- | ------------------------------------------------------------------------ |
| `--limit-per-position` | 5       | Rows per position in the `best` view                                     |
| `--nominate-limit`     | 10      | Rows in the `nominate` drain-score view                                  |

## Interactive commands

Once running, the prompt accepts:

| Command            | What it does                                                                          |
| ------------------ | ------------------------------------------------------------------------------------- |
| `<player name>`    | Tab-completes; starts a real nomination — prompts for winning team and bid            |
| `best`             | Top-N per position by need-adjusted VORP, with `salary_value`, `inflated_value`, and `max_my_bid` |
| `nominate`         | Drain-score ranking: high market value, low fit for you (nominate these to drain opponents' budgets) |
| `whatif`           | Re-rank `best` after a hypothetical bid on a given player                              |
| `lookup`           | Detailed view of one player (drafted or available)                                     |
| `roster`           | My Team's picks with bids paid                                                         |
| `budgets`          | Per-team budget status — remaining $, slots filled, max bid                            |
| `exclude`          | Add a player to the per-session exclude list                                           |
| `sim`              | Run a full season simulation with current rosters                                      |
| `random`           | Auto-simulate one nomination + bidding round (Vickrey-style)                           |
| `random til full`  | Auto-simulate the rest of the draft to completion                                      |
| `go back`          | Revert the previous pick                                                               |
| `help`             | Full command list                                                                      |
| `exit`             | Quit (progress is already saved on every pick)                                         |

Tab completion is on for player names and team names where applicable.

## Keeper CSV format

```csv
name,fantasy_team,salary
Christian McCaffrey,My Team,45
Justin Jefferson,The Algorithm,50
```

- `salary` is **last year's winning price**. The actual keeper cost
  charged against the team's cap is `salary + --keeper-surcharge`
  (default `+$5`).
- `fantasy_team` accepts your original Yahoo team name as an alias
  for `My Team` (the CLI renames your team during setup).
- Cap validation fires at startup: if a team's total keeper spend
  would leave fewer dollars than they need to fill remaining slots
  at `--min-bid`, the CLI hard-errors with a fix-up message before
  the draft begins.

## Output

`DraftProgressSalaryCap.csv` is rewritten on every pick (columns:
`name`, `fantasy_team`, `winning_bid`). To resume after a crash, pass
it via `--inprogress`. The format is stable; rotating between
machines mid-draft works as long as you keep the file in sync.

Legacy V1 progress files (with `salary` instead of `winning_bid`) are
accepted automatically — the column is renamed transparently on load.

## See also

- [`snake-draft`](snake-draft.md) — snake-draft cockpit; the salary-cap
  side mirrors its UX.
- [`draft-prep`](draft-prep.md) — run *before* the draft for tiers,
  values, and VORP.
- [API: `fantasyfb.drafts`](../api/drafts.md) — `compute_salary_values`,
  `MockSalaryCapDraft`, `backtest_salary_values`, salary-cap cockpit
  views.
