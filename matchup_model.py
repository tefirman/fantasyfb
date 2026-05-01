"""
Vegas-backed matchup factor for fantasy football projections.

Replaces V1's `basal + opp_elo_weight*elo_diff + string_weight*(1-string)`
game-factor formula with a richer multiplier built from three signals:

1. Team implied scoring total (Vegas) -- a forward-looking proxy for how
   many fantasy points the player's team will produce. Captures the
   scoring environment the spread alone hides (a 3-point favorite in a
   30-point game is very different from a 3-point favorite in a 50-point
   game).
2. Opponent's allowed fantasy points to the player's position -- how
   permissive this defense has been against this position over the
   season so far.
3. Depth-chart string -- backups get a discount; starters do not.

Each signal is converted to a deviation from league average and folded
multiplicatively around 1.0 so a league-average matchup yields factor 1.0
and downstream code can do `points_avg = points_rate * factor` cleanly.

Stage 2 of the V2 rebuild. Stage 3 will fit the per-position weights via
walk-forward least squares; right now they're hand-tuned defaults that
reflect typical signal strength.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class _PositionWeights:
    """Coefficient bundle for one position's matchup factor.

    factor = 1
            + alpha * z(team_implied_total)
            + beta  * z(opp_allowed_vs_position)
            - gamma * (string - 1)

    where z(x) = (x - league_avg) / league_std.
    """
    alpha: float  # team implied total weight
    beta: float   # opp allowed-vs-position weight
    gamma: float  # depth-chart string penalty


# Hand-tuned defaults, scaled so a one-stdev deviation in any one signal
# moves the factor by 0.1-0.3. Stage 3 replaces these with LS fits.
_DEFAULT_WEIGHTS: Dict[str, _PositionWeights] = {
    "QB":  _PositionWeights(alpha=0.20, beta=0.15, gamma=0.50),
    "RB":  _PositionWeights(alpha=0.15, beta=0.20, gamma=0.55),
    "WR":  _PositionWeights(alpha=0.15, beta=0.20, gamma=0.40),
    "TE":  _PositionWeights(alpha=0.10, beta=0.20, gamma=0.40),
    # Kickers' fantasy output tracks team scoring opportunities (red-zone
    # stalls -> FGs) but not opponent allowed-to-position in any clean way.
    "K":   _PositionWeights(alpha=0.10, beta=0.0,  gamma=0.0),
    # Defenses score *against* the offense, so the team-implied-total
    # signal flips sign: a high implied opp_total predicts a bad day for
    # the defense. We encode that by feeding opp_implied_total in with a
    # negative alpha.
    "DEF": _PositionWeights(alpha=-0.30, beta=0.15, gamma=0.0),
}


class MatchupModel:
    """Per-game multiplicative matchup factor.

    Build via :meth:`from_history`, which precomputes the league-wide
    distributions of implied total and allowed-vs-position used to
    z-score each input. Then call :meth:`apply_factors` to attach a
    `matchup_factor` column to a players DataFrame for a given week.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, _PositionWeights]] = None,
    ) -> None:
        self.weights = weights or dict(_DEFAULT_WEIGHTS)
        self._implied_total_mean: float = 22.5
        self._implied_total_std: float = 5.0
        self._allowed_per_pos_mean: Dict[str, float] = {}
        self._allowed_per_pos_std: Dict[str, float] = {}
        self._allowed_table: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_history(
        cls,
        stats_df: pd.DataFrame,
        schedule_df: pd.DataFrame,
        weights: Optional[Dict[str, _PositionWeights]] = None,
    ) -> "MatchupModel":
        """Fit the league-average baselines from historical data.

        Args:
            stats_df: per-game player stats with `points`, `position`,
                `opponent`, `season`, `week` columns. Used to compute
                "fantasy points allowed by team X to position P per game"
                via the player's `opponent` field.
            schedule_df: per-team-game schedule with `implied_total`.
                Used for the league mean/std of implied totals.
            weights: optional per-position coefficient overrides.
        """
        m = cls(weights=weights)
        m._fit_implied_total_baseline(schedule_df)
        m._fit_allowed_table(stats_df)
        return m

    def _fit_implied_total_baseline(self, schedule_df: pd.DataFrame) -> None:
        if schedule_df is None or "implied_total" not in schedule_df.columns:
            return
        valid = schedule_df["implied_total"].dropna()
        valid = valid[valid > 0]  # rows missing Vegas lines come through as 0
        if valid.empty:
            return
        self._implied_total_mean = float(valid.mean())
        self._implied_total_std = float(valid.std(ddof=0)) or 5.0

    def _fit_allowed_table(self, stats_df: pd.DataFrame) -> None:
        """Compute per-(opp_team, position) average fantasy points allowed.

        The mean is taken across (game, position) pairs, so a team that
        plays 10 games has each (opp, pos) row weighted equally with one
        that played 12.
        """
        if stats_df is None or stats_df.empty:
            return

        # Per-game, per-position points the opponent allowed.
        per_game = (
            stats_df.groupby(
                ["opponent", "season", "week", "position"], as_index=False
            )["points"].sum()
        )

        agg = per_game.groupby(["opponent", "position"], as_index=False).agg(
            allowed_per_game=("points", "mean"),
        )
        self._allowed_table = agg

        # League baselines per position for z-scoring.
        league = per_game.groupby("position")["points"].agg(["mean", "std"])
        for pos, row in league.iterrows():
            self._allowed_per_pos_mean[pos] = float(row["mean"])
            std = float(row["std"]) if not pd.isna(row["std"]) else 0.0
            self._allowed_per_pos_std[pos] = std or 1.0

    # ------------------------------------------------------------------
    # Factor computation
    # ------------------------------------------------------------------

    def factor(
        self,
        position: str,
        team_implied_total: float,
        opp_implied_total: float,
        opp_team: str,
        string: float = 1.0,
    ) -> float:
        """Per-player matchup multiplier centered at 1.0."""
        weights = self.weights.get(position)
        if weights is None:
            return 1.0

        # Defenses care about the *opponent's* implied total -- they score
        # less when the offense they face is projected to score a lot.
        relevant_total = opp_implied_total if position == "DEF" else team_implied_total
        z_total = self._z_implied_total(relevant_total)

        z_allowed = self._z_allowed(opp_team, position)
        string_penalty = max(0.0, string - 1.0)

        return float(
            1.0
            + weights.alpha * z_total
            + weights.beta * z_allowed
            - weights.gamma * string_penalty
        )

    def apply_factors(
        self,
        players: pd.DataFrame,
        schedule: pd.DataFrame,
        as_of: int,
    ) -> pd.DataFrame:
        """Attach a `matchup_factor` column to a players-shaped DataFrame.

        Args:
            players: must have `current_team`, `position`, and `string`.
            schedule: provider schedule output (one row per team-week).
            as_of: YYYYWW of the week we're projecting.

        Returns:
            A copy of `players` with `matchup_factor` and the underlying
            inputs (team implied total, opp_team, opp allowed) joined on
            for debuggability.
        """
        season, week = divmod(as_of, 100)
        week_sched = schedule[
            (schedule["season"] == season) & (schedule["week"] == week)
        ][["team", "opp_team", "implied_total", "opp_implied_total"]]

        out = players.merge(
            week_sched.rename(columns={"team": "current_team"}),
            on="current_team",
            how="left",
        )

        # Players whose teams aren't on the slate this week (bye, missing
        # schedule entry) get a neutral 1.0 factor instead of NaN.
        out["matchup_factor"] = [
            self.factor(
                position=row["position"],
                team_implied_total=row.get("implied_total") or self._implied_total_mean,
                opp_implied_total=row.get("opp_implied_total") or self._implied_total_mean,
                opp_team=row.get("opp_team") or "",
                string=row.get("string", 1.0) or 1.0,
            )
            if pd.notna(row.get("implied_total"))
            else 1.0
            for _, row in out.iterrows()
        ]
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _z_implied_total(self, value: float) -> float:
        if value is None or pd.isna(value) or value == 0:
            return 0.0
        return (value - self._implied_total_mean) / self._implied_total_std

    def _z_allowed(self, opp_team: str, position: str) -> float:
        if (
            self._allowed_table is None
            or position not in self._allowed_per_pos_mean
        ):
            return 0.0

        match = self._allowed_table[
            (self._allowed_table["opponent"] == opp_team)
            & (self._allowed_table["position"] == position)
        ]
        if match.empty:
            return 0.0
        allowed = float(match.iloc[0]["allowed_per_game"])
        mean = self._allowed_per_pos_mean[position]
        std = self._allowed_per_pos_std[position]
        return (allowed - mean) / std
