# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Persistent nflreadpy caching for offline draft prep** (#50): `NflreadpyProvider` now defaults nflreadpy's cache to filesystem mode (24h TTL) instead of its own in-memory default, which was wiped at the end of every process and therefore provided no benefit across the many separate CLI invocations a draft-prep session runs. Once a pull succeeds, subsequent pulls within the cache window reuse it without a network connection. `draft-prep`, `snake-draft`, and `salary-cap-draft` gain a `--refresh-cache` flag to force a fresh download for a single run; an explicit `NFLREADPY_CACHE` env var (or a caller's own `nflreadpy.update_config()`) still takes precedence over the new default.
- **`YahooFantasyClient.list_team_names(season)`**: lists the user's fantasy team name(s) for a season without connecting to a league or picking one. Lets a caller (e.g. a UI) offer a picker *before* `connect_to_league`/`League(name=...)` needs one — previously, an account with multiple teams for a season could only be resolved via `connect_to_league`'s interactive `input()` prompt, which hangs in any non-interactive context (e.g. a Streamlit app). `connect_to_league` now shares its league-lookup logic with the new method via a private `_find_nfl_league_teams` helper instead of duplicating it, and now raises a clear `ValueError` when no NFL league is found for the season instead of silently falling through with a stale/`None` league id.

### Removed
- **`PlayerDataManager.apply_name_corrections`**: fetched a legacy `name_corrections.csv` straight from `raw.githubusercontent.com` on every `League` construction, entirely outside `NflreadpyProvider`'s persistent caching, purely to patch stale player-name spellings from the pre-nflreadpy, Pro-Football-Reference-based name-matching era. `map_player_ids` has linked players by `yahoo_id`/`gsis_id` instead of name for a while now, and `snake-draft`/`salary-cap-draft`'s V2 rewrites had already dropped the equivalent inline fetch on that same assumption — this was the one remaining caller still carrying the dead weight. Surfaced as an offline-draft-prep crash (see Fixed below) before being removed outright; `process_players`/`League._process_players` no longer need the `stats` argument that only this step consumed.

### Fixed
- **`NflreadpyProvider.get_depth_charts` breaking offline draft prep on a cold cache**: unlike `get_schedule`/`get_rosters`/`get_player_stats`, it always requested the current calendar year's depth-chart file directly instead of going through the season-clamping the others use, and had no fallback for a download failure — only for a successful-but-empty response. With no network and no cached depth-chart file yet, this raised a raw `ConnectionError`/`ValueError` straight out of `League` construction, defeating the persistent filesystem caching added above. It now degrades to an empty depth-chart frame in that case, same as the other providers' missing-season handling, so a second offline run completes rather than crashing.
- **`PlayerDataManager.add_injuries` breaking offline draft prep**: fetches a small CSV directly from `raw.githubusercontent.com`, entirely outside `NflreadpyProvider`'s persistent caching, with no fallback for a dead network. A `--refresh-cache`-free, fully offline second run (real-world repro: nflreadpy's own cache warm, wifi off) crashed with `urllib.error.URLError` from inside this step. Now catches `OSError` (covers bare `urllib`'s and `requests`' connection failures alike), warns, and skips the injury-timespan enrichment rather than raising — it's optional signal, not required for a draft-prep session to complete.
- **`connect_to_league` connecting to the wrong league when a season's teams span multiple leagues**: Yahoo groups a user's teams for a season under one response entry even when they belong to entirely different leagues (e.g. two teams in the same season, two different `team_key` league-id segments). The multi-team branch derived the league id from an arbitrary team's `team_key` rather than the *selected* team's own, so picking the second team by name could silently connect you to the first team's league instead. `_find_nfl_league_teams` now maps each team name to its own league id.
- **Dual VORP (position-specific + flex)**: `compute_vorp` now emits three additional columns — `flex_replacement_rate`, `vorp_flex_per_game`, and `vorp_flex_season` — alongside the existing position-only columns. The new `compute_flex_replacement_levels` function sets each position's replacement baseline against the combined pool of all players eligible for the deepest flex slot covering that position. In a superflex (`Q/W/R/T`) league this correctly compresses QB VORP to reflect that the superflex slot would otherwise be filled by a WR/RB/TE rather than another QB. All draft decision surfaces (`vorp_adjusted` in cockpit views, salary cap dollar values, mock draft pick strategies) now use `vorp_flex_per_game`/`vorp_flex_season` as their primary signal. For positions with no flex slot (K, DEF) and for QB in a non-superflex league, flex VORP equals position VORP so there is no behavioral change in those cases.

