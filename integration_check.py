#!/usr/bin/env python3
"""
Integration check for the nflreadpy data-provider refactor.

Runs without Yahoo credentials by exercising the data layer and the parts
of PlayerDataManager that don't need a live league. The goal is to catch
regressions from the sportsref_nfl -> nflreadpy swap before stacking the
projection-model overhaul on top.

Usage:
    python integration_check.py

Exits 0 on full pass, 1 if any check fails.
"""

from __future__ import annotations

import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")


_PASSED = 0
_FAILED = 0
_FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        line = f"  [PASS] {label}"
        if detail:
            line += f" ({detail})"
        print(line)
    else:
        _FAILED += 1
        line = f"  [FAIL] {label}"
        if detail:
            line += f" ({detail})"
        print(line)
        _FAILURES.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---- 1. Provider --------------------------------------------------------

section("Provider: get_player_stats")
from nflreadpy_provider import NflreadpyProvider

provider = NflreadpyProvider()
stats = provider.get_player_stats(202401, 202404)

required_stat_cols = {
    "player_id_sr", "name", "position", "team", "opponent",
    "season", "week", "game_id", "points_allowed",
    "rush_yds", "rush_att", "rush_td", "rush_first_down",
    "rec", "rec_yds", "rec_td", "rec_first_down",
    "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
    "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
    "kick_ret_td", "punt_ret_td", "xpm", "fgm",
    "sacks", "def_int", "fumbles_rec", "def_int_td", "fumbles_rec_td",
}
check("returns rows", len(stats) > 500, detail=f"{len(stats)} rows")
check("all required columns present",
      required_stat_cols.issubset(set(stats.columns)),
      detail=f"missing: {required_stat_cols - set(stats.columns) or 'none'}")
positions = set(stats.position.unique())
check("six fantasy positions present",
      {"QB", "RB", "WR", "TE", "K", "DEF"}.issubset(positions),
      detail=f"got: {sorted(positions)}")
def_rows = stats[stats.position == "DEF"]
check("defenses have points_allowed populated",
      def_rows["points_allowed"].notna().all() and len(def_rows) >= 32,
      detail=f"{len(def_rows)} DEF rows, {def_rows['points_allowed'].notna().sum()} non-null")
check("defense sacks in plausible per-game range",
      def_rows["sacks"].between(0, 12).all(),
      detail=f"min={def_rows['sacks'].min()}, max={def_rows['sacks'].max()}")
# Year-range filter: nothing leaks outside 2024 wk 1-4
as_of = stats.season * 100 + stats.week
check("YYYYWW range respected",
      as_of.min() >= 202401 and as_of.max() <= 202404,
      detail=f"{as_of.min()}..{as_of.max()}")


# ---- 2. Schedule --------------------------------------------------------

section("Provider: get_schedule")
sched = provider.get_schedule(2024, 2024)
required_sched_cols = {"season", "week", "date", "team", "home_away",
                       "opp_team", "elo_diff", "opp_elo"}
check("returns rows", len(sched) > 500, detail=f"{len(sched)} rows")
check("all required columns present",
      required_sched_cols.issubset(set(sched.columns)),
      detail=f"missing: {required_sched_cols - set(sched.columns) or 'none'}")
# Two rows per game
home_rows = (sched.home_away == "Home").sum()
away_rows = (sched.home_away == "Away").sum()
check("home and away rows balanced", home_rows == away_rows,
      detail=f"{home_rows} home / {away_rows} away")
# Sign check: KC (home) was favored vs BAL in 2024 W1, so KC's elo_diff > 0
kc_w1 = sched[(sched.season == 2024) & (sched.week == 1) & (sched.team == "KC")]
check("spread sign convention: home favorite has positive elo_diff",
      not kc_w1.empty and float(kc_w1.iloc[0]["elo_diff"]) > 0,
      detail=f"KC W1 elo_diff={float(kc_w1.iloc[0]['elo_diff']):.3f}" if not kc_w1.empty else "KC W1 missing")


# ---- 3. Rosters ---------------------------------------------------------

