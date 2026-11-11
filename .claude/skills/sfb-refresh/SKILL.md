---
name: sfb-refresh
description: Refresh the public Scott Fish Bowl playoff odds page. Re-collects the Sleeper leagues, re-simulates the field, rebuilds sfb/index.html with the analytics flag, and (only with explicit approval) publishes it to tefirman/sfb-odds. Use when the user asks to "update the SFB dashboard", "refresh the SFB odds", "rebuild the SFB page", or runs /sfb-refresh.
---

# SFB Refresh

Rebuilds the static page at https://taylorfirman.com/sfb-odds/ from fresh Sleeper data. The `SFB refresh` GitHub Action (`.github/workflows/sfb-refresh.yml`) does the same thing daily; use this skill for an immediate local run, or just trigger the workflow from the Actions tab. Reference: `app/sfb_site/README.md` and `docs/cli/sfb-field.md`. Run everything from the repo root, using the `.venv` if `sfb-field` is not on the PATH.

## Procedure

1. **Check inputs.** `sfb/leagues.csv` and `notes/SFB16Leaderboard.html` must exist (they are once-per-season; do not re-run `sfb-field leagues` unless teams changed). Note the current `sfb/odds.csv` modification time so you can report how stale it was.

2. **Collect** (network-bound, about 20 minutes, rate-limited). Run in the background and do not poll:
   ```bash
   sfb-field collect sfb/leagues.csv --out-dir sfb/data 2>&1 | tee sfb/collect.log
   ```
   Exit code 1 means some leagues failed and are listed on stderr. Retry just those with `--only ID,ID`. Stop on any HTTP 429 and tell the user; never raise `--max-calls-per-minute` past the default.

3. **Simulate** (offline, under a minute):
   ```bash
   sfb-field simulate sfb/data --out-dir sfb
   ```

4. **Build the page.** Always pass `--ga-id G-1MRV3D498D`. The ID is public but deliberately not in the repo, so leaving the flag off silently ships the page without analytics.
   ```bash
   python app/sfb_site/build.py --odds sfb/odds.csv --cut-line sfb/cut_line.csv \
       --leaderboard notes/SFB16Leaderboard.html --data sfb/data --players sfb/players.csv \
       --out sfb/index.html --ga-id G-1MRV3D498D
   ```
   The "through week" comes from `sfb/data/settings.parquet`, so it advances on its own after a new collect.

5. **Sanity-check before showing anything.** Report: number of teams (expect about 4,800 for 400 Sleeper leagues of 12), no NaN in `odds.csv`, `qualify` and `win` sums plausible (win sums to about 1 across the field), `index.html` contains `googletagmanager`, and the through week matches the NFL week just played. Open `sfb/index.html` locally for the user if they want to look.

6. **Publish only with explicit go-ahead.** Pushing to `main` of `tefirman/sfb-odds` is a production deploy and has been blocked by the auto-mode classifier before, so ask first. Then:
   - Run `gh auth status`; the CLI can be on the wrong account (`tfirman_cards`), and it must be `tefirman`.
   - Clone `tefirman/sfb-odds` into the scratchpad (there is no standing local clone), copy `sfb/index.html` over `index.html`, commit to `main`, push. Earlier commits there went straight to `main`.
   - Commit message style: short, no em-dashes, e.g. "Refresh odds through week N".

## Notes

- Playoff round sizes and average weights live in `fantasyfb.sfb.Rules`. After week 11 the SFB publishes the real cut sizes, so check whether they need updating before the page is rebuilt for weeks 12-17.
- Analytics stays out of the hosted web app and the CLI HTML reports on purpose.
- 17 MyFantasyLeague leagues are not simulated, so those teams are not searchable. That is expected.
