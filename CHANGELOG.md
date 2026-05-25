# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