section("Provider: get_rosters")
rosters = provider.get_rosters(2024, 2024)
check("returns rows", len(rosters) > 1000, detail=f"{len(rosters)} rows")
check("yahoo_id column present", "yahoo_id" in rosters.columns)
yid_pct = rosters["yahoo_id"].notna().mean() if "yahoo_id" in rosters.columns else 0
check("yahoo_id populated for majority of players",
      yid_pct > 0.5, detail=f"{yid_pct:.1%} non-null")
gsis_pct = rosters["player_id_sr"].astype(str).str.match(r"^00-\d{7}$").mean()
check("player_id_sr in gsis format", gsis_pct > 0.9,
      detail=f"{gsis_pct:.1%} match 00-XXXXXXX")


# ---- 4. Depth charts ----------------------------------------------------

section("Provider: get_depth_charts")
dc = provider.get_depth_charts()
check("returns rows", len(dc) > 100, detail=f"{len(dc)} rows")
check("required columns present",
      {"name", "current_team", "position", "string", "player_id_sr"}.issubset(dc.columns))
check("string column populated and numeric",
      dc["string"].notna().all() and pd.api.types.is_numeric_dtype(dc["string"]))
fantasy_positions = set(dc["position"].dropna().unique()) & {"QB", "RB", "WR", "TE"}
check("fantasy positions present", fantasy_positions == {"QB", "RB", "WR", "TE"},
      detail=f"got: {sorted(fantasy_positions)}")


# ---- 5. Team aliases ----------------------------------------------------

section("Provider: team_aliases")
aliases = provider.team_aliases()
check("returns 32 teams", len(aliases) == 32, detail=f"{len(aliases)} rows")
check("yahoo and real_abbrev columns present",
      {"yahoo", "real_abbrev"}.issubset(aliases.columns))
# real_abbrev values must match the team codes in the schedule -- this was
# the regression that bit us during the original refactor.
schedule_teams = set(sched["team"].unique())
alias_teams = set(aliases["real_abbrev"].unique())
check("alias team codes match schedule team codes",
      schedule_teams == alias_teams,
      detail=f"in schedule not aliases: {schedule_teams - alias_teams}; "
             f"in aliases not schedule: {alias_teams - schedule_teams}")


# ---- 6. PlayerDataManager: map_player_ids via yahoo_id ------------------

section("PlayerDataManager: map_player_ids (yahoo_id join)")
from player_data_manager import PlayerDataManager

# Synthesize a Yahoo-style players DataFrame by sampling real yahoo_ids from
# the rosters feed. If map_player_ids does its job, every sampled player
# should round-trip back to the same gsis_id.
sampled = rosters.dropna(subset=["yahoo_id"]).head(20).copy()
yahoo_to_real = aliases.set_index("real_abbrev")["yahoo"].to_dict()
sampled = sampled[sampled["current_team"].isin(yahoo_to_real)]
synthetic_players = pd.DataFrame({
    "player_id": sampled["yahoo_id"].astype(int),
    "name": sampled["name"],
    "position": sampled["position"],
    "editorial_team_abbr": sampled["current_team"].map(yahoo_to_real),
    "status": "",
    "fantasy_team": None,
})
expected_gsis = dict(zip(sampled["yahoo_id"].astype(int),
                         sampled["player_id_sr"]))

# PlayerDataManager only needs season/week for its non-Yahoo paths.
mgr = PlayerDataManager(yahoo_client=None, season=2024, current_week=4,
                        nfl_provider=provider)
mapped = mgr.map_player_ids(synthetic_players)
linked = mapped.dropna(subset=["player_id_sr"])
check("synthesized players linked via yahoo_id",
      len(linked) == len(synthetic_players),
      detail=f"{len(linked)}/{len(synthetic_players)} linked")
correct = sum(
    1 for _, row in linked.iterrows()
    if expected_gsis.get(int(row["player_id"])) == row["player_id_sr"]
)
check("yahoo_id -> gsis mapping correct",
      correct == len(linked), detail=f"{correct}/{len(linked)} correct")


# ---- 7. PlayerDataManager: add_bye_weeks --------------------------------

