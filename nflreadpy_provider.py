"""
nflreadpy-backed implementation of NFLDataProvider.

Replaces the legacy sportsref_nfl backend, which had grown unreliable due
to Pro Football Reference captchas. nflreadpy reads pre-built parquet
files from the nflverse data releases, so it is fast and unauthenticated.
"""

import warnings
from typing import Iterable

import nflreadpy as nfl
import numpy as np
import pandas as pd

from nfl_data_provider import NFLDataProvider


def _clamp_seasons(
    seasons: list[int], available_max: int, context: str,
) -> list[int]:
    """Drop seasons past `available_max` and warn about it.

    Pre-draft callers routinely request the upcoming season before nflverse
    has uploaded its parquet for it -- e.g. asking for 2026 stats in May
    2026 when nflreadpy's current_season is still 2025. Without clamping,
    nflreadpy either 404s on the missing parquet (stats / schedules) or
    raises ValueError (rosters). Silently dropping the future seasons and
    returning what's available lets the projection engine work off
    historical data, which is what it needs anyway.

    Raises ValueError if every requested season is past `available_max` --
    that would yield an empty result and almost certainly indicates a bug
    in the caller, not just a pre-release timing issue.
    """
    available = [s for s in seasons if s <= available_max]
    dropped = [s for s in seasons if s > available_max]
    if not available:
        raise ValueError(
            f"No available seasons in requested range for {context}: "
            f"requested {seasons}, available through {available_max}."
        )
    if dropped:
        warnings.warn(
            f"Skipping {context} for seasons {dropped}: nflverse data not "
            f"yet available (current_season={available_max}).",
            stacklevel=3,
        )
    return available


# Yahoo's `editorial_team_abbr` -> nflreadpy team code. Yahoo and nflreadpy
# disagree on a handful of teams (Rams: LAR vs LA; Raiders' relocation; the
# Cardinals/Ravens/Texans/Colts/Chargers/Titans triplets the legacy CSV
# stored in PFR-style real_abbrev). Hardcoded here because the active set
# of NFL franchises changes ~once a decade.
_YAHOO_TO_NFL_TEAM = {
    "Ari": "ARI", "Atl": "ATL", "Bal": "BAL", "Buf": "BUF",
    "Car": "CAR", "Chi": "CHI", "Cin": "CIN", "Cle": "CLE",
    "Dal": "DAL", "Den": "DEN", "Det": "DET",  "GB": "GB",
    "Hou": "HOU", "Ind": "IND", "Jax": "JAX",  "KC": "KC",
    "LAC": "LAC", "LAR": "LA",  "Mia": "MIA", "Min": "MIN",
     "NO": "NO",   "NE": "NE",  "NYG": "NYG", "NYJ": "NYJ",
     "LV": "LV",  "Phi": "PHI", "Pit": "PIT", "Sea": "SEA",
     "SF": "SF",   "TB": "TB",  "Ten": "TEN", "Was": "WAS",
}


# Map of stat names from nflreadpy player_stats -> the legacy fantasyfb schema
# expected by fantasy_scoring.FantasyScorer.
_OFFENSE_RENAMES = {
    "rushing_yards": "rush_yds",
    "carries": "rush_att",
    "rushing_tds": "rush_td",
    "rushing_first_downs": "rush_first_down",
    "receptions": "rec",
    "receiving_yards": "rec_yds",
    "receiving_tds": "rec_td",
    "receiving_first_downs": "rec_first_down",
    "passing_yards": "pass_yds",
    "completions": "pass_cmp",
    "passing_tds": "pass_td",
    "passing_first_downs": "pass_first_down",
    "passing_interceptions": "pass_int",
    "kickoff_return_yards": "kick_ret_yds",
    "punt_return_yards": "punt_ret_yds",
    "pat_made": "xpm",
    "fg_made": "fgm",
}


