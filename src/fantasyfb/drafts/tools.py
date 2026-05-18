"""Pre-draft analytics built on top of ProjectionEngineV2 output.

The League object exposes one row per (player, position) with the V2
columns `points_rate`, `points_stdev`, `num_games`, `volume_rate`, and
`efficiency_rate`. Those rates answer "how good is the player" -- the
draft loop also needs answers to "how scarce is this player at his
position", "where does he go relative to the field", and "what does
my roster look like if I keep picking this way". This module provides
those second-order analytics as pure functions / a small simulator
class so the draft CLIs can stay thin and the logic stays testable
without Yahoo creds.

Public API:
    compute_replacement_levels(projections, roster_spec, num_teams)
    compute_vorp(projections, roster_spec, num_teams)
    compute_salary_values(projections, roster_spec, num_teams, salary_cap=...)
    max_bid(remaining_budget, open_slots)
    assign_tiers(projections, ...)
    load_adp_csv(path, ...)
    merge_adp(projections, adp_df, num_teams)
    Roster, FLEX_ELIGIBILITY  # roster-state tracking + flex eligibility
    MockDraft(...)  # simulator
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


_BASE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")
_SEASON_GAMES: int = 17


# Flex slot encoding used by Yahoo league configs throughout the
# codebase. Each entry maps the slot label to the base positions that
# can fill it.
FLEX_ELIGIBILITY: Dict[str, tuple[str, ...]] = {
    "W/T":     ("WR", "TE"),
    "W/R/T":   ("WR", "RB", "TE"),
    "Q/W/R/T": ("QB", "WR", "RB", "TE"),
}


def _roster_spec_to_dict(roster_spec) -> Dict[str, int]:
    """Accept either a DataFrame (position/count columns, as produced
    by fantasyfb.League.roster_spots) or a plain dict and return a
    cleaned {slot: count} dict with bench/IR stripped out."""
    if isinstance(roster_spec, pd.DataFrame):
        spec = dict(zip(roster_spec["position"], roster_spec["count"]))
    else:
        spec = dict(roster_spec)
    return {k: int(v) for k, v in spec.items()
            if k not in ("BN", "IR") and int(v) > 0}


def _expected_starters_per_position(
    spec: Dict[str, int], num_teams: int,
) -> Dict[str, float]:
    """Total starting slots across the league that will be filled at
    each base position, including a flex share.

    Hard slots (QB/RB/WR/TE/K/DEF) count fully. Flex slots are split
    evenly across their eligible base positions -- a defensible default
    that doesn't require an opinion on which position "tends to" win
    flex (in practice RB/WR dominate, but that's already reflected in
    the projection-driven greedy fill done by VORP itself).
    """
    starters: Dict[str, float] = {p: 0.0 for p in _BASE_POSITIONS}
    for slot, count in spec.items():
        if slot in _BASE_POSITIONS:
            starters[slot] += count * num_teams
        elif slot in FLEX_ELIGIBILITY:
            eligible = FLEX_ELIGIBILITY[slot]
            share = (count * num_teams) / len(eligible)
            for pos in eligible:
                starters[pos] += share
    return starters


def compute_replacement_levels(
    projections: pd.DataFrame,
    roster_spec,
    num_teams: int,
) -> Dict[str, float]:
    """Replacement-level points_rate per position.

    Definition: for position P, sort the projection pool descending by
    `points_rate`; the replacement level is the rate of the player
    ranked at index `expected_starters[P]` (0-indexed). Conceptually
    this is "the best player at P who won't be a starter anywhere in
    the league" -- the natural baseline for VORP.

    If fewer than `expected_starters[P] + 1` players exist at the
    position, the replacement level falls back to the rate of the
    weakest available player at that position (so VORP stays defined,
    just degenerate).
    """
    spec = _roster_spec_to_dict(roster_spec)
    starters = _expected_starters_per_position(spec, num_teams)

    pool = projections[~projections["player_id_sr"].astype(str).str.startswith("avg_")]

    levels: Dict[str, float] = {}
    for pos in _BASE_POSITIONS:
        if starters[pos] <= 0:
            # Position isn't rostered in this league -- VORP is undefined.
            levels[pos] = float("nan")
            continue
        rates = (pool.loc[pool["position"] == pos, "points_rate"]
                 .dropna().sort_values(ascending=False).to_numpy())
        if rates.size == 0:
            levels[pos] = 0.0
            continue
        idx = int(round(starters[pos]))
        idx = min(idx, rates.size - 1)
        levels[pos] = float(rates[idx])
    return levels


def compute_vorp(
    projections: pd.DataFrame,
    roster_spec,
    num_teams: int,
    season_games: int = _SEASON_GAMES,
) -> pd.DataFrame:
    """Add VORP columns to a projection DataFrame.

    Returns a copy with two new columns:
        vorp_per_game: points_rate - replacement_level[position]
        vorp_season:   vorp_per_game * season_games

    Players at positions that don't appear in the league (e.g. K in a
    K-less league) get NaN VORP -- the caller can drop them.
    """
    levels = compute_replacement_levels(projections, roster_spec, num_teams)
    out = projections.copy()
    out["replacement_rate"] = out["position"].map(levels)
    out["vorp_per_game"] = out["points_rate"] - out["replacement_rate"]
    out["vorp_season"] = out["vorp_per_game"] * season_games
    return out


def _total_roster_size(spec: Dict[str, int], bench_slots: int) -> int:
    """Starting slots + bench. Used by salary value math to count the
    total picks each team will make."""
    return sum(spec.values()) + bench_slots


def _bench_slots_from_spec(roster_spec) -> int:
    if isinstance(roster_spec, pd.DataFrame):
        bench_row = roster_spec[roster_spec["position"] == "BN"]
        return int(bench_row["count"].iloc[0]) if not bench_row.empty else 0
    if isinstance(roster_spec, dict):
        return int(roster_spec.get("BN", 0))
    return 0


def compute_salary_values(
    projections: pd.DataFrame,
    roster_spec,
    num_teams: int,
    *,
    salary_cap: int,
    min_bid: int = 1,
) -> pd.DataFrame:
    """Convert season VORP into per-player salary cap dollar values.

    Standard valuation: the league has `num_teams * salary_cap` total
    dollars to distribute across `num_teams * roster_size` picks. Every
    pick reserves `min_bid` (so a $1 minimum is always honored), and the
    remaining "above-min" pool is allocated among the top-N starter
    pool (N = num_teams * starting_slots_per_team) proportionally to
    each player's positive season VORP. Players outside the starter
    pool or with non-positive VORP get `min_bid`.

    Why VORP-proportional rather than raw-points-proportional: the
    market sets prices based on edge over replacement, not absolute
    output. A QB1 outscores an RB1 in raw points but the QB1's *edge*
    over a free-agent QB is much smaller than the RB1's edge over a
    free-agent RB, so the RB1 commands more dollars. VORP already
    encodes that asymmetry.

    Requires `vorp_season` on the input (run `compute_vorp` first).
    Returns a copy with a new `salary_value` float column.

    Raises ValueError if the salary cap is too small to reserve
    `min_bid` for every pick.
    """
    if "vorp_season" not in projections.columns:
        raise ValueError(
            "projections is missing required column 'vorp_season'. "
            "Run compute_vorp() first."
        )

    spec = _roster_spec_to_dict(roster_spec)
    bench = _bench_slots_from_spec(roster_spec)
    starting_slots_per_team = sum(spec.values())
    roster_size = _total_roster_size(spec, bench)

    total_pool = num_teams * salary_cap
    total_picks = num_teams * roster_size
    above_min_pool = total_pool - total_picks * min_bid
    if above_min_pool < 0:
        raise ValueError(
            f"salary_cap={salary_cap} is too small to honor "
            f"min_bid={min_bid} across {roster_size} roster slots."
        )

    out = projections.copy()
    out["salary_value"] = float(min_bid)

    pool_mask = ~out["player_id_sr"].astype(str).str.startswith("avg_")
    eligible = out.loc[pool_mask].sort_values("vorp_season", ascending=False)
    starter_cohort = eligible.head(num_teams * starting_slots_per_team)
    positive = starter_cohort.loc[starter_cohort["vorp_season"] > 0]

    total_positive_vorp = float(positive["vorp_season"].sum())
    if total_positive_vorp > 0 and above_min_pool > 0:
        share = positive["vorp_season"] / total_positive_vorp
        out.loc[positive.index, "salary_value"] = (
            min_bid + share * above_min_pool
        ).astype(float)

    return out


def max_bid(
    remaining_budget: int,
    open_slots: int,
    *,
    min_bid: int = 1,
) -> int:
    """Maximum legal bid given remaining budget and open roster slots.

    `max_bid = remaining_budget - (open_slots - 1) * min_bid`

    This is the standard salary cap constraint: after winning one
    player at this bid, every remaining slot must still be fillable at
    `min_bid` each. Assumes `open_slots` includes the slot we'd fill
    by winning this bid (i.e. it's the count *before* the win).

    Returns 0 if the roster is already full or the budget can't even
    cover `min_bid` for the current slot.
    """
    if open_slots <= 0:
        return 0
    return max(0, remaining_budget - (open_slots - 1) * min_bid)


def _enforce_max_per_tier(
    tiers: np.ndarray, rates: np.ndarray,
    max_per_tier: int, max_tiers: int,
) -> np.ndarray:
    """Iteratively split any tier with more than `max_per_tier` members
    at its largest internal gap, until all tiers fit or we'd hit
    `max_tiers`.

    Two safety rails: we never split if it would push us over the tier
    cap, and we don't split a tier whose largest internal gap isn't at
    least 1.5x the tier's median internal gap. The second rule keeps
    uniformly-spaced players from fragmenting into singletons -- if
    every gap inside a fat tier looks the same, there's no defensible
    place to break, so we leave it alone and let the user dial
    `max_per_tier` higher if they don't mind.
    """
    tiers = tiers.copy()
    while int(tiers.max()) < max_tiers:
        sizes = pd.Series(tiers).value_counts()
        oversized = sorted(sizes[sizes > max_per_tier].index.tolist())
        if not oversized:
            break
        # Always split the topmost oversized tier first so tier numbers
        # stay densely allocated to the high-value end of the position.
        target = oversized[0]
        idxs = np.where(tiers == target)[0]
        if idxs.size < 2:
            break
        sub = rates[idxs[0]:idxs[-1] + 1]
        internal = -np.diff(sub)
        if internal.size == 0:
            break
        max_gap = float(internal.max())
        median_gap = float(np.median(internal))
        if max_gap < 1.5 * max(median_gap, 1e-9):
            break
        # idxs[argmax + 1] is the first player on the new (lower) side
        # of the break; everyone from there onward bumps up one tier.
        split_at = idxs[int(np.argmax(internal)) + 1]
        tiers = np.where(np.arange(tiers.size) >= split_at, tiers + 1, tiers)
    return tiers


def assign_tiers(
    projections: pd.DataFrame,
    *,
    by: str = "points_rate",
    positions: Optional[Iterable[str]] = None,
    top_n: int = 30,
    max_tiers: int = 12,
    max_per_tier: int = 12,
    min_gap_z: float = 1.0,
) -> pd.DataFrame:
    """Group players within each position into tiers separated by
    statistically significant gaps in projected output.

    Two-pass algorithm:

    Pass 1 (gap-driven): for each position, sort descending by `by`,
    take the top `top_n` players, and look at consecutive-player gaps
    among that group. Compute median+MAD of just the *upper half* of
    those gaps -- the half-most-significant breaks -- and declare a
    tier boundary wherever a gap exceeds `median + min_gap_z * MAD`.

    Pass 2 (size cap): any resulting tier with more than `max_per_tier`
    members is split at its largest internal gap. Repeats until all
    tiers are size-bounded or `max_tiers` is reached. This is what
    keeps positions like WR -- where the top 3 tiers fall out cleanly
    but the rest is a 20-player smooth descent -- from collapsing
    everything-after-tier-3 into a single unreadable blob.

    Knobs:
    - `min_gap_z` controls Pass 1 strictness. Higher = fewer natural
      breaks recognized.
    - `max_per_tier` controls Pass 2 strictness. Lower = more aggressive
      forced splits inside otherwise-flat regions.
    - `max_tiers` is the hard cap on either pass.

    Players beyond `top_n` at each position get tier = NaN -- they're
    bench/depth and the tier abstraction doesn't apply to them.

    Returns a copy of the input with a new `tier` integer column.
    """
    if positions is None:
        positions = sorted(projections["position"].dropna().unique())

    out = projections.copy()
    out["tier"] = pd.NA

    for pos in positions:
        mask = (out["position"] == pos) & out[by].notna()
        sub = out.loc[mask].sort_values(by=by, ascending=False).head(top_n)
        if sub.empty:
            continue
        rates = sub[by].to_numpy()
        if rates.size == 1:
            out.loc[sub.index, "tier"] = 1
            continue
        gaps = -np.diff(rates)  # positive: how much rank-i beats rank-(i+1)
        if gaps.size == 0:
            threshold = np.inf
        else:
            # Upper half of gaps: where the inter-tier signal lives.
            upper = np.sort(gaps)[-max(gaps.size // 2, 1):]
            median = float(np.median(upper))
            mad = float(np.median(np.abs(upper - median)))
            threshold = median + min_gap_z * max(mad, 1e-9)

        tiers = np.ones(rates.size, dtype=int)
        current = 1
        for i, gap in enumerate(gaps):
            if gap > threshold and current < max_tiers:
                current += 1
            tiers[i + 1] = current
        tiers = _enforce_max_per_tier(tiers, rates, max_per_tier, max_tiers)
        out.loc[sub.index, "tier"] = tiers

    out["tier"] = out["tier"].astype("Int64")
    return out


def load_adp_csv(
    path: str,
    *,
    name_col: str = "Player",
    adp_col: str = "AVG",
    position_col: str = "POS",
    team_col: Optional[str] = "Team",
) -> pd.DataFrame:
    """Load an ADP CSV (FantasyPros / Sleeper / Yahoo-style export) into
    a normalized DataFrame.

    Returns: name, position (cleaned to QB/RB/WR/TE/K/DEF), adp,
    and (optionally) team.
    """
    raw = pd.read_csv(path)
    cols = {name_col: "name", adp_col: "adp", position_col: "position"}
    if team_col and team_col in raw.columns:
        cols[team_col] = "team"
    out = raw.rename(columns=cols)[list(cols.values())].copy()

    # Position strings often include a rank suffix (RB1, WR23) or a
    # platform-specific 'DST' token. Strip both.
    out["position"] = (
        out["position"].astype(str).str.upper()
        .str.replace(r"\d+$", "", regex=True)
        .replace({"DST": "DEF", "D/ST": "DEF"})
    )
    out["adp"] = pd.to_numeric(out["adp"], errors="coerce")
    out = out.dropna(subset=["name", "adp"]).reset_index(drop=True)
    return out


def merge_adp(
    projections: pd.DataFrame,
    adp_df: pd.DataFrame,
    num_teams: int,
) -> pd.DataFrame:
    """Join ADP onto projections and compute value-vs-ADP.

    Adds:
        adp:            average draft pick across sources
        adp_round:      ceil(adp / num_teams)
        proj_rank:      overall rank by points_rate (diagnostic only)
        vorp_rank:      overall rank by vorp_per_game; only set when
                        vorp_per_game is present on the input
        adp_value:      adp - vorp_rank when VORP is available, else
                        adp - proj_rank.  Positive = market under-rates
                        the player relative to your projection.

    Why VORP rank rather than points rank: ranking by absolute fantasy
    points puts QBs at the top of the overall list (passing yards +
    TDs accumulate fast), but the actual draft market knows QB is a
    shallow position and waits on it. That mismatch made every late-
    round QB look like a "value" under a points-based rank. VORP
    centers each position on its own replacement level, so cross-
    position ranks reflect real draft value.

    Players the projection knows about but ADP doesn't get NaN ADP and
    NaN adp_value -- they're presumably undraftable depth.
    """
    out = projections.copy()
    pool_mask = ~out["player_id_sr"].astype(str).str.startswith("avg_")
    out["proj_rank"] = pd.NA
    ranked = out.loc[pool_mask, "points_rate"].rank(method="min", ascending=False)
    out.loc[pool_mask, "proj_rank"] = ranked.astype("Int64")

    has_vorp = "vorp_per_game" in out.columns
    if has_vorp:
        out["vorp_rank"] = pd.NA
        vranked = (out.loc[pool_mask, "vorp_per_game"]
                   .rank(method="min", ascending=False))
        out.loc[pool_mask, "vorp_rank"] = vranked.astype("Int64")

    merged = out.merge(
        adp_df[["name", "position", "adp"]],
        how="left", on=["name", "position"],
    )
    merged["adp_round"] = np.ceil(merged["adp"] / max(num_teams, 1))
    rank_for_value = "vorp_rank" if has_vorp else "proj_rank"
    merged["adp_value"] = merged["adp"] - merged[rank_for_value].astype("Float64")
    return merged


# --------------------------------------------------------------------- #
# Mock draft simulator
# --------------------------------------------------------------------- #


@dataclass
class Roster:
    """Tracks one team's roster during a mock draft.

    `slots` mirrors the league roster_spec for starting positions; each
    pick decrements the most specific eligible slot first, falling back
    to flex, then to bench. We never block a position outright -- a
    team that has filled all its starting RB slots can still draft an
    RB to bench, just at a positional-need penalty.
    """
    starting_slots: Dict[str, int]
    bench_slots: int
    picks: List[dict] = field(default_factory=list)

    @classmethod
    def from_spec(cls, roster_spec) -> "Roster":
        """Build an empty Roster from a roster_spec (DataFrame with
        position/count columns or {slot: count} dict). Bench count comes
        from the BN row/key if present, 0 otherwise."""
        spec = _roster_spec_to_dict(roster_spec)
        bench = 0
        if isinstance(roster_spec, pd.DataFrame):
            bench_row = roster_spec[roster_spec["position"] == "BN"]
            if not bench_row.empty:
                bench = int(bench_row["count"].iloc[0])
        elif isinstance(roster_spec, dict):
            bench = int(roster_spec.get("BN", 0))
        return cls(starting_slots=dict(spec), bench_slots=bench)

    def add(self, pick: dict) -> None:
        self.picks.append(pick)
        pos = pick["position"]
        if self.starting_slots.get(pos, 0) > 0:
            self.starting_slots[pos] -= 1
            return
        for flex_slot, eligible in FLEX_ELIGIBILITY.items():
            if pos in eligible and self.starting_slots.get(flex_slot, 0) > 0:
                self.starting_slots[flex_slot] -= 1
                return
        self.bench_slots = max(self.bench_slots - 1, 0)

    def need_score(self, position: str) -> float:
        """Higher = more urgent need at this position. Used both by
        opponent ADP-noise pickers (to filter absurd selections like a
        4th QB in round 3) and by the user's `'need'` strategy.
        """
        if self.starting_slots.get(position, 0) > 0:
            return 1.0
        for flex_slot, eligible in FLEX_ELIGIBILITY.items():
            if (position in eligible
                    and self.starting_slots.get(flex_slot, 0) > 0):
                return 0.7
        return 0.2 if self.bench_slots > 0 else 0.05


def _build_rosters(roster_spec, num_teams: int) -> List[Roster]:
    return [Roster.from_spec(roster_spec) for _ in range(num_teams)]


def _snake_pick_owner(pick_index: int, num_teams: int, snake: bool) -> int:
    """Return the 0-indexed team owning pick `pick_index` (0-indexed)."""
    rnd = pick_index // num_teams
    slot = pick_index % num_teams
    if snake and rnd % 2 == 1:
        slot = num_teams - 1 - slot
    return slot


def _opponent_pick(
    available: pd.DataFrame,
    pick_overall: int,
    roster: Roster,
    noise_slope: float,
    noise_floor: float,
    rng: np.random.Generator,
) -> int:
    """Choose an index from `available` for an opponent's pick.

    Selection probability is gaussian in the distance from the player's
    ADP to the current overall pick number, with the gaussian's stdev
    scaled by pick number: `sd = max(noise_floor, noise_slope * pick_overall)`.
    Constant-stdev noise was wildly too generous at the top of the
    draft -- in real drafts the top ~3 picks have ADP stdev ~0.5 (the
    elite RBs / WRs always go in the top 3 in some order), but pick
    100 has stdev ~10. Linear-with-floor matches that shape: tight at
    the top, looser deep in the draft.

    Players without ADP get a synthetic late-draft ADP so they only
    get picked once everyone with real ADP is gone.
    """
    adp = available["adp"].to_numpy(dtype=float)
    pos = available["position"].to_numpy()
    adp = np.where(np.isnan(adp), pick_overall + 200.0, adp)
    sd = max(noise_floor, noise_slope * pick_overall)
    z = (adp - pick_overall) / sd
    base_w = np.exp(-0.5 * z * z)
    need = np.array([roster.need_score(p) for p in pos])
    w = base_w * need + 1e-9
    w = w / w.sum()
    return int(rng.choice(np.arange(len(available)), p=w))


def _user_pick(
    available: pd.DataFrame,
    roster: Roster,
    strategy: str,
) -> int:
    """Pick the user's player according to the chosen strategy."""
    if strategy == "bpa":
        return int(available["points_rate"].fillna(-np.inf).to_numpy().argmax())
    if strategy == "vorp":
        # Players at positions the user has 0 starting slots left for
        # get a small VORP penalty so we don't draft a 3rd QB before
        # filling RB. The penalty scales with the remaining draft slots.
        scores = available["vorp_per_game"].fillna(-np.inf).to_numpy()
        need = np.array([roster.need_score(p) for p in available["position"]])
        adjusted = scores * np.where(need > 0.5, 1.0, 0.6)
        return int(adjusted.argmax())
    if strategy == "need":
        # Best VORP at the position with the largest remaining need.
        need = np.array([roster.need_score(p) for p in available["position"]])
        scores = available["vorp_per_game"].fillna(-np.inf).to_numpy()
        return int((scores * need).argmax())
    raise ValueError(f"Unknown user strategy: {strategy!r}")


class MockDraft:
    """Simulate snake (or linear) drafts to evaluate strategies and
    pick positions.

    Opponents pick by sampling near their ADP with gaussian noise; the
    user picks by `my_strategy` ('bpa' / 'vorp' / 'need'). The
    projection pool must already contain `points_rate`, `position`,
    `vorp_per_game` (call `compute_vorp` first), and `adp` (call
    `merge_adp` first).

    Parameters
    ----------
    projections : pd.DataFrame
        Fantasy-relevant players only -- defenses/kickers/etc. that the
        league rosters. The simulator never invents new players.
    roster_spec :
        Yahoo-style roster_spots DataFrame or {slot: count} dict.
    num_teams : int
    my_pick : int
        1-indexed draft slot for the user's team.
    snake : bool
        If True, picks reverse direction every round.
    noise_slope : float
        Per-pick growth rate of the gaussian stdev that scrambles
        opponent picks around their ADP. The effective stdev at pick
        N is `max(noise_floor, noise_slope * N)`. Default 0.1 roughly
        matches FantasyPros ADP stdev shape -- pick 10 has stdev ~1,
        pick 100 has stdev ~10, which is what real drafts look like.
    noise_floor : float
        Minimum gaussian stdev, applied at the top of the draft where
        `noise_slope * N` would otherwise be tiny. Default 1.0 keeps
        the math from degenerating without making pick #1 a coin flip.
    my_strategy : str
        One of 'bpa', 'vorp', 'need'.
    """

    def __init__(
        self,
        projections: pd.DataFrame,
        roster_spec,
        num_teams: int,
        *,
        my_pick: int = 1,
        snake: bool = True,
        noise_slope: float = 0.1,
        noise_floor: float = 1.0,
        my_strategy: str = "vorp",
    ) -> None:
        required = {"name", "position", "points_rate", "vorp_per_game", "adp"}
        missing = required - set(projections.columns)
        if missing:
            raise ValueError(
                f"projections is missing required columns: {sorted(missing)}. "
                "Run compute_vorp() and merge_adp() first."
            )
        if not 1 <= my_pick <= num_teams:
            raise ValueError(
                f"my_pick must be in 1..{num_teams}, got {my_pick}"
            )
        self.projections = projections.reset_index(drop=True)
        self.roster_spec = roster_spec
        self.num_teams = num_teams
        self.my_pick = my_pick
        self.snake = snake
        self.noise_slope = noise_slope
        self.noise_floor = noise_floor
        self.my_strategy = my_strategy

        empty = Roster.from_spec(roster_spec)
        self.starting_slots_per_team = sum(empty.starting_slots.values())
        self.total_picks = (
            self.starting_slots_per_team + empty.bench_slots
        ) * num_teams

    def simulate(self, *, seed: Optional[int] = None) -> pd.DataFrame:
        """Run one mock draft. Returns a DataFrame of picks ordered by
        overall pick number, with columns: pick, round, team, name,
        position, points_rate, vorp_per_game, adp.
        """
        rng = np.random.default_rng(seed)
        rosters = _build_rosters(self.roster_spec, self.num_teams)
        available = self.projections.copy().reset_index(drop=True)
        picks = []
        my_idx = self.my_pick - 1

        for pick in range(self.total_picks):
            owner = _snake_pick_owner(pick, self.num_teams, self.snake)
            if available.empty:
                break

            if owner == my_idx:
                choice = _user_pick(available, rosters[owner], self.my_strategy)
            else:
                choice = _opponent_pick(
                    available, pick + 1, rosters[owner],
                    self.noise_slope, self.noise_floor, rng,
                )

            row = available.iloc[choice]
            pick_record = {
                "pick": pick + 1,
                "round": pick // self.num_teams + 1,
                "team": owner + 1,
                "is_user": owner == my_idx,
                "name": row["name"],
                "position": row["position"],
                "points_rate": row["points_rate"],
                "vorp_per_game": row["vorp_per_game"],
                "adp": row["adp"],
            }
            rosters[owner].add(pick_record)
            picks.append(pick_record)
            available = available.drop(available.index[choice]).reset_index(drop=True)

        return pd.DataFrame(picks)

    def simulate_many(
        self,
        n: int,
        *,
        seed: Optional[int] = None,
    ) -> pd.DataFrame:
        """Run `n` mock drafts; return a tall DataFrame with a `sim`
        column identifying each. Useful for measuring how often a given
        player is available at a given pick number.
        """
        rng = np.random.default_rng(seed)
        frames = []
        for s in range(n):
            child_seed = int(rng.integers(0, 2**31 - 1))
            df = self.simulate(seed=child_seed)
            df.insert(0, "sim", s)
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    def availability(
        self,
        runs: pd.DataFrame,
        pick_number: int,
    ) -> pd.DataFrame:
        """For a tall sim DataFrame from `simulate_many`, compute the
        fraction of sims in which each player was still available when
        `pick_number` came around. Returns name, position, available_pct,
        avg_pick_taken.
        """
        per_sim = runs.groupby(["sim", "name", "position"], as_index=False)["pick"].min()
        n_sims = runs["sim"].nunique()
        per_sim["avail_at"] = (per_sim["pick"] > pick_number).astype(int)
        agg = per_sim.groupby(["name", "position"], as_index=False).agg(
            avail_when_taken=("avail_at", "sum"),
            avg_pick_taken=("pick", "mean"),
            n_sims_taken=("pick", "size"),
        )
        # In sims where a player was never picked, they were available
        # at every pick number -- add those back in.
        agg["available_pct"] = (
            (agg["avail_when_taken"] + (n_sims - agg["n_sims_taken"])) / n_sims
        )
        return agg.sort_values("avg_pick_taken").reset_index(drop=True)
