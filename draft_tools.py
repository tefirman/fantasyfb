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
    assign_tiers(projections, ...)
    load_adp_csv(path, ...)
    merge_adp(projections, adp_df, num_teams)
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
_FLEX_ELIGIBILITY: Dict[str, tuple[str, ...]] = {
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
        elif slot in _FLEX_ELIGIBILITY:
            eligible = _FLEX_ELIGIBILITY[slot]
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


def assign_tiers(
    projections: pd.DataFrame,
    *,
    by: str = "points_rate",
    positions: Optional[Iterable[str]] = None,
    top_n: int = 30,
    max_tiers: int = 12,
    min_gap_z: float = 2.5,
) -> pd.DataFrame:
    """Group players within each position into tiers separated by
    statistically significant gaps in projected output.

    Algorithm: for each position, sort descending by `by`, take the
    top `top_n` players, and look at consecutive-player gaps among
    that group. Compute median+MAD of just the *upper half* of those
    gaps -- the half-most-significant breaks -- and declare a tier
    boundary wherever a gap exceeds `median + min_gap_z * MAD`. Tiers
    are 1-indexed from the top and capped at `max_tiers`.

    Three design choices, each fallout from real-data runs that
    produced one-player-per-tier nonsense at earlier iterations:

    1. Restrict to top_n. Fantasy projections have a long tail of
       depth players whose rates differ by ~0.05 pts. Letting those
       gaps influence the threshold drags it down. Tiers only matter
       for draftable players anyway.

    2. Use only the upper half of gaps when computing the threshold.
       Even within the top_n, intra-tier gaps (small) outnumber inter-
       tier gaps (large), and the small ones cluster tightly enough
       that median+MAD computed over all gaps would still be too low.
       Filtering to the upper half discards the within-tier noise and
       calibrates the threshold against the actual signal -- the
       typical inter-tier break.

    3. Median+MAD instead of mean+std for robustness. Gap distributions
       are heavy-tailed; mean+std is dominated by a few huge outliers,
       which paradoxically lowers the bar for "real" breaks once you
       subtract one std.

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
        proj_rank:      overall rank by points_rate among the full pool
        adp_value:      adp - proj_rank.  Positive = market under-rates
                        the player relative to your projection (a value
                        pick); negative = market over-rates.

    Players the projection knows about but ADP doesn't get NaN ADP and
    NaN adp_value, which is the right behavior -- they're presumably
    undraftable depth and shouldn't be flagged as huge values.
    """
    out = projections.copy()
    pool_mask = ~out["player_id_sr"].astype(str).str.startswith("avg_")
    out["proj_rank"] = pd.NA
    ranked = out.loc[pool_mask, "points_rate"].rank(method="min", ascending=False)
    out.loc[pool_mask, "proj_rank"] = ranked.astype("Int64")

    merged = out.merge(
        adp_df[["name", "position", "adp"]],
        how="left", on=["name", "position"],
    )
    merged["adp_round"] = np.ceil(merged["adp"] / max(num_teams, 1))
    merged["adp_value"] = merged["adp"] - merged["proj_rank"].astype("Float64")
    return merged


# --------------------------------------------------------------------- #
# Mock draft simulator
# --------------------------------------------------------------------- #


@dataclass
class _Roster:
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

    def add(self, pick: dict) -> None:
        self.picks.append(pick)
        pos = pick["position"]
        if self.starting_slots.get(pos, 0) > 0:
            self.starting_slots[pos] -= 1
            return
        for flex_slot, eligible in _FLEX_ELIGIBILITY.items():
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
        for flex_slot, eligible in _FLEX_ELIGIBILITY.items():
            if (position in eligible
                    and self.starting_slots.get(flex_slot, 0) > 0):
                return 0.7
        return 0.2 if self.bench_slots > 0 else 0.05


def _build_rosters(roster_spec, num_teams: int) -> List[_Roster]:
    spec = _roster_spec_to_dict(roster_spec)
    bench = 0
    if isinstance(roster_spec, pd.DataFrame):
        bench_row = roster_spec[roster_spec["position"] == "BN"]
        if not bench_row.empty:
            bench = int(bench_row["count"].iloc[0])
    elif isinstance(roster_spec, dict):
        bench = int(roster_spec.get("BN", 0))
    return [_Roster(starting_slots=dict(spec), bench_slots=bench)
            for _ in range(num_teams)]


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
    roster: _Roster,
    noise_sd: float,
    rng: np.random.Generator,
) -> int:
    """Choose an index from `available` for an opponent's pick.

    Selection probability is gaussian in the distance from the player's
    ADP to the current overall pick number, scaled by the team's
    positional need. Players without ADP get a tiny floor weight so
    they're occasionally taken late. Returns the row index in `available`.
    """
    adp = available["adp"].to_numpy(dtype=float)
    pos = available["position"].to_numpy()
    # Default ADP for unknown players: end of the draft, far from any
    # current pick, so they only get picked if everyone with ADP is gone.
    adp = np.where(np.isnan(adp), pick_overall + 200.0, adp)
    z = (adp - pick_overall) / max(noise_sd, 1e-6)
    base_w = np.exp(-0.5 * z * z)
    need = np.array([roster.need_score(p) for p in pos])
    w = base_w * need + 1e-9
    w = w / w.sum()
    return int(rng.choice(np.arange(len(available)), p=w))


def _user_pick(
    available: pd.DataFrame,
    roster: _Roster,
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
    noise_sd : float
        Standard deviation, in pick numbers, of the gaussian around ADP
        used to model opponent picks. ~6-10 matches observed real-draft
        variance for redraft leagues.
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
        noise_sd: float = 8.0,
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
        self.noise_sd = noise_sd
        self.my_strategy = my_strategy

        spec = _roster_spec_to_dict(roster_spec)
        self.starting_slots_per_team = sum(spec.values())
        bench = 0
        if isinstance(roster_spec, pd.DataFrame):
            bench_row = roster_spec[roster_spec["position"] == "BN"]
            if not bench_row.empty:
                bench = int(bench_row["count"].iloc[0])
        elif isinstance(roster_spec, dict):
            bench = int(roster_spec.get("BN", 0))
        self.total_picks = (self.starting_slots_per_team + bench) * num_teams

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
                    self.noise_sd, rng,
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
