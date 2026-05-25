# Drafts

Pre-draft analytics, mock-draft simulation, and the snake cockpit's
pure view helpers. The CLI entry points
([`draft-prep`](../cli/draft-prep.md), [`snake-draft`](../cli/snake-draft.md))
all build on these.

## Tools

VORP, tiers, mock-draft simulator.

::: fantasyfb.drafts.tools
    options:
      members: true

## Snake cockpit views

Pure-DataFrame functions that produce the board / best / lookup /
roster tables the CLI renders.

::: fantasyfb.drafts.snake_cockpit
    options:
      members: true

## Salary-cap cockpit views

Salary-cap analogue of the snake cockpit. Adds `salary_value` and
`winning_bid` columns to the board; every view derives per-team
budget and slot state from the board itself, so picks are applied
with two cell writes and no external bookkeeping.

::: fantasyfb.drafts.salary_cap_cockpit
    options:
      members: true
