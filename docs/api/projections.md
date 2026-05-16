# Projections

The projection layer converts weekly NFL stats into per-game points
projections (mean + stdev) for every fantasy-relevant player.

## ProjectionEngineV2

The current production engine. Vegas-backed matchup factors with
walk-forward weight fitting.

::: fantasyfb.projections.engine_v2.ProjectionEngineV2

## MatchupModel

Applies opponent/Vegas factors on top of base rates.

::: fantasyfb.scoring.matchup_model.MatchupModel

## Model fitter

Walk-forward fitting of the projection-engine weights.

::: fantasyfb.projections.model_fitter
    options:
      members: true
