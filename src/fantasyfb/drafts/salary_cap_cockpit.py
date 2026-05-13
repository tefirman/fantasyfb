"""Live salary cap draft cockpit helpers built on draft_tools.

Mirrors ``snake_cockpit`` for salary cap drafts. Where the snake side
plans around "pick number and ADP", the salary cap side plans around
"remaining budget and inflated dollar value". The valuation math
itself lives in ``tools`` (``compute_salary_values``, ``max_bid``);
this module renders it through a board-shaped DataFrame that picks
mutate as they happen.

A board for salary cap purposes is the snake board plus two columns:

- ``salary_value``: the pre-draft baseline dollar value (from
  ``compute_salary_values``).
- ``winning_bid``: NaN for undrafted players, the winning price once a
  player is drafted. Combined with ``fantasy_team`` this lets every
  view derive per-team spent / remaining budget without any external
  state.

Public API:
    build_board(players, roster_spec, num_teams, salary_cap, ...)
    compute_inflation(board, salary_cap, num_teams)
    view_best(board, ...)
    view_nominate(board, ...)
    view_what_if(board, name, bid, winning_team, ...)
    view_lookup(board, name)
    view_roster(board, team_name, ...)
    view_budget_status(board, team_names, salary_cap, roster_spec)
    simulate_nomination(board, ...)  # auto-pick for the 'random' command
    DEFAULT_DISPLAY_COLS
"""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .snake_cockpit import (
    _available,
    _ordered_columns,
    _position_sort_key,
    build_my_roster,
)
from .tools import (
    Roster,
    _USER_STRATEGY_MULT,
    _bench_slots_from_spec,
    _roster_spec_to_dict,
    assign_tiers,
    compute_salary_values,
    compute_vorp,
    max_bid,
)


DEFAULT_DISPLAY_COLS: tuple[str, ...] = (
    "name", "position", "current_team", "tier",
    "vorp_adjusted", "need_factor",
    "vorp_per_game", "points_rate",
    "salary_value", "inflated_value", "max_my_bid",
)


