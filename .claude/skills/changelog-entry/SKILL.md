---
name: changelog-entry
description: Add a CHANGELOG.md entry under [Unreleased] for a fix, feature, or removal on the current branch, written in this repo's house style (bold headline, issue/PR number, user-visible symptom, root cause, what changed). Use when the user asks to "add a changelog entry", "update the changelog", or runs /changelog-entry, or as the last step before opening a PR that changes behavior.
---

# Changelog Entry

Adds one entry per user-visible change to the `## [Unreleased]` section of `CHANGELOG.md` (Keep a Changelog format). `docs/changelog.md` includes this file via a snippet, so never edit that one.

## Procedure

1. **Work out what changed.** Read `git diff main...HEAD` (plus any uncommitted changes) and the linked issue, if there is one (`gh issue view <n>`). If the branch contains several unrelated changes, write one entry per change.

2. **Pick the section** under `## [Unreleased]`: `### Added`, `### Changed`, `### Fixed`, or `### Removed`. Create the subsection if it doesn't exist yet, keeping the order Added, Changed, Fixed, Removed. Refactors, test-only changes, and CI tweaks with no user-visible effect don't get an entry; tell the user that rather than inventing one.

3. **Write the entry** as a single bullet on one line (no hard wraps):
   - Starts with a **bold headline** stating the user-visible symptom or feature, then the issue or PR number in parentheses, e.g. `**`MoveAnalyzer.possible_pickups` crashed with a `TypeError` for any healthy drop candidate** (#86):`. For follow-ups to an earlier issue with no number of their own, use `(follow-up to #78)`.
   - Then: what a user would have seen, why it happened (the actual root cause, naming the function or file), and what the fix does. Name concrete players, positions, or numbers when the investigation surfaced them; that's the house style.
   - For fixes to previously untested code, note that test coverage was added.
   - For breaking changes, say **Breaking change:** and what now happens instead.
   - Use backticks for code identifiers. Use commas or periods rather than em-dashes. Say "salary cap draft", never "auction".

4. **Show the user the diff** of `CHANGELOG.md` and ask for edits before committing. If the user wants it committed, include it in the same commit as the change when it hasn't been committed yet, otherwise as its own small commit on the branch.

## Guardrails

- Don't bump the version or create a dated release section here; that's the `/release` skill's job.
- Don't rewrite or reorder existing entries unless asked.
- If the PR number isn't known yet (PR not opened), use the issue number, or leave a `(#TBD)` placeholder and tell the user to fill it in once the PR exists.
