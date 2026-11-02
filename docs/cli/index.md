# CLI reference

`fantasyfb` ships five console entry points. They're all installed on
your `PATH` after `pip install fantasyfb`.

| Command                                       | Source                              | Use                                  |
| --------------------------------------------- | ----------------------------------- | ------------------------------------ |
| [`fantasyfb`](fantasyfb.md)                   | `fantasyfb.league:main`             | Weekly projections + lineup analysis |
| [`snake-draft`](snake-draft.md)               | `fantasyfb.drafts.snake:main`       | Live snake-draft cockpit             |
| [`salary-cap-draft`](salary-cap-draft.md)     | `fantasyfb.drafts.salary_cap:main`  | Live salary-cap draft tool         |
| [`draft-prep`](draft-prep.md)                 | `fantasyfb.drafts.prep:main`        | Pre-draft tiers / VORP / mocks       |
| [`sfb-field`](sfb-field.md)                   | `fantasyfb.sfb.cli:main`            | Field-wide Scott Fish Bowl odds      |

Every command accepts `--help` for the full flag list. Most of them
take `--team` to disambiguate when one Yahoo account manages multiple
fantasy teams.

## When to use which

- **In-season Sunday workflow** → `fantasyfb`
- **Before the draft** → `draft-prep` (tiers, VORP, mock drafts)
- **During a live draft** → `snake-draft` or `salary-cap-draft`
- **Scott Fish Bowl, across all leagues** → `sfb-field`
