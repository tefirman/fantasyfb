"""Find the injuries the SFB odds depend on that ``injured_list.csv`` doesn't cover.

``PlayerDataManager.add_injuries`` flags new injuries only for players on the
template league's rosters, which is 12 of the field's ~4,800 teams. A starter
who is hurt on other leagues' rosters is never flagged and stays in every
lineup. This scans the whole field instead: a player counts once he is rostered
on ``min_teams`` teams (bench and IR included), which keeps the list to players
who move the odds.

Statuses come from Sleeper's player payload, the same one the collect step
already pulls, so scanning makes no extra requests.
"""
from __future__ import annotations

from typing import Iterable, Tuple

import pandas as pd

# Sleeper's injury_status values that mean "not playing", next to the Yahoo-style
# codes add_injuries uses. Questionable is deliberately absent, as there.
OUT_STATUSES = frozenset({
    "Out", "Doubtful", "IR", "PUP", "NA", "Sus", "COV",
    "O", "D", "SUSP", "PUP-R", "PUP-P", "NFI-R", "COVID-19",
})
LIST_COLUMNS = ["player_id_sr", "name", "position", "until"]
LAST_WEEK = 18


def rostered_counts(rosters: pd.DataFrame) -> pd.Series:
    """Distinct teams rostering each ``player_id``."""
    return rosters.drop_duplicates(["league_id", "team", "player_id"]).groupby("player_id").size()


def scan_injuries(
    rosters: pd.DataFrame,
    players: pd.DataFrame,
    injured_list: pd.DataFrame,
    current_week: int,
    min_teams: int = 20,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Players whose injury status and ``injured_list`` disagree.

    Args:
        rosters: ``league_id``, ``team``, ``player_id`` for every rostered player
            (``rosters.parquet`` from ``sfb-field collect``).
        players: Sleeper's player pool (``SleeperClient.get_all_players``), with
            ``player_id``, ``player_id_sr``, ``name``, ``position`` and ``status``.
        injured_list: the current ``injured_list.csv``.
        current_week: the week being projected.
        min_teams: how many field teams must roster a player for him to count.

    Returns:
        ``(new, old)``. ``new`` has players with an out designation and no
        ``until`` reaching ``current_week``, most widely rostered first (columns
        ``player_id_sr, name, position, status, teams``). ``old`` has list rows
        reaching ``current_week`` whose player no longer carries an out
        designation (columns ``player_id_sr, name, position, until, status``),
        so they are probably back early.
    """
    covered = set(injured_list.loc[injured_list.until >= current_week, "player_id_sr"])
    teams = rostered_counts(rosters).rename("teams")
    pool = players.merge(teams, left_on="player_id", right_index=True, how="left")
    pool["teams"] = pool.teams.fillna(0).astype(int)
    out = pool.status.isin(OUT_STATUSES)

    new = pool.loc[out & (pool.teams >= min_teams) & pool.player_id_sr.notna() & ~pool.player_id_sr.isin(covered)]
    new = new.sort_values(["teams", "name"], ascending=[False, True])
    status = pool.drop_duplicates("player_id_sr").set_index("player_id_sr").status
    old = injured_list.loc[injured_list.until >= current_week].copy()
    old["status"] = old.player_id_sr.map(status)
    # A player missing from the pool entirely is left alone rather than dropped.
    old = old.loc[old.player_id_sr.isin(status.index) & ~old.status.isin(OUT_STATUSES)]
    return (new[["player_id_sr", "name", "position", "status", "teams"]].reset_index(drop=True),
            old[LIST_COLUMNS + ["status"]].reset_index(drop=True))


def validate_injured_list(
    before: pd.DataFrame,
    after: pd.DataFrame,
    known_ids: Iterable[str],
    max_changes: int = 25,
) -> None:
    """Raises ``ValueError`` unless ``after`` is a sane edit of ``before``.

    Guards the unattended update: the schema is unchanged, every ``until`` is a
    whole week from 1 to 18, no player appears twice, every player is one Sleeper
    knows (or was already listed), and no more than ``max_changes`` rows were
    added, removed or changed.
    """
    problems = []
    if list(after.columns) != LIST_COLUMNS:
        raise ValueError(f"columns are {list(after.columns)}, expected {LIST_COLUMNS}")
    until = pd.to_numeric(after.until, errors="coerce")
    bad = after.loc[until.isna() | (until % 1 != 0) | (until < 1) | (until > LAST_WEEK)]
    if len(bad):
        problems.append(f"until must be a whole week from 1 to {LAST_WEEK}: {bad.name.tolist()}")
    dupes = after.loc[after.player_id_sr.duplicated(), "name"].tolist()
    if dupes:
        problems.append(f"duplicate players: {dupes}")
    unknown = after.loc[~after.player_id_sr.isin(set(known_ids) | set(before.player_id_sr)), "name"].tolist()
    if unknown:
        problems.append(f"players not in Sleeper's pool: {unknown}")
    old = before.set_index("player_id_sr").until
    new = after.drop_duplicates("player_id_sr", keep="last").set_index("player_id_sr").until
    both = old.index.intersection(new.index)
    changed = len(old.index.symmetric_difference(new.index)) + int((old[both] != new[both]).sum())
    if changed > max_changes:
        problems.append(f"{changed} rows changed, more than the {max_changes} allowed in one run")
    if problems:
        raise ValueError("; ".join(problems))
