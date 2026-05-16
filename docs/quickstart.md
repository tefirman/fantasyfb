# First weekly report

End-to-end walkthrough: from `pip install` to a spreadsheet open in
Excel. Assumes you've already finished the [Yahoo OAuth
setup](yahoo-oauth.md) — `.env` populated, `oauth2.json` will be
generated on first run.

## 1. Install

```bash
pip install fantasyfb
```

## 2. Make a working directory

Everything below assumes you `cd` into one directory and run all
commands from there. `oauth2.json`, `.env`, and any output
spreadsheets all live here.

```bash
mkdir ~/fantasy-2026
cd ~/fantasy-2026
# put .env here (see Yahoo OAuth setup)
```

## 3. Run the weekly CLI

```bash
fantasyfb --team "My Team" --sims 1000 --adds --drops
```

What happens:

1. Authenticates to Yahoo (browser pops open on first run only).
2. Pulls your league's scoring settings, roster spots, and current
   rosters.
3. Pulls weekly NFL stats from `nflreadpy` (cached locally after the
   first call).
4. Fits per-player projection rates and runs 1,000 Monte Carlo season
   simulations.
5. Writes `FantasyFootballProjections_<Day>Week<N>.xlsx` to your
   home/Documents directory by default.
6. Prints the current-week matchup summary and end-of-season standings
   to stdout.

The `--adds` and `--drops` flags add two extra sheets that evaluate
every free-agent pickup and every dropable bench player by expected
$$ earnings delta.

## 4. Open the spreadsheet

Tabs you'll see:

| Sheet         | What's in it                                                |
| ------------- | ----------------------------------------------------------- |
| Rosters       | Every team's roster sorted by WAR                           |
| Available     | Free agents sorted by WAR                                   |
| Schedule      | Week-by-week win probabilities                              |
| Standings     | End-of-season expected wins / playoffs / winner odds        |
| Adds          | Every viable add, with earnings delta                       |
| Drops         | Drops ranked by lowest earnings cost                        |

## 5. Common follow-ups

Trade analysis:

```bash
fantasyfb --team "My Team" --sims 1000 --trades "Justin Jefferson"
```

Mid-season pickup focus:

```bash
fantasyfb --team "My Team" --sims 1000 --pickups all
```

Best-ball league:

```bash
fantasyfb --team "My Team" --sims 1000 --bestball
```

See the [`fantasyfb` CLI reference](cli/fantasyfb.md) for every flag.

## What's next

- **Pre-draft analysis:** [`draft-prep`](cli/draft-prep.md) for tiers,
  VORP, and mock drafts.
- **Live draft cockpit:** [`snake-draft`](cli/snake-draft.md) or
  [`salary-cap-draft`](cli/salary-cap-draft.md).
- **Scripting:** the [API reference](api/league.md) covers `League`
  and the simulation internals if you want to drive them from Python
  instead of the CLI.
