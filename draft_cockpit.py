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

import numpy as np
import pandas as pd

from draft_tools import (
    Roster,
    assign_tiers,
    compute_vorp,
    load_adp_csv,
    merge_adp,
)


_POSITION_ORDER: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")


# `vorp_adjusted` and `need_factor` only appear when a roster is passed
# to the view, so _ordered_columns drops them otherwise.
DEFAULT_DISPLAY_COLS: tuple[str, ...] = (
    "name", "position", "current_team", "tier",
    "vorp_adjusted", "need_factor",
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


def build_my_roster(
    board: pd.DataFrame,
    team_name: str,
    roster_spec,
) -> Roster:
    """Build a Roster reflecting the picks ``team_name`` already has on
    the board. Used by the cockpit views to scale VORP by positional need
    -- a 4th RB after you've filled your starting RB slots is worth less
    than a starting WR you don't have yet, even if their raw VORPs match.

    Pick order doesn't matter for the resulting need_score: greedy slot
    allocation (most-specific first, then flex, then bench) yields the
    same final slot occupancy regardless of the order picks were added.
    """
    roster = Roster.from_spec(roster_spec)
    mine = board[board["fantasy_team"] == team_name]
    for _, row in mine.iterrows():
        roster.add({"position": row["position"]})
    return roster


def _apply_need_scaling(
    avail: pd.DataFrame, my_roster: Optional[Roster],
) -> tuple[pd.DataFrame, str]:
    """Add ``need_factor`` and ``vorp_adjusted`` columns when a roster is
    provided, and return the column to sort by. With no roster, sorts by
    raw ``vorp_per_game`` -- the original cross-position behavior.
    """
    if my_roster is None:
        return avail, "vorp_per_game"
    avail = avail.copy()
    avail["need_factor"] = avail["position"].map(my_roster.need_score)
    avail["vorp_adjusted"] = avail["vorp_per_game"] * avail["need_factor"]
    return avail, "vorp_adjusted"


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
    my_roster: Optional[Roster] = None,
) -> pd.DataFrame:
    """Top-N available players per position, ranked by (need-adjusted) VORP.

    Per-position cap (``limit_per_position``) keeps a deep WR pool from
    drowning out other positions, but the final list is ordered globally
    so the row at the top is the player with the highest cross-position
    value.

    When ``my_roster`` is passed, sort key becomes ``vorp_per_game *
    need_score(position)`` and the output gains ``need_factor`` and
    ``vorp_adjusted`` columns. need_score is 1.0 for positions where the
    user still has a starting slot open, ~0.7 if the position fits an
    open flex slot, and 0.05-0.2 if the user has only bench room left --
    so a 4th RB after the starting RBs are filled gets penalized
    relative to a starting-eligible WR with similar raw VORP.

    Within a position the need_factor is constant, so internal ordering
    matches raw VORP either way -- the adjustment only changes the
    cross-position ranking.

    Replaces the original possible_adds-backed "best" view that ran a
    10k-sim season per candidate (unusable on the clock).
    """
    avail = _available(board, exclude)
    if positions is not None:
        avail = avail[avail["position"].isin(set(positions))]
    avail, sort_col = _apply_need_scaling(avail, my_roster)
    # Sort first; groupby().head() preserves input row order within each
    # group, so the top-N-per-position slice stays globally sorted.
    avail = avail.sort_values(sort_col, ascending=False, na_position="last")
    top = avail.groupby("position", sort=False).head(limit_per_position)
    return top[_ordered_columns(top, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)


def view_nearest(
    board: pd.DataFrame,
    *,
    pick_overall: int,
    num_teams: int,
    exclude: Iterable[str] = (),
    window_rounds: int = 2,
    my_roster: Optional[Roster] = None,
) -> pd.DataFrame:
    """Available players whose ADP falls within the next ``window_rounds``
    of the current overall pick number, sorted by (need-adjusted) VORP.

    This is the planning view: "given that the draft will turn around to
    me in N picks, which players the market thinks are about to go are
    worth grabbing now?" Players with no ADP are excluded -- by
    definition the market hasn't placed them in any window.

    Same need-scaling behavior as ``view_best`` when ``my_roster`` is
    passed: the adjusted VORP penalizes positions you've already filled.
    """
    avail = _available(board, exclude)
    cutoff = pick_overall + window_rounds * num_teams
    near = avail[avail["adp"].notna() & (avail["adp"] <= cutoff)]
    near, sort_col = _apply_need_scaling(near, my_roster)
    near = near.sort_values(sort_col, ascending=False, na_position="last")
    return near[_ordered_columns(near, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)


def view_lookup(board: pd.DataFrame, name: str) -> pd.DataFrame:
    """Row(s) for a single player, available or not.

    Includes ``fantasy_team`` so the user can see who already drafted them
    if the player is off the board.
    """
    rows = board[board["name"] == name]
    cols = list(DEFAULT_DISPLAY_COLS) + ["fantasy_team"]
    return rows[_ordered_columns(rows, cols)].reset_index(drop=True)


def random_pick(
    board: pd.DataFrame,
    *,
    team_name: str,
    roster_spec,
    exclude: Iterable[str] = (),
    pool_size: int = 8,
    rng: Optional[np.random.Generator] = None,
) -> str:
    """Auto-draft a sensible pick for ``team_name`` from the available pool.

    Used by the cockpit's ``random`` command so a user running a mock
    draft doesn't have to type out names for every opponent (or for
    their own picks when they're fast-forwarding through "boring"
    rounds). Returns the picked player's name -- the caller applies the
    pick the same way it would for a typed name.

    The selection is need-adjusted to avoid pathological auto-picks: the
    on-the-clock team's roster is rebuilt from the board so positions
    they've already filled get demoted, then the top ``pool_size``
    available players by adjusted VORP are sampled with probability
    proportional to their adjusted VORP. The top option is heavily
    favored but not deterministic, so re-running the same draft with
    the auto-pilot produces different (but always plausible) outcomes.

    Negative VORP values are clipped to a small epsilon so a fully-
    saturated roster (everyone's adjusted VORP near zero) still picks
    something rather than crashing on a zero-weight sample.
    """
    rng = rng if rng is not None else np.random.default_rng()
    avail = _available(board, exclude)
    roster = Roster.from_spec(roster_spec)
    for _, row in board[board["fantasy_team"] == team_name].iterrows():
        roster.add({"position": row["position"]})

    avail = avail.copy()
    avail["need_factor"] = avail["position"].map(roster.need_score)
    avail["vorp_adjusted"] = avail["vorp_per_game"] * avail["need_factor"]
    avail = avail.sort_values(
        "vorp_adjusted", ascending=False, na_position="last",
    )

    pool = avail.head(pool_size)
    if pool.empty:
        raise ValueError(
            f"No available players to auto-pick for {team_name!r}."
        )
    weights = pool["vorp_adjusted"].fillna(0).clip(lower=0.01).to_numpy()
    weights = weights / weights.sum()
    idx = int(rng.choice(len(pool), p=weights))
    return str(pool.iloc[idx]["name"])


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
