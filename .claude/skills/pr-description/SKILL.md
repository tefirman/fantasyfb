---
name: pr-description
description: Draft a pull request description for the current branch in this repo's house style (Summary, optional Results, Test plan with honest checkboxes). Checks that CHANGELOG.md was updated. Use when the user asks for a "PR description", "PR body", "write up this PR", or runs /pr-description, or before opening a PR.
---

# PR Description

Drafts the body for a pull request from the current branch's changes, matching `.github/pull_request_template.md` and the style of recent merged PRs (e.g. #92).

## Procedure

1. **Gather the facts.** Read `git log main..HEAD` and `git diff main...HEAD` (plus uncommitted changes), and any linked issue (`gh issue view <n>`). For style reference, skim one or two recent merged PRs with `gh pr list --state merged --limit 3 --json number,title,body`.

2. **Check the changelog.** If the branch has a user-visible change and `CHANGELOG.md` has no matching `[Unreleased]` entry, tell the user and offer to run `/changelog-entry` before the PR is opened. Refactors, test-only and CI changes don't need one.

3. **Write the description** with these sections:
   - **Summary**: for a fix, the symptom, then the root cause, then what changed, one bullet per distinct cause. For a feature, what it adds as bullets, then any deviations from a spec or design the reviewer should look at. Call out new dependencies, new flags, and breaking changes explicitly. Name functions and files in backticks.
   - **Results**: only when behavior or output changed and there are real numbers, a before/after table, or a screenshot to show. Omit the section otherwise. Note when a change shifts downstream numbers (projections, sims, valuations).
   - **Test plan**: a checklist of what was actually done.

4. **Keep the checkboxes honest.** Tick an item only if it was run in this session or the user said they ran it. Never tick "ran against a real league" on the user's behalf; ask, or leave it unchecked. List known gaps as unchecked items with a short reason.

5. **Show it to the user** in a fenced markdown block and tell them which checkboxes you couldn't verify. Don't open the PR unless asked.

## Style

- No hard-wrapping: break lines only for new paragraphs, bullets, or sections.
- Use commas or periods rather than em-dashes. Say "salary cap draft" or "bidding", never "auction".
- End the description with `🤖 Generated with [Claude Code](https://claude.com/claude-code)` when Claude wrote it.
- Write for a reviewer who hasn't seen the conversation: lead with what and why, not the debugging story.

## Guardrails

- Don't edit `CHANGELOG.md` here; that's `/changelog-entry`.
- Don't push, open the PR, or edit an existing PR's body without explicit approval.