def build_board(
    players: pd.DataFrame,
    roster_spec,
    num_teams: int,
    *,
    salary_cap: int,
    min_bid: int = 1,
    gap_z: float = 1.0,
    top_n: int = 30,
    max_per_tier: int = 12,
) -> pd.DataFrame:
    """Build the snapshot salary cap draft board.

    Drops the synthetic ``avg_*`` rows ``League.get_rates`` injects for
    simulation, dedupes by ``player_id_sr``, and layers VORP, tiers,
    and ``salary_value`` onto the result. Adds an empty ``winning_bid``
    column so picks can be recorded in place.

    Unlike the snake board there's no ADP merge -- salary cap drafts
    are bid-driven, not pick-order-driven. The cockpit shell can still
    layer ADP on if it wants nomination-order analytics.
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
    valued = compute_salary_values(
        tiered, roster_spec, num_teams,
        salary_cap=salary_cap, min_bid=min_bid,
    )
    valued["winning_bid"] = np.nan
    return valued


def compute_inflation(
    board: pd.DataFrame,
    salary_cap: int,
    num_teams: int,
) -> float:
    """Market inflation factor for remaining players.

    Defined as ``(total league $ minus already-spent $) / (sum of
    salary_value across undrafted players)``. Equals 1.0 at draft
    start; rises above 1.0 if owners have underspent so far (more
    money chasing fewer dollars of value) and falls below 1.0 if
    owners have overpaid early.

    Returns 1.0 when no undrafted value remains (degenerate end-state).
    """
    total_pool = num_teams * salary_cap
    spent = float(board["winning_bid"].fillna(0).sum())
    remaining_dollars = total_pool - spent

    undrafted = board[board["fantasy_team"].isna()]
    remaining_value = float(undrafted["salary_value"].sum())
    if remaining_value <= 0:
        return 1.0
    return remaining_dollars / remaining_value


def _team_remaining(
    board: pd.DataFrame,
    team_name: str,
    salary_cap: int,
    roster_size: int,
) -> tuple[int, int]:
    """Return (remaining_budget, open_slots) for ``team_name`` derived
    from the board. Open slots assume one pick per drafted row."""
    team_rows = board[board["fantasy_team"] == team_name]
    spent = int(team_rows["winning_bid"].fillna(0).sum())
    open_slots = roster_size - len(team_rows)
    return salary_cap - spent, open_slots


def view_best(
    board: pd.DataFrame,
    *,
    my_team: str,
    salary_cap: int,
    num_teams: int,
    roster_spec,
    exclude: Iterable[str] = (),
    limit_per_position: int = 5,
    positions: Optional[Iterable[str]] = None,
    min_bid: int = 1,
) -> pd.DataFrame:
    """Top recommended targets per position for ``my_team``.

    Ranked by need-adjusted VORP (same idea as the snake view), but the
    output also carries the three dollar columns a salary cap user
    actually decides on: ``salary_value`` (pre-draft baseline),
    ``inflated_value`` (after market inflation), and ``max_my_bid``
    (the bid cap the user's remaining budget allows). The cockpit
    shell renders these so the user can see at a glance "should I
    chase this player and for how much."

    Internal ordering within a position matches raw VORP since the
    need_factor is constant; the need-scaling only matters for
    cross-position ranking.
    """
    avail = _available(board, exclude)
    if positions is not None:
        avail = avail[avail["position"].isin(set(positions))]

    spec = _roster_spec_to_dict(roster_spec)
    bench = _bench_slots_from_spec(roster_spec)
    roster_size = sum(spec.values()) + bench
    remaining_budget, open_slots = _team_remaining(
        board, my_team, salary_cap, roster_size,
    )
    user_max_bid = max_bid(remaining_budget, open_slots, min_bid=min_bid)
    inflation = compute_inflation(board, salary_cap, num_teams)
    my_roster = build_my_roster(board, my_team, roster_spec)

    avail = avail.copy()
    avail["need_factor"] = avail["position"].map(my_roster.need_score)
    avail["vorp_adjusted"] = avail["vorp_per_game"] * avail["need_factor"]
    avail["inflated_value"] = avail["salary_value"] * inflation
    # The user can't bid more than their cap allows, regardless of the
    # market price -- clip so the column reads as an actionable number.
    avail["max_my_bid"] = np.minimum(avail["inflated_value"], user_max_bid)

    avail = avail.sort_values(
        "vorp_adjusted", ascending=False, na_position="last",
    )
    top = avail.groupby("position", sort=False).head(limit_per_position)
    return top[_ordered_columns(top, DEFAULT_DISPLAY_COLS)].reset_index(drop=True)


def view_nominate(
    board: pd.DataFrame,
    *,
    my_team: str,
    salary_cap: int,
    num_teams: int,
    roster_spec,
    exclude: Iterable[str] = (),
    limit: int = 10,
) -> pd.DataFrame:
    """Players worth nominating to drain opponents' budgets.

    "Drain score" = ``inflated_value * (1 - my_need_factor)``: high
    market price, low fit for the user's current roster. Nominating
    these forces opponents into bidding wars on players the user
    didn't want anyway, eroding their cap space for the targets the
    user does want (use ``view_best`` for that side of the strategy).

    Players where the user still has a starting slot open get
    deprioritized -- a top WR in round 2 of an auction isn't a
    "drainer" if the user actually needs WRs, even if the market
    price is high.
    """
    avail = _available(board, exclude)
    inflation = compute_inflation(board, salary_cap, num_teams)
    my_roster = build_my_roster(board, my_team, roster_spec)

    avail = avail.copy()
    avail["need_factor"] = avail["position"].map(my_roster.need_score)
    avail["inflated_value"] = avail["salary_value"] * inflation
    avail["drain_score"] = avail["inflated_value"] * (1.0 - avail["need_factor"])

    avail = avail.sort_values(
        "drain_score", ascending=False, na_position="last",
    ).head(limit)
    cols = ["name", "position", "current_team", "salary_value",
            "inflated_value", "need_factor", "drain_score"]
    return avail[_ordered_columns(avail, cols)].reset_index(drop=True)


def view_what_if(
    board: pd.DataFrame,
    *,
    name: str,
    bid: int,
    winning_team: str,
    my_team: str,
    salary_cap: int,
    num_teams: int,
    roster_spec,
    limit_per_position: int = 5,
    min_bid: int = 1,
) -> pd.DataFrame:
    """Re-rank targets assuming ``winning_team`` lands ``name`` at ``bid``.

    Useful for "if Jefferson goes for $60 to team X, who's my plan B?"
    Returns the updated ``view_best`` over the hypothetical board.
    The real board is not mutated.
    """
    if name not in set(board["name"]):
        raise ValueError(f"Player {name!r} is not on the board.")
    scenario = board.copy()
    mask = scenario["name"] == name
    scenario.loc[mask, "fantasy_team"] = winning_team
    scenario.loc[mask, "winning_bid"] = bid
    return view_best(
        scenario, my_team=my_team, salary_cap=salary_cap,
        num_teams=num_teams, roster_spec=roster_spec,
        limit_per_position=limit_per_position, min_bid=min_bid,
    )


def view_lookup(board: pd.DataFrame, name: str) -> pd.DataFrame:
    """Row(s) for a single player, drafted or not.

    Includes ``fantasy_team`` and ``winning_bid`` so the user can see
    who paid what if the player is off the board.
    """
    rows = board[board["name"] == name]
    cols = list(DEFAULT_DISPLAY_COLS) + ["fantasy_team", "winning_bid"]
    return rows[_ordered_columns(rows, cols)].reset_index(drop=True)


def view_roster(board: pd.DataFrame, team_name: str) -> pd.DataFrame:
    """Players drafted by ``team_name`` with the winning bid for each,
    ordered by conventional position sequence then by VORP within
    position. Use ``view_budget_status`` for the team's spent/remaining
    summary.
    """
    mine = board[board["fantasy_team"] == team_name]
    cols = ["name", "position", "current_team", "tier",
            "vorp_per_game", "salary_value", "winning_bid"]
    if mine.empty:
        return mine[_ordered_columns(mine, cols)].reset_index(drop=True)
    mine = mine.assign(_pos_key=_position_sort_key(mine["position"]))
    mine = mine.sort_values(
        ["_pos_key", "vorp_per_game"], ascending=[True, False],
    ).drop(columns="_pos_key")
    return mine[_ordered_columns(mine, cols)].reset_index(drop=True)


def _build_team_roster(board: pd.DataFrame, team_name: str, roster_spec) -> Roster:
    """Reconstruct a ``Roster`` from a team's picks on the board so
    we can score positional need without an external state dict."""
    roster = Roster.from_spec(roster_spec)
    for _, row in board[board["fantasy_team"] == team_name].iterrows():
        roster.add({"position": row["position"]})
    return roster


def simulate_nomination(
    board: pd.DataFrame,
    *,
    team_names: Iterable[str],
    salary_cap: int,
    roster_spec,
    min_bid: int = 1,
    noise_floor: float = 2.0,
    noise_slope: float = 0.1,
    user_team: str = "My Team",
    user_strategy: str = "value",
    rng: Optional[np.random.Generator] = None,
) -> tuple[str, str, int]:
    """Auto-simulate one nomination + Vickrey auction on the current
    board. Returns ``(player_name, winning_team, winning_bid)``.

    A random team with open slots nominates the highest-`salary_value`
    player they can still afford. Every team then privately computes a
    reservation = ``need_factor * salary_value + N(0, sd)``, scaled by
    ``_USER_STRATEGY_MULT[user_strategy]`` for the user's team and
    clipped to ``max_bid`` for each team. The winner is the highest
    reservation; the price is the second-highest reservation +
    ``min_bid`` (the English-auction floor when bids tick up by the
    minimum increment).

    If no team is willing to bid at least ``min_bid``, the nominator
    is forced to take the player at ``min_bid`` -- a degenerate case
    that only happens late in the draft when budgets are exhausted.

    Raises ``ValueError`` if every team has a full roster or no
    undrafted players remain.
    """
    rng = rng if rng is not None else np.random.default_rng()

    spec = _roster_spec_to_dict(roster_spec)
    bench = _bench_slots_from_spec(roster_spec)
    roster_size = sum(spec.values()) + bench
    team_names = list(team_names)

    def team_state(team: str) -> tuple[int, int, int]:
        remaining, open_slots = _team_remaining(
            board, team, salary_cap, roster_size,
        )
        return open_slots, remaining, max_bid(remaining, open_slots, min_bid=min_bid)

    eligible = [t for t in team_names if team_state(t)[0] > 0]
    if not eligible:
        raise ValueError("All teams have full rosters; no nomination possible.")

    available = board[board["fantasy_team"].isna()]
    if available.empty:
        raise ValueError("No undrafted players remain on the board.")

    nominator = str(rng.choice(eligible))
    _, _, nom_max = team_state(nominator)
    affordable = available[available["salary_value"] <= max(nom_max, min_bid)]
    if affordable.empty:
        # Nominator's max-bid is below every remaining player's
        # listed value, but they still have to pick something to
        # honor the min bid floor. Grab the cheapest.
        affordable = available.nsmallest(1, "salary_value")
    nominated = affordable.sort_values(
        "salary_value", ascending=False,
    ).iloc[0]

    reservations: dict[str, int] = {}
    for team in team_names:
        open_slots, _, team_max = team_state(team)
        if open_slots <= 0 or team_max < min_bid:
            continue
        roster = _build_team_roster(board, team, roster_spec)
        nf = roster.need_score(nominated["position"])
        salary = float(nominated["salary_value"])
        mult = _USER_STRATEGY_MULT[user_strategy] if team == user_team else 1.0
        base = nf * salary * mult
        sd = max(noise_floor, noise_slope * salary)
        noisy = base + float(rng.normal(0, sd))
        reservations[team] = int(max(0, min(team_max, round(noisy))))

    sorted_bids = sorted(reservations.items(), key=lambda x: x[1], reverse=True)
    if not sorted_bids or sorted_bids[0][1] < min_bid:
        return str(nominated["name"]), nominator, min_bid

    winner = sorted_bids[0][0]
    second = sorted_bids[1][1] if len(sorted_bids) > 1 else (min_bid - 1)
    price = int(min(
        sorted_bids[0][1],
        max(min_bid, second + min_bid),
    ))
    return str(nominated["name"]), winner, price


def view_budget_status(
    board: pd.DataFrame,
    team_names: Iterable[str],
    *,
    salary_cap: int,
    roster_spec,
    min_bid: int = 1,
) -> pd.DataFrame:
    """Per-team cap snapshot: spent, remaining, slots filled and open,
    and max legal bid given current state.

    Sorted by remaining budget descending so the teams with the most
    spending power left sit at the top -- that's typically who you're
    competing with on the next nomination.
    """
    spec = _roster_spec_to_dict(roster_spec)
    bench = _bench_slots_from_spec(roster_spec)
    roster_size = sum(spec.values()) + bench

    rows = []
    for team in team_names:
        team_picks = board[board["fantasy_team"] == team]
        spent = int(team_picks["winning_bid"].fillna(0).sum())
        slots_filled = len(team_picks)
        slots_open = roster_size - slots_filled
        remaining = salary_cap - spent
        rows.append({
            "team": team,
            "spent": spent,
            "remaining": remaining,
            "slots_filled": slots_filled,
            "slots_open": slots_open,
            "max_bid": max_bid(remaining, slots_open, min_bid=min_bid),
        })
    return (
        pd.DataFrame(rows)
        .sort_values("remaining", ascending=False)
        .reset_index(drop=True)
    )
