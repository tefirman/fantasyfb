# Connecting a league

`League(platform=...)` picks which backend supplies rosters, scoring
settings, and schedule. Three platforms are supported:

| Platform  | Setup                          | Data source                                          |
| --------- | ------------------------------- | ----------------------------------------------------- |
| `yahoo`   | OAuth app + one-time browser login | Live [Yahoo Fantasy API](https://developer.yahoo.com/fantasysports/guide/) — real rosters, real transactions |
| `sleeper` | None — just a league ID          | Live [Sleeper public API](https://docs.sleeper.com/) — real rosters, read-only |
| `generic` | None                              | Fully synthetic mock league (no real league behind it) |

`generic` is the default when `--platform` is omitted on the draft
CLIs (`snake-draft`, `salary-cap-draft`, `draft-prep`), so mock drafts
and sanity checks work out of the box with no credentials at all. The
weekly `fantasyfb` report CLI tracks a live roster over a season, so
it currently only supports `yahoo`.

See the [CLI reference](cli/index.md) — each draft CLI's page has a
"Common flags" table with the exact `--platform` /
`--sleeper-league-id` / `--num-teams` / `--mock-scoring` syntax and
worked examples.

## Sleeper

Sleeper's read API is public — no developer app, no OAuth, no
credentials. You only need the league's numeric ID, which is the
number in its URL:

```text
https://sleeper.com/leagues/<sleeper_league_id>/...
```

```python
import fantasyfb as fb
league = fb.League(platform="sleeper", sleeper_league_id="123456789012345678", name="My Team")
```

`name=` matches either the team's Sleeper display name or the
manager's Sleeper username — pass whichever `list_team_names` (or the
league's Sleeper page) shows you. If you only manage one team in that
league, you can omit `name` and it auto-selects.

Sleeper asks integrators not to pull its full `/players/nfl` payload
more than once a day; `fantasyfb` caches it locally to
`~/.cache/fantasyfb/sleeper_players.json` for 24h, so this is
transparent in normal use.

Sleeper access is read-only — there's no equivalent to Yahoo's
Read/Write scope for scripting add/drop actions.

## Generic (no live league)

For mock drafts or sanity-checking VORP/projections against a
familiar scoring baseline, skip live league data entirely:

```python
import fantasyfb as fb
league = fb.League(platform="generic", num_teams=12, mock_scoring="ppr")
```

This synthesizes `num_teams` empty rosters, a round-robin schedule,
and pulls the real current NFL player pool — there's just no actual
league or manager behind any of the teams. `mock_scoring` accepts
`standard`, `half_ppr`, or `ppr`.

By default, rosters follow a fixed shape (1 QB, 2 RB, 2 WR, 1 TE, 1
FLEX, 1 K, 1 DEF, 7 BN). Pass `roster_spots` as a `position`/`count`
DataFrame to customize it — extra flex spots, superflex (`Q/W/R/T`),
a bigger bench, etc.:

```python
import pandas as pd
import fantasyfb as fb

roster_spots = pd.DataFrame({
    "position": ["QB", "RB", "WR", "TE", "W/R/T", "Q/W/R/T", "BN"],
    "count":    [1,    2,    2,    1,    2,        1,         6],
})
league = fb.League(platform="generic", num_teams=12, roster_spots=roster_spots)
```

Valid position codes are the base positions (`QB`, `RB`, `WR`, `TE`,
`K`, `DEF`), the flex codes `W/T`, `W/R/T`, `Q/W/R/T`, and `BN`/`IR`.
An unrecognized code raises `ValueError` at construction time. On the
draft CLIs, pass the same shape via `--roster-spots` (see the
[CLI reference](cli/index.md)) or answer the interactive prompt when
it's omitted.

## Yahoo

`fantasyfb`'s weekly report CLI, and optionally the draft CLIs, read
roster state, scoring, and league settings from the
[Yahoo Fantasy API](https://developer.yahoo.com/fantasysports/guide/).
That API requires OAuth 2.0 credentials tied to a Yahoo developer app.
This is a one-time setup; once `oauth2.json` exists in your working
directory, every CLI and API call refreshes its token automatically.

### 1. Create a Yahoo developer app

1. Go to <https://developer.yahoo.com/apps/>.
2. Sign in with the Yahoo account that owns (or co-manages) your
   fantasy league.
3. Click **Create an App**.
4. Fill in:
    - **Application Name**: anything (e.g. `fantasyfb-local`).
    - **Application Type**: *Installed Application*.
    - **API Permissions**: tick **Fantasy Sports → Read** (Read/Write
      if you plan to script add/drop actions; Read is enough for
      projections and analysis).
5. Submit. Yahoo generates a **Client ID** (Consumer Key) and **Client
   Secret** (Consumer Secret). Keep this page open — you'll paste both
   into your shell in a moment.

### 2. Drop the credentials in `.env`

`fantasyfb` reads `CONSUMER_KEY` and `CONSUMER_SECRET` from the
environment (via `python-dotenv`). Create a `.env` file in the
directory you'll run scripts from:

```bash
# .env
CONSUMER_KEY=<paste from Yahoo>
CONSUMER_SECRET=<paste from Yahoo>
```

!!! warning "Don't commit `.env`"
    Add `.env` and `oauth2.json` to your `.gitignore`. Both contain
    credentials that grant full read (or read/write) access to your
    fantasy account.

### 3. First-run interactive token grant

The first time you instantiate `fb.League(...)`, the underlying
[`yahoo_oauth`](https://github.com/josuebrunel/yahoo-oauth) library
will:

1. Open a browser tab to a Yahoo authorization URL.
2. Ask you to sign in and approve the app.
3. Show you a short **verification code**.
4. Wait for you to paste that code back into the terminal.

After you paste the code, it writes `oauth2.json` next to your script.
That file holds the access + refresh tokens; subsequent runs use it
silently and auto-refresh as tokens expire.

```python
import fantasyfb as fb
league = fb.League(name="My Team")   # first run -> browser pops open
```

### 4. Picking the right team

`name=` is your **Yahoo fantasy team name** (the one shown on your
league home page), not your Yahoo display name or email. If you
manage multiple teams across leagues, `name` disambiguates which one
this `League` is bound to.

If you only have one team for the current season, you can omit `name`
entirely and it'll auto-select.

### Troubleshooting

??? note "`Please refresh the token` loop on every run"
    Delete `oauth2.json` and re-run — your refresh token expired
    (Yahoo expires them after ~60 days of inactivity). The first-run
    flow will regenerate it.

??? note "`401 Unauthorized` from `lg.current_week()`"
    Your app probably doesn't have Fantasy Sports permission. Go back
    to the Yahoo developer page, edit the app, and tick **Fantasy
    Sports → Read** (or Read/Write).

??? note "Wrong league / wrong season"
    `League(season=2026, name="My Team")` pins both. Without `season`,
    it picks the most recently *completed* season — pass it
    explicitly when prepping for an upcoming draft (e.g.
    `season=2026` in May 2026).

??? note "`Multiple teams found` error"
    You're in more than one league this season. Pass `name=` with the
    exact team name from the league you want.

### Further reading

- [`yahoo_oauth` library docs](https://github.com/josuebrunel/yahoo-oauth)
- [Yahoo Fantasy API docs](https://developer.yahoo.com/fantasysports/guide/)
- [`yahoo_fantasy_api` Python wrapper](https://github.com/spilchen/yahoo_fantasy_api)
