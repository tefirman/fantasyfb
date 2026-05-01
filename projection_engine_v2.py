"""
Fantasy football projection engine v2.

Replaces the V1 model (weighted points + ELO + depth-chart factor +
Bayesian shrinkage to a position prior) with a volume x efficiency
decomposition:

    points_rate = expected_opportunities * expected_points_per_opportunity

The split makes the model interpretable at projection time -- a low
projection is either "low expected volume" (player has low usage), "low
expected efficiency" (player is bad on a per-touch basis), or both --
and lets us source signal from the most predictive horizon for each
piece. Volume changes fast (recent rolling windows beat long histories),
efficiency is sticky (career rates with Bayesian shrinkage to a
position prior).

The output schema matches V1 (player_id_sr, position, points_rate,
points_stdev, num_games) plus diagnostic columns (volume_rate,
efficiency_rate) so callers can debug a projection by reading off
"why".

Stage 1 of the rebuild: matchup adjustment is left to the lineup
optimizer at use-time, same as V1. Stage 2 will swap that for a Vegas-
backed factor.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


# Per-position definitions of "opportunity" -- the volume metric that
# drives fantasy scoring. Tuples are (column, weight); we sum
# weight * stat_value to get total opportunities for the row. Multiple
# entries per position let us blend stats (e.g. RB touches = carries +
# targets at equal weight; QB blends pass attempts + a small premium
# for rush attempts since rushing is denser fantasy points).
_OPPORTUNITY_DEF: Dict[str, list[tuple[str, float]]] = {
    "QB":  [("pass_cmp", 1.0), ("rush_att", 1.5)],
    "RB":  [("rush_att", 1.0), ("rec",      1.0)],
    "WR":  [("rec",      1.0)],
    "TE":  [("rec",      1.0)],
    "K":   [("xpm",      1.0), ("fgm",      1.0)],
    "DEF": [],  # one row per game; opportunity is a constant 1
}


# Default Bayesian shrinkage strength per position, expressed as
# "equivalent prior games to add to the player's actual game count".
# Higher = trust position prior more. Tuned by hand for Stage 1; will
# be replaced by least-squares fits in Stage 3.
_DEFAULT_SHRINKAGE: Dict[str, int] = {
    "QB": 6, "RB": 10, "WR": 10, "TE": 10, "K": 15, "DEF": 15,
}


# Default exponential time-decay rate per week. A game N weeks old gets
# weight exp(-_DEFAULT_TIME_DECAY * N). At 0.04, a 17-week-old game
# (one full season ago) contributes ~50% as much as last week's game,
# which gives recent form real teeth without throwing away long history.
_DEFAULT_TIME_DECAY: float = 0.04


class ProjectionEngineV2:
    """Volume x efficiency projection engine.

    Returns the same `points_rate`/`points_stdev`/`num_games` schema as
    V1 so the rest of fantasyfb (lineup optimizer, season simulator,
    move analyzer) keeps working unchanged. Per-week matchup adjustment
    happens downstream in lineup_optimizer, same as V1.
    """

    def __init__(
        self,
        time_decay: float = _DEFAULT_TIME_DECAY,
        shrinkage_n: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Args:
            time_decay: Per-week exponential decay rate applied when
                aggregating a player's volume and efficiency over their
                game history. 0 = no decay (treat all games equally),
                higher = trust recent games more.
            shrinkage_n: Bayesian shrinkage strength per position,
                expressed as equivalent prior games. Defaults to
                _DEFAULT_SHRINKAGE.
        """
        if time_decay < 0:
            raise ValueError("time_decay must be >= 0")
        self.time_decay = time_decay
        self.shrinkage_n = shrinkage_n or dict(_DEFAULT_SHRINKAGE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_projections(
        self,
        stats_df: pd.DataFrame,
        earliest_weeks: Dict[str, int],
        current_week: int,
        nfl_schedule: Optional[pd.DataFrame] = None,  # accepted for API parity
    ) -> pd.DataFrame:
        """Project per-game fantasy points for every player in stats_df.

        Args:
            stats_df: Historical game stats, must include `points` (added
                upstream by FantasyScorer) plus the position-specific
                opportunity columns referenced in _OPPORTUNITY_DEF.
            earliest_weeks: Per-position YYYYWW cutoff -- games older
                than this are excluded.
            current_week: Training cutoff in YYYYWW. Games on or after
                this week are excluded (no look-ahead).
            nfl_schedule: Accepted for V1 API parity; unused in Stage 1.

        Returns:
            DataFrame with one row per player plus one `avg_<POS>` row
            per position (used as the rookie fallback by fantasyfb.py).
            Columns: player_id_sr, position, points_rate, points_stdev,
            num_games, volume_rate, efficiency_rate.
        """
        df = self._filter_stats(stats_df, earliest_weeks, current_week)
        if df.empty:
            return self._empty_output()

        df = self._add_opportunity_column(df)

        position_priors = self._compute_position_priors(df)
        player_components = self._compute_player_components(df, current_week)

        projections = self._apply_shrinkage(player_components, position_priors)
        averages = self._build_average_rows(position_priors)

        return pd.concat([projections, averages], ignore_index=True, sort=False)

    # ------------------------------------------------------------------
    # Stages of the calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_stats(
        stats_df: pd.DataFrame,
        earliest_weeks: Dict[str, int],
        current_week: int,
    ) -> pd.DataFrame:
        """Restrict to in-window pre-cutoff games for positions of interest."""
        as_of = stats_df["season"] * 100 + stats_df["week"]
        keep = pd.Series(False, index=stats_df.index)
        for pos, earliest in earliest_weeks.items():
            mask = (
                (stats_df["position"] == pos)
                & (as_of >= earliest)
                & (as_of < current_week)
            )
            keep |= mask
        return stats_df[keep].copy()

    @staticmethod
    def _add_opportunity_column(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["opportunities"] = 0.0
        for pos, components in _OPPORTUNITY_DEF.items():
            mask = df["position"] == pos
            if not mask.any():
                continue
            if not components:
                # DEF: one opportunity per row (just played the game).
                df.loc[mask, "opportunities"] = 1.0
                continue
            total = sum(
                df.loc[mask, col].fillna(0) * weight
                for col, weight in components
            )
            df.loc[mask, "opportunities"] = total
        return df

    def _compute_position_priors(self, df: pd.DataFrame) -> pd.DataFrame:
        """Position-level mean opportunities and per-opportunity efficiency.

        Used both as the Bayesian prior for shrinkage and as the
        rookie/free-agent fallback projection.
        """
        rows = []
        for pos, group in df.groupby("position"):
            rows.append({
                "position": pos,
                "volume_rate": group["opportunities"].mean(),
                "efficiency_rate": (
                    group["points"].sum() / group["opportunities"].sum()
                    if group["opportunities"].sum() > 0
                    else group["points"].mean()
                ),
                "stdev": group["points"].std(ddof=0) or 0.0,
            })
        return pd.DataFrame(rows)

    def _compute_player_components(
        self, df: pd.DataFrame, current_week: int,
    ) -> pd.DataFrame:
        """Per-player volume and efficiency, exponentially time-weighted.

        Each game contributes weight exp(-time_decay * weeks_ago) to both
        the volume average and the efficiency ratio. Recent games dominate
        without discarding long history outright -- this is the lever
        that lets the model react to mid-season scheme changes (e.g. RB
        traded into a better situation) instead of regressing toward an
        18-month average.
        """
        df = df.sort_values(["player_id_sr", "season", "week"]).copy()

        # Approximate weeks-ago using a 17-game season; close enough for
        # the decay weighting. (Same calculation V1 used for time_factor.)
        df["weeks_ago"] = (
            17 * (current_week // 100 - df["season"])
            + (current_week % 100) - df["week"]
        ).clip(lower=0)
        df["w"] = np.exp(-self.time_decay * df["weeks_ago"])

        df["w_opp"] = df["w"] * df["opportunities"]
        df["w_pts"] = df["w"] * df["points"]
        df["w_pts_sq"] = df["w"] * df["points"] ** 2

        agg = df.groupby(["player_id_sr", "position"]).agg(
            w_sum=("w", "sum"),
            w_opp_sum=("w_opp", "sum"),
            w_pts_sum=("w_pts", "sum"),
            w_pts_sq_sum=("w_pts_sq", "sum"),
            num_games=("w", "size"),
        ).reset_index()

        agg["volume_rate"] = agg["w_opp_sum"] / agg["w_sum"]
        agg["efficiency_rate"] = np.where(
            agg["w_opp_sum"] > 0,
            agg["w_pts_sum"] / agg["w_opp_sum"],
            0.0,
        )
        # Weighted variance: E[X^2] - E[X]^2.
        mean_pts = agg["w_pts_sum"] / agg["w_sum"]
        mean_pts_sq = agg["w_pts_sq_sum"] / agg["w_sum"]
        agg["raw_points_var"] = (mean_pts_sq - mean_pts ** 2).clip(lower=0)

        return agg[[
            "player_id_sr", "position", "volume_rate", "efficiency_rate",
            "raw_points_var", "num_games",
        ]]

    def _apply_shrinkage(
        self,
        player_components: pd.DataFrame,
        position_priors: pd.DataFrame,
    ) -> pd.DataFrame:
        """Bayesian-blend each player's rate against the position prior.

        The blend weights player vs. position by relative game counts:
        with k = shrinkage_n[position], a player with n games gets
            blended = (n * player + k * prior) / (n + k)
        so a player with 0 games inherits the position prior, while a
        player with many games approaches their own observed rate.
        """
        merged = player_components.merge(
            position_priors.rename(columns={
                "volume_rate": "vol_prior",
                "efficiency_rate": "eff_prior",
                "stdev": "stdev_prior",
            }),
            on="position",
            how="left",
        )

        merged["k"] = merged["position"].map(self.shrinkage_n).fillna(10)
        n = merged["num_games"]
        k = merged["k"]
        denom = n + k

        merged["volume_rate"] = (
            n * merged["volume_rate"] + k * merged["vol_prior"]
        ) / denom
        merged["efficiency_rate"] = (
            n * merged["efficiency_rate"] + k * merged["eff_prior"]
        ) / denom

        merged["points_rate"] = merged["volume_rate"] * merged["efficiency_rate"]

        # Stdev: blend the player's own observed stdev with the position
        # stdev. Same shape as the mean blend so projections for low-
        # sample players inherit the broader spread of their position.
        player_var = merged["raw_points_var"].fillna(0)
        prior_var = merged["stdev_prior"].fillna(0) ** 2
        blended_var = (n * player_var + k * prior_var) / denom
        merged["points_stdev"] = np.sqrt(blended_var.clip(lower=0))

        return merged[[
            "player_id_sr", "position", "points_rate", "points_stdev",
            "num_games", "volume_rate", "efficiency_rate",
        ]]

    @staticmethod
    def _build_average_rows(position_priors: pd.DataFrame) -> pd.DataFrame:
        """Emit one `avg_<POS>` row per position for fantasyfb.get_rates rookies."""
        out = position_priors.copy()
        out["points_rate"] = out["volume_rate"] * out["efficiency_rate"]
        out["points_stdev"] = out["stdev"]
        out["num_games"] = 0
        out["player_id_sr"] = "avg_" + out["position"]
        return out[[
            "player_id_sr", "position", "points_rate", "points_stdev",
            "num_games", "volume_rate", "efficiency_rate",
        ]]

    @staticmethod
    def _empty_output() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "player_id_sr", "position", "points_rate", "points_stdev",
            "num_games", "volume_rate", "efficiency_rate",
        ])
