# `sfb-field`

Field-wide odds for the Scott Fish Bowl (SFB). The SFB plays hundreds of 12-team Sleeper leagues, but its playoffs run across the whole field at once: 13 or more wins qualifies automatically, the rest of the field is filled by points, and weeks 12-17 are scored across all leagues together. A team's real odds therefore depend on every other league, which a single-league simulation can't capture. `sfb-field` collects the leagues, simulates them together, and writes per-team odds of qualifying, of starting each playoff round, and of winning.

It needs no credentials, only the public Sleeper API and a saved copy of the SFB leaderboard page.

## Usage

```bash
sfb-field leagues leaderboard.html --out-dir sfb/       # once per season
sfb-field collect sfb/leagues.csv --out-dir sfb/data    # pulls Sleeper, about 20 minutes
sfb-field simulate sfb/data --out-dir sfb               # offline, under a minute
```

The three steps are separate so that the slow, network-bound one (`collect`) can be done once and the simulation re-run as often as you like. Run output is written to `sfb/` in the repo root, which is gitignored. The public odds page is refreshed from these same steps every day by a GitHub Action, so you only need to run them yourself for a local run (see [Automatic refresh](#automatic-refresh)).

### `leagues`

Reads the league IDs out of a saved copy of the SFB leaderboard page, so the SFB's server isn't asked again. Writes `leagues.csv` (platform, league ID, team count) and `leaderboard_snapshot.csv` (every team's handle and name, used later to make the odds searchable).

| Flag        | Default | Meaning                              |
| ----------- | ------- | ------------------------------------ |
| `leaderboard` | none  | Saved leaderboard HTML               |
| `--out-dir` | `.`     | Where to write the two CSV files     |

### `collect`

Pulls each Sleeper league's settings, rosters, and schedule into parquet files (`rosters.parquet` is what the [`injuries`](#injuries-and-check-injuries) scan reads), about 18 requests per league. Sleeper's full player list is fetched once and cached per UTC day, so re-running the same day does not request it again. Requests go through a shared limiter and the command stops at the first HTTP 429. The 400 Sleeper leagues of the 2026 field took about 20 minutes. A failed league is reported on stderr and the command exits 1, so you can re-run just those with `--only`.

| Flag                      | Default | Meaning                                                      |
| ------------------------- | ------- | ------------------------------------------------------------ |
| `leagues`                 | none    | `leagues.csv` from the previous step                         |
| `--out-dir`               | none    | Where to write the parquet files (required)                  |
| `--workers`               | 3       | Parallel workers                                             |
| `--max-calls-per-minute`  | 500     | Request ceiling. Sleeper asks for fewer than 1,000           |
| `--only`                  | all     | Comma-separated league IDs to (re)collect                    |

### `simulate`

Runs the whole field offline. Every player gets one random draw per week and simulation that all teams starting him share, so a team's score keeps its own mean and variance but teams move together. That correlation is what gives the points cut line a realistic spread.

| Flag             | Default | Meaning                                            |
| ---------------- | ------- | -------------------------------------------------- |
| `data`           | none    | Directory written by `collect`                     |
| `--out-dir`      | `.`     | Where to write the output files                    |
| `--num-sims`     | 1000    | Regular-season simulations                         |
| `--playoff-reps` | 20      | Playoff replays per regular-season simulation      |
| `--seed`         | 1       | Random seed                                        |

### `injuries` and `check-injuries`

`sfb-field injuries sfb/data --out-dir scan` lists the injuries the odds depend on that `injured_list.csv` does not cover yet. It reads `rosters.parquet` (written by `collect`) and Sleeper's player list, which the run already has cached, so it makes no extra Sleeper requests. A player counts once he is rostered on `--min-teams` field teams (default 20), bench and IR included. It writes `new_injuries.csv` (out designation, no `until` reaching the week) and `old_injuries.csv` (listed, but no longer carrying a designation, so probably back early). `--injured-list` takes a path or URL and defaults to the live list.

`sfb-field check-injuries before.csv after.csv` validates an edited list before it is committed: the same four columns, `until` a whole week from 1 to 18, no duplicate players, only players Sleeper knows, and at most `--max-changes` (default 25) rows added, removed or changed. It exits 1 with the reasons if any check fails.

The scan only looks at players on `--min-teams` or more field teams, so a rarely rostered player who is hurt still depends on the template league's rosters and the manual list.

## Automatic refresh

The odds page at [taylorfirman.com/sfb-odds](https://taylorfirman.com/sfb-odds/) is rebuilt every day at 6:17 AM Pacific by the `SFB refresh` GitHub Action (`.github/workflows/sfb-refresh.yml`), and it can be run on demand from the repo's Actions tab. Each run does the following:

1. Updates `injured_list.csv` in `tefirman/fantasy-data`. `injuries` scans the rosters the previous run saved against today's Sleeper statuses, headless Claude Code researches each uncovered player with web search and edits only that file, `check-injuries` validates the edit, and a bot commits it. This step never blocks the refresh, and the first run has no saved rosters, so it skips the scan.
2. Runs `collect` and `simulate`. Failed leagues are retried once, and the run stops without publishing if any still fail or Sleeper rate-limits it.
3. Builds the page with `app/sfb_site/build.py` and pushes it to `tefirman/sfb-odds`.

Running the workflow by hand with `dry_run` checked tries the injury step without changing anything: it researches and validates, shows the proposed diff on the run's summary page, and skips the commit and the refresh. Review the bot's commits in `fantasy-data` and revert any bad row. A manual `/update-injuries` run still works and wins, since the next scan only touches players it finds uncovered.

The league list and saved leaderboard are read from `inputs/` in `tefirman/sfb-odds`, so re-upload them there when teams change. The secrets and variables the workflow needs are listed in [`app/sfb_site/README.md`](https://github.com/tefirman/fantasyfb/blob/main/app/sfb_site/README.md#automatic-refresh).

## Output

| File           | Contents                                                                                                   |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `odds.csv`     | One row per team: `qualify`, `reach_wild_card_2` through `reach_finals`, `win`, plus expected `wins`, `points`, and `avg_ppg` |
| `cut_line.csv` | The points total of the last team to qualify on points, one row per simulation                              |
| `players.csv`  | One row per player: `qual_swing` and `playoff_swing`, and how widely he is started                          |

`qual_swing` is the change in a team's chance of qualifying if the player has a one-standard-deviation better stretch over the remaining regular-season weeks. `playoff_swing` is the change in expected playoff rounds advanced (0 to 6, for teams that qualified) for a better stretch over weeks 12-17. Players started on fewer than 50 teams are too noisy to rank and are left off the page.

The static odds page in `app/sfb_site/` (`build.py`) turns these files into a single HTML file you can host anywhere static. It has a search by Sleeper handle, team name, or league name, the cut-line distribution, and the player swing charts. It is not part of the PyPI package.

## Rules and limits

- The round sizes and average weights live in `fantasyfb.sfb.Rules`, because the SFB publishes the final cut sizes after week 11. Change them there when the real numbers are out.
- Leagues on MyFantasyLeague (17 of 417 in 2026) are listed by `leagues` but not simulated yet.
- A league whose scoring or roster spots differ from the template is refused rather than approximated.
- The 13-win line alone is a lower bound on qualifying, since the points-based remainder depends on every league. A single league analyzed through the [web app](../web-app.md) shows only that lower bound.
- The `fantasyfb` command can't analyze Sleeper leagues yet. Use the web app or the `League` API for a single SFB league.

For scripting, `fantasyfb.sfb` exposes `FieldData`, `simulate_field`, `FieldResult`, and `Rules`.
