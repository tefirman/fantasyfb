"""Which NFL players move a team's Scott Fish Bowl odds.

The field simulation gives every player one shared draw per week and simulation,
so the same draws can be read back as an experiment: in the simulations where a
player has a better stretch, how much more often do the teams that start him do
well? The answer, per player, is a *swing*: the change in a team's result for a
one-standard-deviation better stretch from that player.

- ``qual_swing``: chance of qualifying, over the regular-season weeks still to play.
- ``playoff_swing``: expected playoff rounds advanced (0 to 6) for a team that
  qualified, over the playoff weeks.

Owners are the teams that start the player in at least one of those weeks.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


def player_sds(weeks: dict, which: Iterable[int]) -> np.ndarray:
    """(num_week, num_player) stdev of each player's score in each of ``which`` weeks."""
    return np.vstack([weeks[w][0].max(axis=0) for w in which])


def owners(weeks: dict, which: Iterable[int]) -> np.ndarray:
    """(num_team, num_player) float32, 1 where the team starts the player in any of ``which`` weeks."""
    return (np.stack([weeks[w][0] > 0 for w in which]).any(axis=0)).astype(np.float32)


def standardized_output(draws: Dict[int, np.ndarray], sds: np.ndarray, which: Iterable[int]) -> np.ndarray:
    """(num_sim, num_player) total of ``sd x draw`` over the weeks, scaled to unit variance.

    Players with no variance get zeros.
    """
    total = sum(sds[i][:, None] * draws[w] for i, w in enumerate(which))
    scale = np.sqrt((sds ** 2).sum(0))
    return (total / np.where(scale > 0, scale, 1.0)[:, None]).T.astype(np.float32)


def qualification_swing(qualified: np.ndarray, own: np.ndarray, output: np.ndarray) -> np.ndarray:
    """Slope of the owners' qualification rate on a player's standardized regular-season output.

    Args:
        qualified: (num_sim, num_team) bool.
        own: (num_team, num_player) ownership from ``owners``.
        output: (num_sim, num_player) from ``standardized_output``.
    """
    count = own.sum(0)
    rate = (qualified.astype(np.float32) @ own) / np.where(count > 0, count, np.nan)
    x = output - output.mean(0)
    var = (x ** 2).mean(0)
    return (x * (rate - rate.mean(0))).mean(0) / np.where(var > 0, var, np.nan)


class PlayoffSwing:
    """Accumulates the playoff swing over playoff replays.

    Each replay passes in the rounds every team advanced and the players' playoff
    output. Pooling the qualified owners across simulations and replays, the swing
    is the regression slope of rounds advanced on that output. Regular-season
    results do not depend on playoff draws, so the slope is not distorted by who
    qualified.
    """

    def __init__(self, qualified: np.ndarray, own: np.ndarray):
        self.qualified = qualified.astype(np.float32)
        self.own = own
        self.teams_in = self.qualified.sum(1)
        self.sums = {k: np.zeros(own.shape[1]) for k in ("n", "r", "y", "ry", "yy", "share")}
        self.reps = 0

    def add(self, advanced: np.ndarray, output: np.ndarray) -> None:
        """One replay: (num_sim, num_team) rounds advanced and (num_sim, num_player) output."""
        owners_in = self.qualified @ self.own
        rounds = (advanced * self.qualified) @ self.own
        s = self.sums
        s["n"] += owners_in.sum(0)
        s["r"] += rounds.sum(0)
        s["y"] += (output * owners_in).sum(0)
        s["ry"] += (output * rounds).sum(0)
        s["yy"] += (output ** 2 * owners_in).sum(0)
        s["share"] += (owners_in / np.maximum(self.teams_in, 1)[:, None]).mean(0)
        self.reps += 1

    def swing(self) -> np.ndarray:
        s = self.sums
        n = np.where(s["n"] > 0, s["n"], np.nan)
        var = s["yy"] / n - (s["y"] / n) ** 2
        return (s["ry"] / n - (s["r"] / n) * (s["y"] / n)) / np.where(var > 0, var, np.nan)

    def playoff_share(self) -> np.ndarray:
        """Average share of the playoff field that starts each player."""
        return self.sums["share"] / max(self.reps, 1)


def swing_table(player_ids, qual_swing, playoff_swing, playoff_share, own_regular, own_playoff) -> pd.DataFrame:
    """One row per player: the two swings and how widely he is started.

    ``field_share`` is the share of all teams starting him in the playoff weeks;
    ``playoff_share`` is the share of the playoff field doing so.
    """
    return pd.DataFrame({
        "player_id": player_ids,
        "teams": own_regular.sum(0).astype(int),
        "field_share": own_playoff.mean(0),
        "playoff_share": playoff_share,
        "qual_swing": qual_swing,
        "playoff_swing": playoff_swing,
    })


def add_player_info(table: pd.DataFrame, directory: Optional[dict] = None) -> pd.DataFrame:
    """Adds ``name``, ``position`` and ``nfl_team`` to a ``swing_table`` from Sleeper's player map.

    ``directory`` defaults to Sleeper's cached player map (one request a day at most).
    Players it doesn't know keep their ID as the name.
    """
    if directory is None:
        from ..data.sleeper_client import fetch_all_players
        directory = fetch_all_players()
    info = [directory.get(str(pid), {}) for pid in table.player_id]
    out = table.copy()
    out["name"] = [i.get("full_name") or str(pid) for i, pid in zip(info, table.player_id)]
    out["position"] = [i.get("position") or "" for i in info]
    out["nfl_team"] = [i.get("team") or "" for i in info]
    return out
