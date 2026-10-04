---
name: weekly-run
description: In-season weekly check for a real fantasy league. Runs the fantasyfb pipeline for a team, sanity-checks the players DataFrame for the bug classes that have bitten this repo before, and summarizes matchup odds, standings, and add/drop/trade suggestions. Use when the user asks to "run the weekly numbers", "check my team", "who should I pick up", or runs /weekly-run.
---

# Weekly Run

Runs the same pipeline as the `fantasyfb` CLI (`league.main`), but checks the data before trusting the output. A clean-looking spreadsheet built on a corrupted `players` DataFrame (duplicate rows, NaN projections) is worse than an error, so the checks come first.

## Inputs

Ask for (or reuse from earlier in the conversation):
- **Team name**, exactly as it appears in the Yahoo league. The CLI has hardcoded payouts for a few known teams in `cli._apply_defaults`; for others, ask for payouts (1st/2nd/3rd) or use the default 60/30/10.
- **What to analyze**: adds, drops, pickups for specific players, trades, per-game deltas. Default to adds + drops.
- **Week**, only if they want something other than the current week.

Yahoo credentials (`oauth2.json`, `.env`) must be in the repo root. If the Yahoo connection fails, run `python notes/yahoo_api_probe.py` to tell an API outage apart from an auth problem before debugging anything else.

## Procedure

1. **Freshness.** If it's game day or the day after (live or just-finished week), use a fresh pull (`NflreadpyProvider(refresh=True)` / `--refresh-cache`), because the 24h cache will hold stale in-progress stats. Otherwise the cache is fine.

2. **Build the League in Python** (not the CLI), so the DataFrame can be inspected before any export:
   ```python
   import fantasyfb as fb
   from fantasyfb.data.nflreadpy_provider import NflreadpyProvider
   league = fb.League(name=TEAM, num_sims=SIMS, nfl_provider=NflreadpyProvider(refresh=REFRESH))
   ```
   This takes a few minutes and is network-bound. Run it in the background and write intermediate results to the scratchpad, not the repo.

3. **Sanity-check `league.players`** and report anything that fails, before looking at results:
   - No duplicate `player_id` rows (depth-chart or name-join fan-out).
   - Every rostered player (`fantasy_team` not null) has a non-NaN `points_avg`; list any that don't.
   - Each team has the expected number of `starter == True` rows for `league.week`, given `league.roster_spots`.
   - During a live week: starters whose NFL game has finished have `points_stdev == 0` (actual points applied).
   - Kickers show position `K`, not `PK`.
   - Players with an injury designation have a sensible `until`. If `NewInjuries.csv` / `OldInjuries.csv` appeared in the repo root, say so and suggest `/update-injuries`.

   If any check fails, stop and show the evidence. That's a bug to investigate (and likely a GitHub issue), not a result to present.

4. **Run the analysis** the user asked for: `league.season_sims(True, payouts=...)`, then `possible_adds`, `possible_drops`, `possible_pickups`, `possible_trades`, or `perGameDelta` with the same arguments `league.main` passes (including `limit_per` and `exclude`).

5. **Summarize in chat**, briefly:
   - This week's matchup: win probability and projected points for both sides.
   - Standings outlook: `wins_avg`, playoff odds, title odds, expected earnings for the user's team, and anything notable about rivals.
   - The top few add/drop/trade suggestions with their earnings delta, flagging any that rely on an injured player or a questionable projection.

6. **Offer the spreadsheet.** If they want the Excel file, run the CLI with the same options (`fantasyfb --team "..." --adds --drops ...`). By default it writes to `~/Documents/<TeamNameNoSpaces>/<season>/FantasyFootballProjections_<Weekday>Week<N>.xlsx`. Tell them the path.

## Guardrails

- fantasyfb is read-only against Yahoo. Never attempt to set lineups or make transactions; present suggestions only.
- Don't write outputs or scratch files into the repo; the root-level CSVs are gitignored run artifacts and shouldn't be added to.
- If a suggestion looks absurd (a clear starter recommended as a drop, a huge earnings delta for a bench player), treat it as a possible data bug and check that player's row before presenting it.
