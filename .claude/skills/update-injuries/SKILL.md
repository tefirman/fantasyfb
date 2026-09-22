---
name: update-injuries
description: Weekly refresh of injured_list.csv (in the tefirman/fantasy-data repo) from current Yahoo injury designations. Researches each new or changed injury via web search for a best-guess return week, proposes a reviewable diff, and never commits without explicit approval. Use when the user asks to "update injuries", "refresh the injury list", or runs /update-injuries.
---

# Update Injuries

Keeps `fantasyfb/injured_list.csv` in the `tefirman/fantasy-data` repo
(local checkout: `~/fantasy-data`) in sync with reality: which players
are hurt, and a best-guess week they'll be back (`until` column).

This is a **propose, don't commit** skill. Always stop and show the
user a diff before writing to the CSV or making any git commit. Never
push automatically.

## Schema

`injured_list.csv` columns: `player_id_sr, name, position, until`

- `until`: the last week the player is expected to be OUT. The main
  pipeline (`player_data_manager.py`) treats a player as injured
  through this week, i.e. `until >= current_week` keeps a manual
  projection in place.
- A player should only appear here while genuinely questionable/out.
  Once healthy, remove their row rather than leaving a stale `until`.

## Inputs to reconcile

There are two signals to fold together each run:

1. **`NewInjuries.csv`** (repo root of `fantasyfb`, if present) — players
   `player_data_manager.py` flagged this week as newly showing an
   injury designation (O/D/SUSP/IR/PUP-R/PUP-P/NFI-R/NA/COVID-19) on a
   roster that isn't yet reflected in `injured_list.csv`. Columns:
   `player_id_sr, name, position, status`.
2. **`OldInjuries.csv`** (repo root of `fantasyfb`, if present) —
   players whose `injured_list.csv` `until` week has passed but who
   are still carrying an active designation in the day's pull. These
   need their `until` re-estimated (likely still out) or the row
   dropped (likely activated/healthy — double check status first).

If neither file exists, fall back to asking the user for the current
week's Yahoo roster export, or pulling injury designations directly
via the platform client if a live session is available.

## Procedure

1. **Load current state.**
   - Read `~/fantasy-data/fantasyfb/injured_list.csv` (the file this
     skill updates).
   - Read `NewInjuries.csv` and `OldInjuries.csv` from the `fantasyfb`
     repo root, if they exist.
   - If both are absent or empty, tell the user there's nothing to
     reconcile and stop.

2. **Research each player needing a decision** (every row in
   `NewInjuries.csv`, plus every `OldInjuries.csv` row whose status is
   still one of the injury designations above). For each:
   - Web search `"<player name>" injury <current NFL season year>` and
     similar, favoring recent beat-reporter and team-source reporting
     (local beat writers, ESPN/NFL Network injury desks,
     Rotoworld/RotoWire news) over aggregator "injury designation"
     pages with no substance.
   - **Anchor every result to the current season.** Include the
     current season year in searches, and verify each source's
     publish date falls within roughly the last 30 days. Stale
     reporting from a prior season (a past injury to the same player,
     a since-resolved timeline, an old team assignment) is easy to
     surface by accident and easy to mistake for current news —
     discard or explicitly flag anything you can't confirm is from
     the season in progress rather than presenting it as current.
   - While you're in there, notice (and flag to the user) anything
     that looks like stale roster data on our side too — e.g. the
     player's reported current team doesn't match what's in the
     source CSVs — since that can point to a data-quality issue
     elsewhere in the pipeline, not just a one-off research miss.
   - Look specifically for: the diagnosed injury, any stated recovery
     timeline, practice participation trend, and the team's own
     words ("week-to-week", "considered day-to-day", "out several
     weeks", IR requires missing 4 games minimum, etc).
   - Translate what you find into a concrete `until` week number
     (NFL week, not a duration) using the league's current week as the
     reference point. Note the source and its publish date, plus your
     reasoning — this goes in the proposal, not just the number.
   - If genuinely nothing concrete is reported yet (news is <24-48h
     old, team hasn't commented), it's fine to propose `until = current
     week + 1` as a conservative default and flag it as low-confidence
     rather than inventing a timeline.

3. **Build the proposed diff.** For each player, show:
   - name, position, current status
   - old `until` (if any) → proposed `until`
   - one-line rationale with source attribution (e.g. "ESPN (9/17):
     out 4-6 weeks with high ankle sprain, targeting Week 8 return")
   - confidence: high / medium / low

   Present this as a table in chat, not a file write yet.

4. **Get explicit sign-off.** Ask the user to confirm, edit, or reject
   each row (individually is fine if the list is short). Do not
   proceed to file changes until they've responded — this is the
   whole point of the skill; the guess is a draft, not a fact.

5. **Apply approved changes** to
   `~/fantasy-data/fantasyfb/injured_list.csv`:
   - Update `until` for existing rows.
   - Add new rows for newly-injured players.
   - Remove rows for players confirmed healthy/activated.
   - Preserve `player_id_sr`/`name`/`position` exactly as given in the
     source CSVs (don't re-derive or reformat them).

6. **Show the user the resulting file diff** (`git diff` in
   `~/fantasy-data`) and ask whether to commit. If yes, commit with a
   short message summarizing what changed (e.g. "Update injured list:
   add J. Doe (Wk 6 return), remove A. Smith (activated)") using the
   standard attribution footer. **Never push** without a separate,
   explicit ask — committing locally is as far as this skill goes
   unless told otherwise.

7. **Clean up** `NewInjuries.csv`/`OldInjuries.csv` in the `fantasyfb`
   repo root only after the user confirms the corresponding rows were
   handled (delete or leave — ask which they prefer; these are
   pipeline-generated scratch files, not tracked source of truth).

## Guardrails

- Never guess a specific return date/week without at least attempting
  a web search first — silent fabrication defeats the purpose.
- Distinguish "day-to-day/questionable, no real timeline yet" from "IR,
  out for a defined window" — the former deserves a short, clearly
  low-confidence `until`, not a fabricated multi-week number.
- Don't touch any file outside `injured_list.csv` (and the two scratch
  CSVs in step 7) as part of this skill.
- If a player's Yahoo status and news reporting conflict (e.g. Yahoo
  still shows "Q" but reporting says he's been ruled out for the
  season), surface the conflict explicitly rather than picking one
  silently.
- Never present a stale-season source as current-season fact. A
  player's name plus injury keywords will readily surface last year's
  (or older) reporting on the same or a different injury — check the
  publish date before treating a search result as this week's news.
