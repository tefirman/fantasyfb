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
    --leaderboard notes/SFB16Leaderboard.html --data sfb/data --out sfb/index.html
```

`collect` can be re-run for a few leagues with `--only ID,ID`, and a refresh only needs `collect` and `simulate` again. The leaderboard page is only read for names, so it does not need to be re-saved unless teams change.

## Notes

- Odds are through the last completed week in the collected data, shown at the top of the page.
- The round sizes and average weights live in `fantasyfb.sfb.Rules`. Update them there when the SFB publishes its final cut sizes after week 11.
- The 17 MyFantasyLeague leagues are not simulated, so their teams are not searchable.
