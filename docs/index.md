# fantasyfb

Fantasy football league simulation and optimization toolkit. Pulls
projections from [nflverse](https://github.com/nflverse) data, syncs
roster state from a Yahoo Fantasy league, and runs Monte Carlo season
simulations to value pickups, trades, and draft picks.

## What's here

- **[Install](install.md)** — `pip install fantasyfb` plus dev setup.
- **[Yahoo OAuth setup](yahoo-oauth.md)** — the one-time credential
  dance you have to do before anything else works.
- **[First weekly report](quickstart.md)** — end-to-end walkthrough
  from a fresh install to a finished Excel file.
- **[CLI reference](cli/index.md)** — one page per entry point
  (`fantasyfb`, `snake-draft`, `salary-cap-draft`, `draft-prep`).
- **[Architecture](architecture.md)** — what each subpackage does and
  how the pieces fit together.
- **[API reference](api/index.md)** — auto-generated from docstrings
  for users who script against `League` directly.

## Quickstart

```bash
pip install fantasyfb
```

```python
import fantasyfb as fb

league = fb.League(name="My Team")
schedule_sim, standings_sim = league.season_sims(postseason=True)
print(standings_sim[["team", "wins_avg", "playoffs", "winner"]])
```

`fb.League(name=...)` reads from the Yahoo Fantasy API, so you'll need
[OAuth credentials](yahoo-oauth.md) set up first.

## Command-line tools

After install, four entry points are on your `PATH`:

| Command            | Use                                  |
| ------------------ | ------------------------------------ |
| `fantasyfb`        | Weekly projections + lineup analysis |
| `snake-draft`      | Live snake-draft cockpit             |
| `salary-cap-draft` | Live salary-cap (auction) draft tool |
| `draft-prep`       | Pre-draft tiers / VORP / mocks       |

Run any with `--help` for the full option list.
