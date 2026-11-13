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

The page is refreshed every morning on a laptop by `scripts/sfb_daily.sh`, which launchd runs at 8:00 AM (or when the laptop wakes, if it was asleep then; nothing runs while it is shut down). GitHub's scheduled Actions started hours late or not at all, so the `SFB refresh` workflow (`.github/workflows/sfb-refresh.yml`) now runs only when started by hand, from the Actions tab or the GitHub mobile app, as a backup. Both do the same steps:

1. Update `injured_list.csv` in `tefirman/fantasy-data`. `sfb-field injuries` pulls the field's current rosters (one Sleeper request per league, about a minute) and lists widely rostered players whose Sleeper status and the list disagree. If there are any, headless Claude Code researches each one with web search and edits only that file, `sfb-field check-injuries` validates the edit, and the change is committed and pushed. This step never blocks the refresh. The prompt is `.github/prompts/sfb-injuries.md`, and the model is pinned to Sonnet 5.5.
2. Collect and simulate the field, retrying failed leagues once, and stop without publishing if any still fail or Sleeper rate-limits the run.
3. Build the page with the analytics ID, sanity-check it, and push it to `tefirman/sfb-odds`.

Both read the league list and saved leaderboard from `inputs/` in `tefirman/sfb-odds`, so re-upload `inputs/SFB16Leaderboard.html` and `inputs/leagues.csv` there when teams change. Review the injury commits in `fantasy-data` and revert any bad row; a manual `/update-injuries` still works and wins, since the next scan only touches players it finds uncovered.

### The laptop job

The script works in its own clones under `~/.sfb-daily` (this repo at `main`, `fantasy-data`, and `sfb-odds` as `site/`, plus a venv), resets them to their remotes on every run, and pushes with your own git credentials over SSH, so your working copies are never touched. The Claude step runs on your Claude subscription, not the API: the script never passes an API key. It also runs Claude with `--restricted` and `--strict-mcp-config`, so your own Claude settings, hooks and MCP servers are ignored and file access is confined to `~/.sfb-daily`, and with only web search, web fetch, read, and an edit of the one list allowed. Output goes to `~/Library/Logs/sfb-daily.log`, and a macOS notification says when the page is published or a run fails.

One-time setup:

```bash
git clone git@github.com:tefirman/fantasyfb.git ~/.sfb-daily/fantasyfb
# a long-lived sign-in for unattended runs (a normal one can lapse within days)
claude setup-token
security add-generic-password -U -s sfb-daily-claude -a "$USER" -w   # paste the token at the prompt
cp ~/.sfb-daily/fantasyfb/scripts/com.tefirman.sfb-daily.plist ~/Library/LaunchAgents/
# set SFB_GA_ID in the copy to the Google Analytics measurement ID, then:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tefirman.sfb-daily.plist
```

The script finds `claude` on the PATH, or else the copy bundled with the VS Code extension; set `CLAUDE` in the plist to use another. To try it without committing or publishing anything, run `SFB_GA_ID=G-... ~/.sfb-daily/fantasyfb/scripts/sfb_daily.sh --dry-run`, which prints the injury diff and leaves the page at `~/.sfb-daily/sfb/index.html`. `launchctl kickstart gui/$(id -u)/com.tefirman.sfb-daily` starts a real run now, and `launchctl bootout gui/$(id -u)/com.tefirman.sfb-daily` turns the job off.

### The GitHub workflow

Run it from the Actions tab or the GitHub app; it has no inputs. One-time setup in this repo's settings:

- Secret `SFB_ODDS_PUSH_TOKEN`: a fine-grained personal access token with Contents: write on `tefirman/sfb-odds` only.
- Secret `FANTASY_DATA_PUSH_TOKEN`: the same, on `tefirman/fantasy-data` only.
- Secret `ANTHROPIC_API_KEY`: the workflow's Claude step bills the API, about $0.50 on a run with something to research.
- Variable `SFB_GA_ID`: the Google Analytics measurement ID. The run fails without it instead of publishing a page with no analytics.

Sleeper's full player list is cached per UTC day, so re-running the workflow the same day does not request it again.

## Notes

- The header and footer show when the simulations finished (the modification time of `odds.csv`), in the viewer's locale.
- The team that opens by default comes from `--default-team` (a Sleeper handle, `tefirman51` unless changed; pass an empty string for none). A `#league-roster` in the URL takes precedence.
- The page links Google Fonts (Barlow); the design tokens and logo are inlined. Pass `--ga-id G-XXXXXXXXXX` to `build.py` to add Google Analytics 4 page-view counting, which loads `googletagmanager.com`. Without the flag the page sends nothing else anywhere.
- The round sizes and average weights live in `fantasyfb.sfb.Rules`. Update them there when the SFB publishes its final cut sizes after week 11.
- The 17 MyFantasyLeague leagues are not simulated, so their teams are not searchable.
