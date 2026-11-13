# SFB playoff odds page

A static page with field-wide Scott Fish Bowl odds: search a team by Sleeper handle, name, or league name, or see how many points it takes to qualify on points and who the most likely champions are. It is one self-contained HTML file with the odds embedded, so it needs no server and can be opened from disk or hosted on any static host (GitHub Pages, for example). It is not part of the Cloud Run web app and is kept out of that Docker image.

## Update it

The odds come from the `sfb-field` command (see `fantasyfb.sfb`). From the repo root:

```bash
# once per season: league IDs and names from a saved copy of the leaderboard page
sfb-field leagues notes/SFB16Leaderboard.html --out-dir sfb

# each refresh: pull the leagues from Sleeper (about 20 minutes, rate-limited), then simulate (under a minute)
sfb-field collect sfb/leagues.csv --out-dir sfb/data
sfb-field simulate sfb/data --out-dir sfb

# build the page
python app/sfb_site/build.py --odds sfb/odds.csv --cut-line sfb/cut_line.csv \
    --leaderboard notes/SFB16Leaderboard.html --data sfb/data --players sfb/players.csv --out sfb/index.html
```

`collect` can be re-run for a few leagues with `--only ID,ID`, and a refresh only needs `collect` and `simulate` again. The leaderboard page is only read for names, so it does not need to be re-saved unless teams change.

## Automatic refresh

`.github/workflows/sfb-refresh.yml` does the steps above daily at 6:17 AM Pacific (14:17 UTC, so 7:17 AM during daylight time) and on demand from the Actions tab, then pushes the page to `tefirman/sfb-odds`. It reads the league list and saved leaderboard from `inputs/` in that repo, so re-upload `inputs/SFB16Leaderboard.html` and `inputs/leagues.csv` there when teams change. One-time setup in this repo's settings:

- Secret `SFB_ODDS_PUSH_TOKEN`: a fine-grained personal access token with Contents: write on `tefirman/sfb-odds` only.
- Variable `SFB_GA_ID`: the Google Analytics measurement ID. The run fails without it instead of publishing a page with no analytics.

On Sundays and Wednesdays (scheduled runs) and on manual runs that do not skip it, the workflow first updates `injured_list.csv` in `tefirman/fantasy-data`: `sfb-field injuries` scans the rosters the previous run saved (cached between runs) against today's Sleeper statuses, headless Claude Code researches each uncovered player with web search and edits only that file, `sfb-field check-injuries` validates the edit, and a bot commits it. The prompt is `.github/prompts/sfb-injuries.md`. This step never blocks the refresh, and the first run has no saved rosters, so it skips the scan. Extra setup for it: secret `ANTHROPIC_API_KEY`, and secret `FANTASY_DATA_PUSH_TOKEN` (a fine-grained PAT with Contents: write on `tefirman/fantasy-data` only). Review the bot's commits in that repo and revert any bad row; a manual `/update-injuries` still works and wins, since the next scan only touches players it finds uncovered.

To try the injury step without changing anything, run the workflow by hand from the Actions tab with `dry_run` checked. It researches and validates, shows the proposed diff and summary on the run's summary page, and skips the commit and the whole refresh.

The injury step costs about $0.50 in Claude tokens on a day with something to research, so scheduled runs do it only on Sundays and Wednesdays. A manual run does it too, unless you check `skip_injuries`; a dry run ignores that box.

Failed leagues are retried once, and the run stops without publishing if any still fail or Sleeper rate-limits it. Sleeper's full player list is cached per UTC day, so re-running the workflow the same day does not request it again.

## Notes

- The header and footer show when the simulations finished (the modification time of `odds.csv`), in the viewer's locale.
- The team that opens by default comes from `--default-team` (a Sleeper handle, `tefirman51` unless changed; pass an empty string for none). A `#league-roster` in the URL takes precedence.
- The page links Google Fonts (Barlow); the design tokens and logo are inlined. Pass `--ga-id G-XXXXXXXXXX` to `build.py` to add Google Analytics 4 page-view counting, which loads `googletagmanager.com`. Without the flag the page sends nothing else anywhere.
- The round sizes and average weights live in `fantasyfb.sfb.Rules`. Update them there when the SFB publishes its final cut sizes after week 11.
- The 17 MyFantasyLeague leagues are not simulated, so their teams are not searchable.
