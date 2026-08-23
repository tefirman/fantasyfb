# `snake-draft`

Interactive snake-draft cockpit (redraft, V2). Loads your league from
Yahoo or Sleeper, or synthesizes a fully mock league with no real
platform (`--platform generic`, the default), overlays a VORP/tier/ADP
board, and presents an interactive REPL with suggestions as the draft
progresses. Persists pick history to a CSV so you can pause and
resume.

## Usage

```bash
snake-draft --team "My Team" --adp ADP.csv [options]
```

The first time it asks whether you want to provide a custom draft
order; subsequent resumes pick up the order from the in-progress CSV.

## Common recipes

```bash
# Live mock draft from scratch (--platform generic, 12 teams, PPR
# scoring -- prompts for both if not passed)
snake-draft --team "My Team" --adp ADP.csv

# Mock draft with a specific team count and scoring system
snake-draft --team "My Team" --adp ADP.csv --num-teams 10 --mock-scoring half_ppr

# Draft against your real Yahoo league instead of a mock
snake-draft --team "My Team" --adp ADP.csv --platform yahoo

# Draft against a Sleeper league instead
snake-draft --team "My Team" --adp ADP.csv --platform sleeper --sleeper-league-id 123456789

# Resume a paused draft
snake-draft --team "My Team" --adp ADP.csv --inprogress DraftProgress.csv

# Pre-draft for an upcoming season (--platform yahoo defaults to last completed season)
snake-draft --team "My Team" --adp ADP.csv --platform yahoo --season 2026

# Exclude players you'd never draft
snake-draft --team "My Team" --adp ADP.csv --exclude "Tom Brady,Cam Newton"

# Best-ball scoring/roster settings (defaults to Underdog; pass dk for DraftKings)
snake-draft --team "My Team" --adp ADP.csv --bestball

# Third-Round Reversal at round 3 (matches Sleeper's reversal_round setting)
snake-draft --team "My Team" --adp ADP.csv --reversal-round 3
```

## Required flags

| Flag       | Meaning                                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------- |
| `--team`   | Team to draft for — Yahoo team name (`--platform yahoo`), the Sleeper team/manager display name (`--platform sleeper`), or whatever you want to call your team (`--platform generic`) |
| `--adp`    | Path to ADP CSV. FantasyPros-style columns by default (`Player`, `POS`, `Team`, `AVG`) — see `--adp-*-col` below |

## Common flags

| Flag                   | Default                              | Meaning                                                                                                                       |
| ----------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `--season`              | most recent completed                | Yahoo season year. **Pass explicitly before the season starts** (e.g. `--season 2026` in May 2026). Ignored with `--platform sleeper`/`generic` — neither is tied to a real, season-scoped league |
| `--platform`            | `generic`                            | Fantasy platform backend: `yahoo`, `sleeper`, or `generic` (fully synthetic mock draft, no real league — see issue #47)      |
| `--sleeper-league-id`   | —                                    | Numeric Sleeper league ID (from the league URL). Required with `--platform sleeper`                                          |
| `--num-teams`           | 12                                   | Number of teams for a `--platform generic` mock draft. Prompted for interactively if not given                               |
| `--mock-scoring`        | `ppr`                                | Scoring system for a `--platform generic` mock draft: `standard`, `half_ppr`, or `ppr`. Prompted for interactively if not given |
| `--roster-spots`        | fixed default shape                  | Custom roster shape for a `--platform generic` mock draft, as comma-separated `POSITION=COUNT` pairs, e.g. `QB=1,RB=2,WR=2,TE=1,W/R/T=1,K=1,DEF=1,BN=7` (flex codes: `W/T`, `W/R/T`, `Q/W/R/T` for superflex). Prompted for interactively if not given |
| `--fresh-draft`         | off                                  | Ignore each team's current roster and treat every player as available, instead of preserving it as a keeper — useful for mock-drafting a Sleeper league that already has real, mid-season rosters |
| `--exclude`             | —                                    | Comma-separated player names to filter out of views                                                                            |
| `--inprogress`          | —                                    | Path to a `DraftProgress.csv` from a paused draft                                                                              |
| `--output`              | `DraftProgress.csv` (or `--inprogress` path) | Where to save the running pick log                                                                                    |
| `--payouts`             | —                                    | Comma-separated 1st/2nd/3rd payouts for earnings projections                                                                   |
| `--bestball`            | off                                  | Enable best-ball scoring/roster settings and switch `sim`/`simadd` to `bestball_sims`. Bare flag defaults to `underdog`; pass a platform name (`underdog`, `dk`) to match its rules |
| `--reversal-round`      | 0 (disabled)                         | Apply Third-Round Reversal at this round number — that round repeats the previous round's direction instead of flipping back, then normal snake alternation resumes (matches Sleeper's `reversal_round` setting) |
| `--refresh-cache`       | off                                  | Bypass the local nflreadpy cache and force a fresh download of stats/schedule/roster data for this run (see [caching](../architecture.md#nflreadpy-caching)) |

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
| ---------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `--limit-per-position` | 5       | Rows per position in the `best` view                                                                                             |
| `--nearest-window`     | 2       | ADP window in rounds for the `nearest` view                                                                                       |
| `--random-pool-size`   | 8       | Size of the top-VORP pool the `random` / mock-opponent picks sample from. Smaller = more deterministic, larger = more chaos      |
| `--simadd-limit`       | 3       | Default players per position simulated by `simadd` (also prompted per-run)                                                        |

## Interactive commands

Once running, the prompt accepts:

| Command          | What it does                                                                                                    |
| ---------------- | ----------------------------------------------------------------------------------------------------------------- |
| `<player name>`  | Tab-completes; commits the pick to whichever team is on the clock                                                |
| `best`           | Top-N available per position by need-adjusted VORP. Prompts for pool (best available / nearest ADP) and, outside `--bestball` drafts, scoring (normal / bestball) |
| `lookup`         | Detailed view of one player (drafted or available)                                                               |
| `exclude`        | Add a player to the per-session exclude list                                                                     |
| `roster`         | Your roster as drafted so far                                                                                    |
| `sim`            | Run a full season simulation with current rosters                                                                |
| `simadd`         | Sim top-N available per position; ranks by win/playoff/earnings delta. Same pool/scoring prompts as `best`, plus players-per-position count (best-available pool only) |
| `random`         | Auto-pick for the team on the clock (samples from `--random-pool-size`)                                          |
| `random til me`  | Auto-pick until it's your turn again                                                                             |
| `go back`        | Undo the last pick                                                                                                |
| `help`           | Full command list                                                                                                 |
| `exit`           | Quit (progress is already saved on every pick)                                                                    |

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