def _years_in_range(start: int, finish: int) -> list[int]:
    """Convert a YYYYWW..YYYYWW range into the list of seasons it covers."""
    return list(range(start // 100, finish // 100 + 1))


class NflreadpyProvider(NFLDataProvider):
    """Concrete NFLDataProvider backed by the nflreadpy parquet feeds."""

    def get_player_stats(self, start: int, finish: int) -> pd.DataFrame:
        seasons = _clamp_seasons(
            _years_in_range(start, finish),
            nfl.get_current_season(),
            "player stats",
        )
        raw = nfl.load_player_stats(seasons=seasons).to_pandas()

        # Restrict to regular season; the legacy package never trained on
        # postseason games either.
        raw = raw[raw["season_type"] == "REG"].copy()

        offense = self._build_offense(raw)
        defense = self._build_defense(raw, seasons)

        stats = pd.concat([offense, defense], ignore_index=True, sort=False)

        as_of = stats["season"] * 100 + stats["week"]
        stats = stats[(as_of >= start) & (as_of <= finish)].reset_index(drop=True)
        return stats

    def _build_offense(self, raw: pd.DataFrame) -> pd.DataFrame:
        offense = raw[raw["position"].isin(["QB", "RB", "WR", "TE", "K"])].copy()

        offense = offense.rename(columns={
            "player_id": "player_id_sr",
            "player_display_name": "name",
            "opponent_team": "opponent",
            **_OFFENSE_RENAMES,
        })

        # Combine all fumble-lost flavors that nflreadpy splits apart.
        for col in ("rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"):
            if col not in offense.columns:
                offense[col] = 0
        offense["fumbles_lost"] = (
            offense["rushing_fumbles_lost"].fillna(0)
            + offense["receiving_fumbles_lost"].fillna(0)
            + offense["sack_fumbles_lost"].fillna(0)
        )

        # nflreadpy reports `special_teams_tds` as a single bucket. The
        # downstream scorer treats kick_ret_td and punt_ret_td identically
        # (same point value), so attributing the whole bucket to one of
        # them is functionally equivalent.
        if "special_teams_tds" not in offense.columns:
            offense["special_teams_tds"] = 0
        offense["kick_ret_td"] = offense["special_teams_tds"].fillna(0)
        offense["punt_ret_td"] = 0

        offense["game_id"] = self._build_game_id(offense)

        keep = [
            "player_id_sr", "name", "position", "team", "opponent",
            "season", "week", "game_id",
            "rush_yds", "rush_att", "rush_td", "rush_first_down",
            "rec", "rec_yds", "rec_td", "rec_first_down",
            "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
            "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
            "kick_ret_td", "punt_ret_td", "xpm", "fgm",
        ]
        offense = offense[[c for c in keep if c in offense.columns]].copy()
        for col in keep:
            if col not in offense.columns:
                offense[col] = 0
        return offense

    def _build_defense(self, raw: pd.DataFrame, seasons: Iterable[int]) -> pd.DataFrame:
        # Aggregate per-player defensive stats up to team-week totals.
        agg_cols = {
            "def_sacks": "sacks",
            "def_interceptions": "def_int",
            "fumble_recovery_opp": "fumbles_rec",
            "def_tds": "def_int_td",
        }
        for src in agg_cols:
            if src not in raw.columns:
                raw[src] = 0

        team_def = (
            raw.groupby(["season", "week", "team", "opponent_team"], as_index=False)[
                list(agg_cols.keys())
            ]
            .sum(numeric_only=True)
            .rename(columns={**agg_cols, "opponent_team": "opponent"})
        )

        # def_tds in nflreadpy combines int-return and fumble-return TDs.
        # The fantasy scorer pays both at the same rate, so attributing
        # the whole bucket to def_int_td is point-equivalent.
        team_def["fumbles_rec_td"] = 0

        # points_allowed comes from the schedule, not the stats feed.
        sched = nfl.load_schedules(seasons=list(seasons)).to_pandas()
        sched = sched[sched["game_type"] == "REG"]
        pts = pd.concat([
            sched[["season", "week", "home_team", "away_score"]].rename(
                columns={"home_team": "team", "away_score": "points_allowed"}),
            sched[["season", "week", "away_team", "home_score"]].rename(
                columns={"away_team": "team", "home_score": "points_allowed"}),
        ], ignore_index=True)
        team_def = team_def.merge(pts, on=["season", "week", "team"], how="left")

        team_def["position"] = "DEF"
        team_def["name"] = team_def["team"]
        team_def["player_id_sr"] = team_def["team"]
        team_def["game_id"] = self._build_game_id(team_def)

        # Zero out offensive columns so concat with offense lines up cleanly.
        for col in [
            "rush_yds", "rush_att", "rush_td", "rush_first_down",
            "rec", "rec_yds", "rec_td", "rec_first_down",
            "pass_yds", "pass_cmp", "pass_td", "pass_first_down", "pass_int",
            "fumbles_lost", "kick_ret_yds", "punt_ret_yds",
            "kick_ret_td", "punt_ret_td", "xpm", "fgm",
        ]:
            team_def[col] = 0

        return team_def

    @staticmethod
    def _build_game_id(df: pd.DataFrame) -> pd.Series:
        return (
            df["season"].astype(str)
            + "_"
            + df["week"].astype(int).astype(str).str.zfill(2)
            + "_"
            + df["team"].astype(str)
        )

    def get_schedule(self, start_year: int, end_year: int) -> pd.DataFrame:
        seasons = _clamp_seasons(
            list(range(start_year, end_year + 1)),
            nfl.get_current_season(),
            "schedule",
        )
        raw = nfl.load_schedules(seasons=seasons).to_pandas()
        raw = raw[raw["game_type"] == "REG"].copy()
        raw["date"] = pd.to_datetime(raw["gameday"], errors="coerce")

        # In nflreadpy, positive spread_line = home team favored (verified
        # empirically on 2024 W1 games). A team's elo_diff under the legacy
        # convention is positive when that team is favored.
        #
        # The divisor matches elo_diff to the scale the legacy sportsref_nfl
        # provider produced (range ~±0.25, vs the ~±1.0 you'd get from a
        # naive spread/14). The remote weighting_factors.csv was MLE-fit
        # against that legacy scale, so we preserve it here. Empirically
        # back-fit from 2025 W12: spread / 60 lands within the old range,
        # though correlation isn't perfect since the legacy provider used
        # Elo ratings (team-strength prior) while we only have per-game
        # spreads. Good enough until weighting_factors.csv is refit.
        spread = raw["spread_line"].fillna(0).astype(float)
        total = raw["total_line"].fillna(0).astype(float)
        elo_divisor = 60.0

        # Per-team Vegas implied scoring totals. With spread sign convention
        # "positive = home favored", the home team's implied total is
        # (total + spread)/2 and the away team's is (total - spread)/2 --
        # they sum to the over/under by construction. These let downstream
        # matchup models reason about the scoring environment directly,
        # rather than the win-probability proxy we get from the spread alone.
        home_implied = (total + spread) / 2.0
        away_implied = (total - spread) / 2.0

        home = pd.DataFrame({
            "season": raw["season"],
            "week": raw["week"],
            "date": raw["date"],
            "team": raw["home_team"],
            "opp_team": raw["away_team"],
            "home_away": "Home",
            "elo_diff": spread / elo_divisor,
            "opp_elo": 1.0,
            "spread_line": spread,
            "total_line": total,
            "implied_total": home_implied,
            "opp_implied_total": away_implied,
        })
        away = pd.DataFrame({
            "season": raw["season"],
            "week": raw["week"],
            "date": raw["date"],
            "team": raw["away_team"],
            "opp_team": raw["home_team"],
            "home_away": "Away",
            "elo_diff": -spread / elo_divisor,
            "opp_elo": 1.0,
            "spread_line": -spread,
            "total_line": total,
            "implied_total": away_implied,
            "opp_implied_total": home_implied,
        })
        out = pd.concat([home, away], ignore_index=True)
        return out.sort_values(["season", "week"], ignore_index=True)

    def get_rosters(self, start_year: int, end_year: int) -> pd.DataFrame:
        seasons = _clamp_seasons(
            list(range(start_year, end_year + 1)),
            nfl.get_current_season(),
            "rosters",
        )
        raw = nfl.load_rosters_weekly(seasons=seasons).to_pandas()

        # Take the most recent week we have for each (season, player) so
        # `current_team` reflects late-season trades and call-ups rather
        # than week-1 rosters.
        raw = raw.sort_values(["season", "week"]).drop_duplicates(
            subset=["season", "gsis_id"], keep="last"
        )

        out = raw.rename(columns={
            "gsis_id": "player_id_sr",
            "full_name": "name",
            "team": "current_team",
        })
        cols = ["name", "current_team", "position", "player_id_sr", "yahoo_id", "season"]
        return out[[c for c in cols if c in out.columns]].reset_index(drop=True)

    def get_depth_charts(self) -> pd.DataFrame:
        # nflreadpy reworked the depth-chart schema starting in 2025: the
        # old (season, week, club_code, depth_team, full_name) shape was
        # replaced with (dt, team, player_name, pos_abb, pos_rank). We
        # support both because mid-package upgrades shouldn't trip up
        # users still pulling historical seasons.
        latest = pd.Timestamp.now(tz="UTC").year
        raw = nfl.load_depth_charts(seasons=[latest]).to_pandas()
        if raw.empty and latest > 1999:
            raw = nfl.load_depth_charts(seasons=[latest - 1]).to_pandas()
        if raw.empty:
            return pd.DataFrame(columns=["name", "current_team", "position", "string", "player_id_sr"])

        if "pos_rank" in raw.columns:
            # New schema (2025+): keep only the latest snapshot.
            raw = raw[raw["dt"] == raw["dt"].max()]
            out = raw.rename(columns={
                "gsis_id": "player_id_sr",
                "player_name": "name",
                "team": "current_team",
                "pos_abb": "position",
                "pos_rank": "string",
            })
        else:
            # Legacy schema (<=2024): keep the most recent week we have.
            raw = raw[raw["week"] == raw["week"].max()]
            out = raw.rename(columns={
                "gsis_id": "player_id_sr",
                "full_name": "name",
                "club_code": "current_team",
                "depth_team": "string",
            })

        out["string"] = pd.to_numeric(out["string"], errors="coerce").fillna(2.0)
        return out[["name", "current_team", "position", "string", "player_id_sr"]].reset_index(drop=True)

    def get_draft(self, year: int) -> pd.DataFrame:
        raw = nfl.load_draft_picks(seasons=[year]).to_pandas()
        out = raw.rename(columns={
            "gsis_id": "player_id_sr",
            "pfr_player_name": "name",
            "team": "current_team",
        })
        return out[["name", "current_team", "player_id_sr"]].reset_index(drop=True)

    def team_aliases(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"yahoo": y, "real_abbrev": t} for y, t in _YAHOO_TO_NFL_TEAM.items()]
        )
