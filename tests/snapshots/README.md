# Weekly-pipeline snapshots

Each directory here is a frozen copy of everything one weekly `fantasyfb`
run read from the outside world: every NFL-provider and platform-client
call and its result, the manual injury list, and the wall-clock time of
the run. `tests/test_weekly_snapshot.py` replays each one through the real
pipeline offline and checks invariants every correct run must satisfy:
no duplicate players, full and legal lineups, finished games locked to
actual points, probabilities that add up, rosters restored after move
analysis, and a complete Excel report.

Snapshots pin the pipeline's *inputs*, not its outputs, so they don't need
re-recording when the projection model changes. Re-record only if replay
fails with `SnapshotMiss`, which means the pipeline started making a call
the snapshot never saw.

## Recording

Record mid-slate when you can (for example Sunday night, before Monday
Night Football) so the live-week code paths run with some games final and
some still to play:

```bash
# Your Yahoo league (needs oauth2.json + .env, same as the fantasyfb CLI)
python scripts/record_snapshot.py --platform yahoo --team "My Team" --name yahoo_2026_w05_sunday_night

# A Sleeper league
python scripts/record_snapshot.py --platform sleeper --sleeper-league-id <id> --team "<team>" --name sleeper_2026_w05
```

Every directory with a `meta.json` is picked up automatically. A snapshot
is roughly 1 MB. Real league snapshots contain your league's team and
manager names, so only commit them if you're comfortable with that.

## Current snapshots

| Snapshot | What it covers |
| --- | --- |
| `generic_2026_w02_sunday_night` | Synthetic 12-team PPR league (rosters snake-drafted on 2025 fantasy points, week 1 given fixed pseudo-random scores) on real 2026 NFL data. The clock is frozen at 11:30pm on Sunday of week 2: Thursday and Sunday games are final, and Monday night (LA vs. NYG) is still to play. |