section("PlayerDataManager: add_bye_weeks")
# Build a tiny players DataFrame with one entry per team, using the same
# team codes the schedule uses (this is the regression we just fixed).
team_players = pd.DataFrame({
    "name": list(schedule_teams),
    "position": "QB",
    "current_team": list(schedule_teams),
})
sched["season"] = sched["season"].astype(int)
sched["week"] = sched["week"].astype(int)
mgr.season = 2024  # ensure bye computation targets a season we have data for
byes = mgr.add_bye_weeks(team_players, sched)
expected_byes = byes["bye_week"].between(1, 19).all()
check("bye weeks computed for every team",
      byes["bye_week"].notna().all(),
      detail=f"{byes['bye_week'].notna().sum()}/{len(byes)} populated")
check("bye weeks in plausible range",
      expected_byes,
      detail=f"min={byes['bye_week'].min()}, max={byes['bye_week'].max()}")


# ---- 8. End-to-end: stats -> scoring -> projection ---------------------

section("End-to-end: stats -> FantasyScorer -> ProjectionEngine")
from fantasy_scoring import FantasyScorer
from projection_engine import ProjectionEngine
from league_configs import apply_default_scoring_categories

ppr_half = apply_default_scoring_categories({
    "Pass Yds": 0.04, "Pass TD": 4, "Int Thrown": -1,
    "Rush Yds": 0.1, "Rush TD": 6,
    "Rec": 0.5, "Rec Yds": 0.1, "Rec TD": 6,
    "Fum Lost": -2,
    "Sack": 1, "Int": 2, "Fum Rec": 2, "Ret TD": 6,
    "Pts Allow 0": 10, "Pts Allow 1-6": 7, "Pts Allow 7-13": 4,
    "Pts Allow 14-20": 1, "Pts Allow 21-27": 0,
    "Pts Allow 28-34": -1, "Pts Allow 35+": -4,
    "PAT Made": 1, "FG 0-19": 3, "FG 20-29": 3, "FG 30-39": 3,
    "FG 40-49": 4, "FG 50+": 5,
})
scorer = FantasyScorer(ppr_half)
scored = scorer.calculate_points(stats)
check("scoring produced points column",
      "points" in scored.columns and scored["points"].notna().all(),
      detail=f"mean={scored['points'].mean():.2f}")

merged = scored.merge(sched, on=["season", "week", "team"], how="left")
check("schedule join populated elo_diff for every row",
      merged["elo_diff"].notna().all(),
      detail=f"{merged['elo_diff'].notna().sum()}/{len(merged)}")

merged["string"] = 1.0
weighting = pd.DataFrame([
    {"position": pos, "basal": 1.0, "opp_elo_weight": 0.05,
     "string_weight": 0.05, "time_scale": 0.01}
    for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]
])
ref_games = {p: 16 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]}
engine = ProjectionEngine(weighting_factors=weighting, reference_games=ref_games)
earliest = {p: 202401 for p in ["QB", "RB", "WR", "TE", "K", "DEF"]}
proj = engine.calculate_projections(merged, earliest, current_week=202405)
check("projections produced",
      len(proj) > 0 and "points_rate" in proj.columns,
      detail=f"{len(proj)} rows")

# Sanity check on top performers: a known-good QB from W1-W4 2024 should
# show up among the top scorers if scoring + projection are wired up.
top_qbs = (
    scored[scored.position == "QB"]
    .groupby(["name"], as_index=False)["points"]
    .sum()
    .nlargest(10, "points")["name"]
    .tolist()
)
known_top_qbs = {"Lamar Jackson", "Jayden Daniels", "Baker Mayfield",
                 "Sam Darnold", "Josh Allen", "Patrick Mahomes"}
check("at least 3 known top QBs in top-10",
      len(known_top_qbs.intersection(top_qbs)) >= 3,
      detail=f"hit: {sorted(known_top_qbs.intersection(top_qbs))}")


# ---- Summary ------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"PASSED: {_PASSED}    FAILED: {_FAILED}")
if _FAILURES:
    print("\nFailures:")
    for f in _FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All integration checks passed.")
sys.exit(0)
