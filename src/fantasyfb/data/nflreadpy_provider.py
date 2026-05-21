"""
nflreadpy-backed implementation of NFLDataProvider.

Replaces the legacy sportsref_nfl backend, which had grown unreliable due
to Pro Football Reference captchas. nflreadpy reads pre-built parquet
files from the nflverse data releases, so it is fast and unauthenticated.
"""

import io
import re
import urllib.request
import warnings
from typing import Any, Callable, Iterable

import nflreadpy as nfl
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .nfl_provider import NFLDataProvider


# nflreadpy uses polars to parse the parquet files it downloads from
# nflverse. Polars' UTF-8 validation is stricter than pyarrow's, and the
# nflverse parquet exports periodically contain a stray non-UTF-8 byte in
# a string column (e.g. mojibake in a stadium name). Polars rejects the
# whole file; pyarrow reads it without complaint. nflreadpy re-raises the
# polars error as ValueError("Failed to parse data from {url}: ...
# parquet: File out of specification: String data contained invalid
# UTF-8"). When we see that exact signature, fall back to downloading the
# same URL ourselves and parsing with pyarrow.
_POLARS_UTF8_SIGNATURE = "String data contained invalid UTF-8"
_NFLREADPY_PARSE_URL_RE = re.compile(r"Failed to parse data from (\S+):")


def _is_polars_utf8_error(exc: BaseException) -> str | None:
    """Return the upstream URL if `exc` is the polars UTF-8 parquet error."""
    if not isinstance(exc, ValueError):
        return None
    msg = str(exc)
    if _POLARS_UTF8_SIGNATURE not in msg:
        return None
    match = _NFLREADPY_PARSE_URL_RE.search(msg)
    return match.group(1) if match else None


def _sanitize_string_columns(table: pa.Table) -> pa.Table:
    """Replace invalid UTF-8 bytes in string columns with U+FFFD.

    On Python 3.10 pyarrow's `.to_pandas()` raises when converting an
    Arrow string array that contains bytes Python's str constructor
    can't decode (e.g. the `Levi's<bad byte> Stadium` value nflverse
    currently ships). Newer pyarrow + Python versions are more
    permissive. We cast to binary and decode in Python with
    errors="replace" so the bad bytes become the Unicode replacement
    character and `to_pandas()` succeeds everywhere.
    """
    new_columns = []
    for name in table.column_names:
        col = table.column(name)
        if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
            binary = col.combine_chunks().cast(pa.binary())
            decoded = [
                None if v is None else v.decode("utf-8", errors="replace")
                for v in binary.to_pylist()
            ]
            new_columns.append(pa.array(decoded, type=pa.string()))
        else:
            new_columns.append(col)
    return pa.table(new_columns, names=table.column_names)


def _pyarrow_fallback(url: str) -> pd.DataFrame:
    """Download `url` directly and parse with pyarrow, returning pandas."""
    warnings.warn(
        f"polars rejected {url} as invalid UTF-8; falling back to pyarrow.",
        stacklevel=3,
    )
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - nflverse URL
        content = resp.read()
    table = pq.read_table(io.BytesIO(content))
    return _sanitize_string_columns(table).to_pandas()


def _load_pandas(
    loader: Callable[..., Any],
    *,
    per_season: bool = False,
    **kwargs: Any,
) -> pd.DataFrame:
    """Call an nflreadpy loader and return a pandas DataFrame.

    Falls back to pyarrow if polars rejects the upstream parquet for
    invalid UTF-8 (see module-level comment).

    `per_season=True` is for loaders that download one parquet per
    season and concatenate (load_player_stats, load_rosters_weekly,
    load_depth_charts, load_draft_picks). When set, on first failure we
    retry season-by-season so a single bad season doesn't lose the
    others. `per_season=False` is for single-file loaders
    (load_schedules) where one URL covers all seasons; we just download
    that URL and apply the season filter ourselves.
    """
    try:
        return loader(**kwargs).to_pandas()
    except ValueError as exc:
        url = _is_polars_utf8_error(exc)
        if url is None:
            raise
        if not per_season:
            df = _pyarrow_fallback(url)
            seasons = kwargs.get("seasons")
            if isinstance(seasons, list) and "season" in df.columns:
                df = df[df["season"].isin(seasons)].reset_index(drop=True)
            return df
        seasons = kwargs.get("seasons") or []
        if not isinstance(seasons, list) or len(seasons) <= 1:
            return _pyarrow_fallback(url)
        # Retry per-season, falling back individually for the broken one.
        frames: list[pd.DataFrame] = []
        for season in seasons:
            single = {**kwargs, "seasons": [season]}
            try:
                frames.append(loader(**single).to_pandas())
            except ValueError as inner:
                inner_url = _is_polars_utf8_error(inner)
                if inner_url is None:
                    raise
                frames.append(_pyarrow_fallback(inner_url))
        return pd.concat(frames, ignore_index=True)


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
        raw = _load_pandas(nfl.load_player_stats, per_season=True, seasons=seasons)

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
        sched = _load_pandas(nfl.load_schedules, seasons=list(seasons))
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
        raw = _load_pandas(nfl.load_schedules, seasons=seasons)
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
        raw = _load_pandas(nfl.load_rosters_weekly, per_season=True, seasons=seasons)

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
        raw = _load_pandas(nfl.load_depth_charts, per_season=True, seasons=[latest])
        if raw.empty and latest > 1999:
            raw = _load_pandas(nfl.load_depth_charts, per_season=True, seasons=[latest - 1])
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
        raw = _load_pandas(nfl.load_draft_picks, seasons=[year])
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
