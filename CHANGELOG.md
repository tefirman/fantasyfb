# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-05-11

First PyPI release.

### Added
- Projection engine V2 with Vegas-backed matchup factors and
  walk-forward weight fitting.
- `draft-prep` CLI for pre-draft tiers, VORP, ADP value, and mock-draft
  sims; `traps` subcommand for overdrafted-player avoid lists.
- Snake-draft cockpit V2 with VORP/tier/ADP board, tab completion, input
  history, and auto-pilot (`random`, `random til me`) commands.
- `--season` flag for pre-draft runs targeting upcoming seasons.
- Backtest harness comparing V1 vs V2 projections.

### Changed
- Repository restructured as `src/fantasyfb/` for PyPI packaging.
- CLIs standardized on `--team` flag for team identifier.
- Projection engine wired to V2 by default; V2 diagnostic columns
  preserved through `League.get_rates()`.
- `MatchupModel.apply_factors` is now idempotent across repeated calls.

### Fixed
- Duplicate player rows in `League.get_rates()` (#7).
- Season sim no longer double-counts `runners_up` from RangeIndex
  collision; completed-week scores are now locked.
- Yahoo API calls clamped when `--week` is past `end_week`.
- `as_of` week always treated as start-of-week in schedule.
- Negative projections from MatchupModel factors clipped at zero.
- Stale references to ESPN and Pro Football Reference removed.

### Removed
- `--email` option from `send-spreadsheet`.
- Many Mile feature from season simulator.
