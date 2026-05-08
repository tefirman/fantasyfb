"""Live-draft cockpit helpers built on draft_tools.

The interactive CLIs (``snake_draft.py``, eventually ``salary_cap_draft.py``)
own the input loop and Yahoo-credentialed pieces. Everything that can be
expressed as a pure function on a draft "board" -- a DataFrame combining the
projection pool with VORP, tiers, and ADP value -- lives here so it can be
unit-tested offline.

Public API:
    build_board(players, roster_spec, num_teams, adp_csv_path, ...)
    view_best(board, ...)
    view_nearest(board, ...)
    view_lookup(board, name)
    view_roster(board, team_name)
    DEFAULT_DISPLAY_COLS
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from draft_tools import (
    assign_tiers,
    compute_vorp,
    load_adp_csv,
    merge_adp,
)


_POSITION_ORDER: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")


DEFAULT_DISPLAY_COLS: tuple[str, ...] = (
    "name", "position", "current_team", "tier",
    "vorp_per_game", "points_rate",
    "adp", "adp_round", "adp_value",
)


def build_board(
    players: pd.DataFrame,
    roster_spec,
    num_teams: int,
    adp_csv_path: str,
    *,
    name_col: str = "Player",
    adp_col: str = "AVG",
    position_col: str = "POS",
    team_col: Optional[str] = "Team",
    gap_z: float = 1.0,
    top_n: int = 30,
    max_per_tier: int = 12,
) -> pd.DataFrame:
    """Build the snapshot draft board.

    Drops the synthetic ``avg_*`` rows that ``League.get_rates`` injects for
    sim purposes, dedupes by ``player_id_sr``, and layers VORP / tier / ADP
    columns onto the result.

    The board is a snapshot: ``fantasy_team`` reflects whatever was on
    ``players`` at call time (so keepers / in-progress picks survive). The
    cockpit shell mutates ``fantasy_team`` on the returned board as picks
    come in.
    """
    pool = (
        players[~players["player_id_sr"].astype(str).str.startswith("avg_")]
        .drop_duplicates(subset=["player_id_sr"], keep="first")
        .copy()
    )
    with_vorp = compute_vorp(pool, roster_spec, num_teams)
    tiered = assign_tiers(
        with_vorp, top_n=top_n, max_per_tier=max_per_tier, min_gap_z=gap_z,
    )
    adp = load_adp_csv(
        adp_csv_path,
        name_col=name_col, adp_col=adp_col,
        position_col=position_col, team_col=team_col,
    )
    return merge_adp(tiered, adp, num_teams=num_teams)


def _available(board: pd.DataFrame, exclude: Iterable[str] = ()) -> pd.DataFrame:
    avail = board[board["fantasy_team"].isna()]
    excluded = {n for n in exclude if n}
    if excluded:
        avail = avail[~avail["name"].isin(excluded)]
    return avail


def _ordered_columns(board: pd.DataFrame, cols: Iterable[str]) -> list[str]:
    return [c for c in cols if c in board.columns]


def _position_sort_key(position: pd.Series) -> pd.Series:
    """Sort key that puts QB/RB/WR/TE/K/DEF in conventional order, with
    anything else (flex labels, garbage) sorted to the end alphabetically."""
    order = {p: i for i, p in enumerate(_POSITION_ORDER)}
    return position.map(lambda p: (order.get(p, len(_POSITION_ORDER)), p))


def view_best(
    board: pd.DataFrame,
    *,
    exclude: Iterable[str] = (),
    limit_per_position: int = 5,
    positions: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Top-N available players per position, ranked by VORP across positions.

    Per-position cap (``limit_per_position``) keeps a deep WR pool from
    drowning out other positions, but the final list is ordered by
    ``vorp_per_game`` regardless of position so the row at the top of the
    table is the player with the highest cross-position value.

    Within a position VORP ordering is identical to points_rate ordering
    by construction (vorp = points_rate - replacement_level[position]) --
    the cross-position sort is where VORP earns its keep, distinguishing
    a 25-point QB above a deep replacement level from a 17-point RB just
    barely above his own.

    Replaces the original possible_adds-backed "best" view that ran a
    10k-sim season per candidate (unusable on the clock).
    """
    avail = _available(board, exclude)
    if positions is not None:
        avail = avail[avail["position"].isin(set(positions))]
    # Sort by VORP first; groupby().head() preserves input row order
    # within each group, so the top-N-per-position slice stays
    # VORP-sorted overall without a re-sort.
    avail = avail.sort_values("vorp_per_game", ascending=False, na_position="last")
    top = avail.groupby("position", sort=False).head(limit_per_position)
    return top[_ordered_columns(top, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)


def view_nearest(
    board: pd.DataFrame,
    *,
    pick_overall: int,
    num_teams: int,
    exclude: Iterable[str] = (),
    window_rounds: int = 2,
) -> pd.DataFrame:
    """Available players whose ADP falls within the next ``window_rounds``
    of the current overall pick number, sorted by VORP descending.

    This is the planning view: "given that the draft will turn around to
    me in N picks, which players that the market thinks are about to go
    are worth grabbing now?" Players with no ADP are excluded -- by
    definition the market hasn't placed them in any window.
    """
    avail = _available(board, exclude)
    cutoff = pick_overall + window_rounds * num_teams
    near = avail[avail["adp"].notna() & (avail["adp"] <= cutoff)]
    near = near.sort_values("vorp_per_game", ascending=False, na_position="last")
    return near[_ordered_columns(near, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)


def view_lookup(board: pd.DataFrame, name: str) -> pd.DataFrame:
    """Row(s) for a single player, available or not.

    Includes ``fantasy_team`` so the user can see who already drafted them
    if the player is off the board.
    """
    rows = board[board["name"] == name]
    cols = list(DEFAULT_DISPLAY_COLS) + ["fantasy_team"]
    return rows[_ordered_columns(rows, cols)].reset_index(drop=True)


def view_roster(board: pd.DataFrame, team_name: str) -> pd.DataFrame:
    """Players drafted by ``team_name``, ordered by conventional position
    sequence then by VORP within position.
    """
    mine = board[board["fantasy_team"] == team_name]
    if mine.empty:
        return mine[_ordered_columns(mine, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)
    mine = mine.assign(_pos_key=_position_sort_key(mine["position"]))
    mine = mine.sort_values(
        ["_pos_key", "vorp_per_game"], ascending=[True, False],
    ).drop(columns="_pos_key")
    return mine[_ordered_columns(mine, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)
