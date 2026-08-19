<table markdown="block">
<tr markdown="block">
<td markdown="block" style="vertical-align: middle;"><img src="assets/fantasyfb_logo.png" alt="fantasyfb" width="160"></td>
<td markdown="block">

# fantasyfb

Fantasy football league simulation and optimization toolkit. Pulls
projections from [nflverse](https://github.com/nflverse) data, syncs
roster state from a Yahoo Fantasy league, and runs Monte Carlo season
simulations to value pickups, trades, and draft picks.

</td>
</tr>
</table>

## What's here

- **[Install](install.md)** — `pip install fantasyfb` plus dev setup.
- **[Connecting a league](platforms.md)** — Yahoo OAuth setup, or the
  credential-free Sleeper/generic options.
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

`fb.League(name=...)` defaults to the Yahoo Fantasy API, so you'll
need [OAuth credentials](platforms.md#yahoo) set up first — or pass
`platform="sleeper"` / `platform="generic"` for a
[credential-free league connection](platforms.md).

## Command-line tools

After install, four entry points are on your `PATH`:

| Command            | Use                                  |
| ------------------ | ------------------------------------ |
| `fantasyfb`        | Weekly projections + lineup analysis |
| `snake-draft`      | Live snake-draft cockpit             |
| `salary-cap-draft` | Live salary-cap (auction) draft tool |
| `draft-prep`       | Pre-draft tiers / VORP / mocks       |

Run any with `--help` for the full option list.
