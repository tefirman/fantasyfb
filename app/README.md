# fantasyfb web app (draft)

A small web front end that runs fantasyfb season simulations for a **Sleeper** or **Yahoo** league and
shows the same interactive HTML report `fantasyfb --format html` writes.

- **Sleeper:** the read API is public, so a user pastes their league URL, picks their team, and gets a report.
- **Yahoo:** the user signs in with Yahoo (OAuth2), picks one of their teams, and gets a report. See
  [Yahoo sign-in](#yahoo-sign-in) for setup and the security model. Yahoo is hidden unless it's configured.

It lives in `app/`, outside `src/`, so it's never part of the PyPI package.

## Run it

```bash
pip install -e . -r app/requirements.txt
uvicorn fantasyfb_web.main:app --app-dir app --reload
# open http://127.0.0.1:8000
```

Sleeper works as-is over plain http. Yahoo needs https (see below).

The first run on a machine downloads about 2 seasons of nflverse data (cached for 24h after that), so expect
it to take noticeably longer than later runs.

## Yahoo sign-in

Yahoo only lets a user's own login read their teams, so the app runs the standard OAuth2 flow: the browser
goes to Yahoo, the user approves read-only access, and Yahoo sends the browser back to the app's callback URL
with a one-time code that the server trades for tokens.

**One-time setup**

1. In your app at https://developer.yahoo.com/apps/, add this redirect URI (Yahoo requires https, even for
   localhost): `https://localhost:8000/auth/yahoo/callback`. The CLI's `oob` setup does not cover the web app.
2. Put your app's credentials in `.env` in the directory you start the server from (the same
   `CONSUMER_KEY` / `CONSUMER_SECRET` the CLI uses). Optionally set `YAHOO_REDIRECT_URI` if you registered a
   different URL.
