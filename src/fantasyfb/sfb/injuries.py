"""Find the injuries the SFB odds depend on that ``injured_list.csv`` doesn't cover.

``PlayerDataManager.add_injuries`` flags new injuries only for players on the
template league's rosters, which is 12 of the field's ~4,800 teams. A starter
who is hurt on other leagues' rosters is never flagged and stays in every
lineup. This scans the whole field instead: a player counts once he is rostered
on ``min_teams`` teams (bench and IR included), which keeps the list to players
who move the odds.

Statuses come from Sleeper's player payload, the same one the collect step
already pulls. Rosters are pulled fresh (``collect.collect_rosters``, one
request per league) rather than read from an earlier collect, which could be
days old.
"""
from __future__ import annotations

from typing import Iterable, Tuple

import pandas as pd

from ..name_utils import normalize_name_key

# Sleeper's injury_status values that mean "not playing", next to the Yahoo-style
# codes add_injuries uses. Questionable is deliberately absent, as there.
OUT_STATUSES = frozenset({
    "Out", "Doubtful", "IR", "PUP", "NA", "Sus", "COV",
    "O", "D", "SUSP", "PUP-R", "PUP-P", "NFI-R", "COVID-19",
})
LIST_COLUMNS = ["player_id_sr", "name", "position", "until"]
LAST_WEEK = 18


def fill_player_ids(players: pd.DataFrame, nfl_rosters: pd.DataFrame) -> pd.DataFrame:
    """Backfill ``player_id_sr`` where Sleeper's payload has no ``gsis_id``.

    Sleeper leaves ``gsis_id`` empty for most recent draft classes and some
    veterans (on Nov 18, 40 of the 51 widely rostered players Sleeper listed as
    out), and ``scan_injuries`` and ``validate_injured_list`` both need it. IDs
    are filled from nflverse's rosters, which is what ``PlayerDataManager``
    does for the same players: by ``yahoo_id``, then by suffix-normalized name
    and team, then by name and position alone when that names exactly one
    player (which covers trades and team codes that differ between feeds, like
    LAR and LA). Anything still unmatched stays empty.
    """
    ids = players.player_id_sr.astype("string").str.strip().replace("", pd.NA)
    rosters = nfl_rosters.dropna(subset=["player_id_sr"]).assign(
        _name=lambda d: normalize_name_key(d["name"]),
        _pos=lambda d: d["position"].replace({"PK": "K"}),
    ).sort_values("season")
    cands = players.assign(
        _name=normalize_name_key(players["name"]), _pos=players["position"].replace({"PK": "K"}),
    )

    def fill(keys: list, source: pd.DataFrame, unique: bool = False) -> None:
        missing = ids.isna()
        if not missing.any():
            return
        source = source.dropna(subset=keys).drop_duplicates(keys + ["player_id_sr"], keep="last")
        if unique:
            source = source.drop_duplicates(keys, keep=False)
        else:
            source = source.drop_duplicates(keys, keep="last")
        found = cands.loc[missing].merge(source[keys + ["player_id_sr"]].rename(
            columns={"player_id_sr": "_found"}), on=keys, how="left")["_found"]
        ids.loc[missing] = found.to_numpy()

    if "yahoo_id" in rosters.columns and "yahoo_id" in players.columns:
        def as_text(s: pd.Series) -> pd.Series:
            return s.astype("string").str.replace(r"\.0$", "", regex=True)

        cands["_yid"] = as_text(players["yahoo_id"])
        fill(["_yid"], rosters.assign(_yid=as_text(rosters["yahoo_id"])))
    cands["_team"] = players["editorial_team_abbr"] if "editorial_team_abbr" in players.columns else pd.NA
    fill(["_name", "_pos", "_team"], rosters.assign(_team=rosters["current_team"]))
    fill(["_name", "_pos"], rosters, unique=True)
    return players.assign(player_id_sr=ids.astype(object).where(ids.notna(), None))


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
    # Sleeper's gsis_id has a stray leading space for some players (" 00-0035228"),
    # which would hide them from the list and from the validator's known IDs.
    players = players.assign(player_id_sr=players.player_id_sr.str.strip())
    injured_list = injured_list.assign(player_id_sr=injured_list.player_id_sr.str.strip())
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