## [0.6.0] — 2026-07-09

Sleeper-native scoring for SFB-style leagues (Third-Round Reversal, stacking yardage bonuses), V2 projection engine now the sole engine after winning the V1 bake-off (#24), and a new MkDocs documentation site (#21).

### Added
- **Docs site** (#21): MkDocs Material site at <https://tefirman.github.io/fantasyfb/>. Covers install, Yahoo OAuth setup, an end-to-end first-weekly-report walkthrough, full CLI reference for all four entry points, an architecture overview, and auto-generated API reference via `mkdocstrings`. Built and `--strict`-validated on every PR; deployed to GitHub Pages on push to `main`.
- **`scripts/build-assets.py`**: regenerates the docs-site logo variants (web hero + favicon) from the high-res master at `assets/fantasyfb_logo.png`.
- **Sleeper scoring/roster settings**: `data/sleeper_client.py` pulls a league's scoring, roster spots, and Third-Round Reversal setting directly from Sleeper's public read-only API (no OAuth) instead of hand-transcribing them. `configs.get_sfb_config_from_sleeper(league_id)` and `League(sfb=<sleeper_league_id>)` both use it to pull current settings live.
- **Third-Round Reversal support**: `drafts/tools.round_direction` / `MockDraft(reversal_round=...)` and `drafts/snake.snake_pick_slot(..., reversal_round=...)` can express TRR draft order (matching Sleeper's own `reversal_round` draft setting) instead of assuming plain alternating snake. Exposed as `--reversal-round` on both `snake-draft` and `draft-prep mock`.
- **New yardage-bonus scoring categories**: `FantasyScorer` now supports stacking `Pass 300+`/`Pass 400+` and `Rush 100+`/`200+`/`Rec 100+`/`200+` tiers, plus a combined `Rush+Rec 100+`/`200+` bonus -- needed to accurately score SFB16's Sleeper-based ruleset. Per-play "long play" bonuses (40+ yard completions/rushes, 20-29/30-39/40+ yard receptions) are intentionally not modeled -- they require play-by-play data, not per-game box-score aggregates.
- **`--sfb` flag** on `snake-draft` and `draft-prep` (previously only reachable via a `League()` kwarg, not exposed on any CLI script).

### Changed
- **`League(fit_matchup=True)` is now the default** (#24): matchup weights are ridge-fitted via walk-forward least squares on the prior season instead of using the hand-tuned defaults. A 2024 full-season walk-forward backtest showed `V2_fitted` beats the hand-tuned `V2_default` on QB/WR/K and overall RMSE.

### Removed
- **V1 projection engine** (#24): `projections/engine.py` deleted after a walk-forward bake-off confirmed V2 beats V1 by 5.7% overall MAE on the 2024 season (4.317 vs 4.576), consistent across 2023 as well. Bake-off script preserved at commit `894b6b4`.

## [0.5.0] — 2026-05-24

Best ball support across the draft and simulation stack (#31), and cost-plus-N keeper support across the salary cap V2 stack (#29).

### Added
- **Best ball season simulation** (#32): `SeasonSimulator.simulate_season(best_ball=True)` auto-fills optimal weekly lineups; `select_optimal_lineup` greedily fills fixed slots then flex; `compute_best_ball_team_projections` Monte Carlos per-player projections into team-level `(avg, stdev)`.
- **Best ball cockpit views** (#32): `view_bestball` and `view_nearestbestball` rank available players by upside-weighted VORP (`points_rate + 0.5 × points_stdev − replacement_rate`); `bestball` / `nearestbestball` wired into the snake draft pick loop.
- **Cost-plus-N keeper pricing** (#33): new `--keeper-surcharge` flag on `salary-cap-draft` (default `5`); keeper price = last year's salary + surcharge.
- **Keepers in salary cap V2 stack** (#33): `build_board` accepts a `keepers` DataFrame and excludes keepers from the dollar pool (VORP still computed on full pool); `MockSalaryCapDraft` accepts a `keepers` DataFrame to pre-apply keepers in mock drafts; `backtest_salary_values` gains a `keeper_names` parameter to strip pre-negotiated picks from surplus / overpay calculations.
- **Per-team keeper budget validation** (#33): teams whose keeper commitments exceed the cap have their keepers dropped with a warning before the draft starts. Resume-safe: keepers already present in an `--inprogress` file are skipped when `--keepers` is also passed.

### Changed
- Draft cockpits default to real Yahoo team names instead of generic placeholders (#33).
- Keepers CSV `fantasy_team` column accepts the user's actual Yahoo team name (#33).

### Fixed
- `_simulate_playoffs` returns `None` early for unsupported bracket sizes (anything other than 4 or 6 playoff teams), covering DraftKings / Underdog best-ball formats with no traditional playoff bracket (#32).
- `build_board` no longer raises `KeyError: 'fantasy_team'` when called on a bare projection pool (#33).

## [0.4.0] — 2026-05-21

Salary cap draft V2 (#11). Rebuilds `salary-cap-draft` on top of a tested valuation layer and cockpit views, with snake-parity ergonomics and a mock salary cap draft simulator.

### Added
- **Valuation primitives in `drafts.tools`** (#25): `compute_salary_values` (VORP-proportional, money-conserving) and `max_bid` (budget-constraint helper).
- **Salary cap cockpit views** (#26): `build_board`, `compute_inflation`, `view_best`, `view_nominate`, `view_what_if`, `view_lookup`, `view_roster`, `view_budget_status`.
- **Salary cap CLI rewrite** (#27): argparse-based `salary-cap-draft` with snake-parity commands (`best`, `nominate`, `whatif`, `lookup`, `roster`, `budgets`, `exclude`, `sim`, `go back`, `help`, `exit`), tab completion + readline history, and inflated-value / `max_my_bid` surfaced in the player lookup output.
- **Mock salary cap draft simulator and backtest harness** (#28): `MockSalaryCapDraft` (Vickrey-style bidding with `value` / `aggressive` / `conservative` strategies), `backtest_salary_values` for V1-vs-V2 surplus comparison, and `simulate_nomination` for in-cockpit use.
- **`random` / `random til full` commands** in `salary-cap-draft` for auto-piloting nominations and full-draft fills.
- **Resume support for legacy V1 draft progress CSVs** — `--inprogress` accepts the old `salary` column and renames it transparently.

### Changed
- Standings sorted by earnings, then `wins_avg`, then `points_avg` (#23).
- `move_analyzer` refactored to list-accumulate + single concat (#22).

### Fixed
- pyarrow fallback for nflverse parquet files that polars rejects as invalid UTF-8; bad-byte string columns are sanitized before the Arrow → pandas conversion (#27, #30).
- `player_id` cast to `str` when filling the `player_id_sr` fallback, fixing an arrow-string dtype crash in `map_player_ids` (#30).
- `_clean_schedule` team/score swap uses tuple assignment to avoid dtype-coupled arrow-string crashes (#30).

### Removed
- V1 `best_combos` cartesian-product optimizer (replaced by `view_best`).
- V1 `--starterpct` / `--limit` knobs (replaced by need scaling in `view_best`).
- V1 `possible_adds` Monte Carlo bench loop.
- V1 inline `name_corrections` HTTP fetch.
- `optparse` usage in `salary_cap.py` (replaced by `argparse`).

## [0.3.0] — 2026-05-11

First PyPI release.

### Added
- Projection engine V2 with Vegas-backed matchup factors and walk-forward weight fitting.
- `draft-prep` CLI for pre-draft tiers, VORP, ADP value, and mock-draft sims; `traps` subcommand for overdrafted-player avoid lists.
- Snake-draft cockpit V2 with VORP/tier/ADP board, tab completion, input history, and auto-pilot (`random`, `random til me`) commands.
- `--season` flag for pre-draft runs targeting upcoming seasons.
- Backtest harness comparing V1 vs V2 projections.

### Changed
- Repository restructured as `src/fantasyfb/` for PyPI packaging.
- CLIs standardized on `--team` flag for team identifier.
- Projection engine wired to V2 by default; V2 diagnostic columns preserved through `League.get_rates()`.
- `MatchupModel.apply_factors` is now idempotent across repeated calls.

### Fixed
- Duplicate player rows in `League.get_rates()` (#7).
- Season sim no longer double-counts `runners_up` from RangeIndex collision; completed-week scores are now locked.
- Yahoo API calls clamped when `--week` is past `end_week`.
- `as_of` week always treated as start-of-week in schedule.
- Negative projections from MatchupModel factors clipped at zero.
- Stale references to ESPN and Pro Football Reference removed.

### Removed
- `--email` option from `send-spreadsheet`.
- Many Mile feature from season simulator.