3. Make a local https certificate with [mkcert](https://github.com/FiloSottile/mkcert) (`*.pem` is gitignored):

   ```bash
   brew install mkcert && mkcert -install
   mkcert localhost
   ```

4. Start the server over https:

   ```bash
   uvicorn fantasyfb_web.main:app --app-dir app --port 8000 \
     --ssl-keyfile localhost-key.pem --ssl-certfile localhost.pem
   # open https://localhost:8000
   ```

**Security model**

- The app's consumer key and secret come from the environment only. A user's password never reaches the app.
- Tokens live in server memory only: never on disk, never in a URL, never in a log (`repr()` of the token
  object is redacted, and error messages never include Yahoo's response bodies). They're dropped on sign out,
  after 2 idle hours (12 hours at most), and on restart.
- The browser holds only a random session ID in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. The ID is
  rotated at sign-in.
- Each sign-in carries a single-use random `state` that must match on return, so a forged callback is refused.
- Cross-origin POSTs are refused, and auth, run, and report responses are `Cache-Control: no-store`.
- A Yahoo run belongs to the session that started it: anyone else gets a 404 for its page, status, and
  download, and two users' identical requests are never merged into one job. (Sleeper runs are public-data
  and keep the shareable-link behavior.)
- The app only reads from Yahoo. Nothing in the package writes to a platform.
- Yahoo queries give up after a few tries rather than retrying forever, so a revoked sign-in fails the
  run with a clear message instead of tying up the worker.

## Deploying

The app is a single container. `app/Dockerfile` builds it from the repo root (`docker build -f app/Dockerfile -t fantasyfb-web .`), and a whitelist in `/.dockerignore` keeps local secrets such as `oauth2.json`, `.env`, and the `.pem` files out of the image. It listens on `$PORT` (default 7860), exposes `GET /healthz`, and runs behind a host's proxy (`--proxy-headers`), so the one-run-per-visitor limit sees the visitor's address.

**Settings** (environment variables):

| Variable | Default | What it does |
| --- | --- | --- |
| `CONSUMER_KEY`, `CONSUMER_SECRET` | none | Your Yahoo app's credentials. Without them the page is Sleeper-only. Set them as secrets, never in the image. |
| `YAHOO_REDIRECT_URI` | `https://localhost:8000/auth/yahoo/callback` | The public https callback. Must match a redirect URI registered on your Yahoo app exactly. |
| `FANTASYFB_RUN_TIMEOUT` | `1200` | Seconds before a run is killed. |
| `FANTASYFB_MAX_QUEUED` | `10` | Most runs queued or running at once. Each takes minutes, so a long queue is a long wait. |
| `FANTASYFB_ENABLE_MOVES` | `1` | `0` turns off the adds and drops analyses. |
| `FANTASYFB_ENABLE_ROOTING` | `1` | `0` turns off the rooting guide (per-game deltas). |
| `FANTASYFB_COOKIE_SECURE` | `1` | `0` only for a deliberate plain-http dev setup. |

**Limits built in:** each run executes in its own child process, so the timeout really stops it and a crash or out-of-memory kill fails only that run. Each visitor (the signed-in session for Yahoo, the IP address for Sleeper) can have one run in progress at a time.

### Google Cloud Run

See [`deploy/cloudrun/README.md`](../deploy/cloudrun/README.md) for the build, deploy, and Yahoo redirect setup. It uses the same `app/Dockerfile`.

## Tests

```bash
pytest app/tests tests/test_yahoo_auth.py
```

These are hermetic: Sleeper and the simulation are stubbed, so they don't need network access.

## How it fits together

| File | What it does |
| --- | --- |
| `fantasyfb_web/main.py` | FastAPI routes: league lookup, queue a run, poll status, serve and download the report |
| `fantasyfb_web/sleeper.py` | Parses a league ID out of a pasted URL; league name/season/teams for the picker |
| `fantasyfb_web/yahoo.py` | Yahoo OAuth2 helpers (authorize URL, code exchange) and the team lookup for the picker |
| `fantasyfb_web/sessions.py` | In-memory browser sessions that hold Yahoo tokens and the OAuth `state` |
| `fantasyfb_web/jobs.py` | In-memory background job queue (one worker thread by default) |
| `fantasyfb_web/pipeline.py` | One run: `League` (Sleeper, or Yahoo via an injected client) → season sims → optional adds/drops/rooting guide → `FantasyHtmlExporter.render()` |
| `fantasyfb_web/templates/` | Picker and progress pages, styled with the report's own `industry-styles.css` |

The pages load `industry-styles.css` straight from `src/fantasyfb/io/templates/`, so the app and the
reports can't drift apart visually.

Flow (Sleeper): `GET /api/leagues?q=<url or id>` → `POST /api/runs` → redirect to `/runs/<id>`, which polls
`/api/runs/<id>` and turns into the report when the run finishes. Run IDs are random UUIDs, so a run's URL
doubles as an unguessable share link.

## Known limits of this draft

- **Single process only.** Jobs and results live in memory and are lost on restart. Before running more
  than one worker, move to a real queue (RQ/Celery + Redis) and store reports somewhere durable.
- **One run at a time.** A run is CPU-heavy and `League` writes to shared on-disk caches, so the pool has one
  worker; extra runs queue (up to `FANTASYFB_MAX_QUEUED`). Identical Sleeper requests that are already queued share one job.
- **`pipeline.py` duplicates the report half of `fantasyfb.league.main`.** It should move into the package
  as a reusable function both can call.
- **Abuse protection is basic.** There is a queue cap, one run per visitor, and a per-run timeout, but no per-IP request rate limiting or CAPTCHA.
- **Adds, drops, and the rooting guide are on by default.** The faster simulator makes them practical. Set
  `FANTASYFB_ENABLE_MOVES=0` or `FANTASYFB_ENABLE_ROOTING=0` and the server refuses them and the page hides them. Yahoo
  adds use the CLI's usual rostership filter, capped at 5 per position. Pickups and trades aren't exposed.
- **Best ball leagues** run as redraft; Sleeper's best ball flag isn't read yet.
- **Adds** only re-simulate the top 5 free agents per position by WAR, because Sleeper has no roster
  percentages to filter on.
