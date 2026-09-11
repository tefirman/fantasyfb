# Scoring

## FantasyScorer

Converts NFL stats into fantasy points using the league's scoring
rules.

::: fantasyfb.scoring.fantasy_scoring.FantasyScorer

## MatchupModel

Per-game multiplicative matchup factor: team implied scoring total
(Vegas), opponent's allowed fantasy points to the player's position,
and depth-chart string, each folded around 1.0 so
`points_avg = points_rate * factor`. Replaces V1's
`basal + opp_elo_weight*elo_diff + string_weight*(1-string)` formula.

::: fantasyfb.scoring.matchup_model.MatchupModel

## LineupOptimizer

Picks the best legal starting lineup given per-player projections and
the league's roster slots.

::: fantasyfb.scoring.lineup_optimizer.LineupOptimizer
