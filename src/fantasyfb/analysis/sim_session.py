"""
Season simulations for comparing many roster scenarios.

Evaluating a pickup or a trade means simulating the whole league again with
one or two rosters changed. Done from scratch each time, nearly all of that
work repeats: every other team's lineups are unchanged, and each run is
simulated with fresh luck, so two scenarios differ partly by chance alone.
A session does the shared work once and keeps the luck fixed.
"""

import pandas as pd

from ..sim.season_simulator import CommonRandomNumbers


class SeasonSimSession:
    """Season simulations of one league that share a baseline and their luck.

    The baseline is the league's rosters when the session starts. Each
    ``standings`` call re-projects only the teams whose rosters you changed
    since then and simulates the season with the same random draws as every
    other call, so the standings differ only through the roster changes.
    Results are identical to ``League.season_sims`` run with those draws.
    """

    def __init__(self, league, postseason: bool = True, payouts: list = (800, 300, 100)):
        self.league = league
        self.postseason = postseason
        self.payouts = list(payouts)
        self._normals = CommonRandomNumbers()
        league.client.refresh_oauth()
        self._baseline = league._season_projections()

    def standings(self, changed_teams: list = None) -> pd.DataFrame:
        """Simulated season standings for the league's current rosters.

        Args:
            changed_teams: names of the teams whose rosters differ from the
                baseline. Teams not listed are assumed to match it.

        Returns:
            The standings DataFrame ``League.season_sims`` returns.
        """
        self.league.client.refresh_oauth()
        projections = self._baseline
        if changed_teams:
            changed = list(dict.fromkeys(changed_teams))
            fresh = self.league._season_projections(teams=changed)
            kept = projections[~projections.fantasy_team.isin(changed)]
            projections = pd.concat([kept, fresh], ignore_index=True).sort_values(
                ["week", "fantasy_team"], kind="stable", ignore_index=True
            )
        self._normals.rewind()
        return self.league._simulate_season(
            projections, self.postseason, list(self.payouts), normals=self._normals
        )[1]

    def restore(self) -> None:
        """Recompute every team's starters, which changed-team runs leave unset."""
        self.league.starters(17)


class BestBallSession:
    """The same interface for best ball, which still simulates from scratch."""

    def __init__(self, league, payouts: list):
        self.league = league
        self.payouts = payouts

    def standings(self, changed_teams: list = None) -> pd.DataFrame:
        return self.league.bestball_sims(self.payouts)

    def restore(self) -> None:
        pass
