# fantasyfb web app (draft)

A small web front end that runs fantasyfb season simulations for a **Sleeper** league and shows the
same interactive HTML report `fantasyfb --format html` writes. Sleeper's read API is public, so there's
no sign-in and no credentials to store: a user pastes their league URL, picks their team, and gets a report.

It lives in `app/`, outside `src/`, so it's never part of the PyPI package.

## Run it

```bash
pip install -e . -r app/requirements.txt
uvicorn fantasyfb_web.main:app --app-dir app --reload
# open http://127.0.0.1:8000
```

The first run on a machine downloads about 2 seasons of nflverse data (cached for 24h after that), so expect
it to take noticeably longer than later runs.

## Tests

```bash
pytest app/tests
```

These are hermetic: Sleeper and the simulation are stubbed, so they don't need network access.

## How it fits together

| File | What it does |
| --- | --- |
| `fantasyfb_web/main.py` | FastAPI routes: league lookup, queue a run, poll status, serve and download the report |
| `fantasyfb_web/sleeper.py` | Parses a league ID out of a pasted URL; league name/season/teams for the picker |
| `fantasyfb_web/jobs.py` | In-memory background job queue (one worker thread by default) |
| `fantasyfb_web/pipeline.py` | One run: `League(platform="sleeper")` → season sims → optional adds/drops/rooting guide → `FantasyHtmlExporter.render()` |
| `fantasyfb_web/templates/` | Picker and progress pages, styled with the report's own `industry-styles.css` |

The pages load `industry-styles.css` straight from `src/fantasyfb/io/templates/`, so the app and the
reports can't drift apart visually.

Flow: `GET /api/leagues?q=<url or id>` → `POST /api/runs` → redirect to `/runs/<id>`, which polls
`/api/runs/<id>` and turns into the report when the run finishes. Run IDs are random UUIDs, so a run's URL
doubles as an unguessable share link.

## Known limits of this draft

- **Single process only.** Jobs and results live in memory and are lost on restart. Before running more
  than one worker, move to a real queue (RQ/Celery + Redis) and store reports somewhere durable.
- **One run at a time.** A run is CPU-heavy and `League` writes to shared on-disk caches, so the pool has one
  worker; extra runs queue. Identical requests that are already queued share one job.
- **`pipeline.py` duplicates the report half of `fantasyfb.league.main`.** It should move into the package
  as a reusable function both can call.
- **No rate limiting or abuse protection** beyond the queue cap.
- **Best ball leagues** run as redraft; Sleeper's best ball flag isn't read yet.
- **Adds** only re-simulate the top 5 free agents per position by WAR, because Sleeper has no roster
  percentages to filter on.
