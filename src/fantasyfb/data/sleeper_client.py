"""
Sleeper Fantasy API client.

Sleeper's read API is public and unauthenticated -- no OAuth, no app
registration, just a league ID off the league's URL
(sleeper.com/leagues/<league_id>/...). Two things live here:

- Module-level functions for pulling a league's scoring/roster settings
  (used to bootstrap e.g. Scott Fish Bowl scoring, which runs on Sleeper).
- `SleeperClient`, a full client covering the same surface as
  `YahooFantasyClient` (teams, rosters, schedule, player pool) so a
  Sleeper-only league doesn't need a Yahoo league underneath it. It's
  intentionally standalone rather than wired into `League.__init__` --
  see issue #37 for the follow-up `FantasyPlatformClient` abstraction
  that would let `League` pick either backend.

Sleeper has no public write API (no transactions, no lineup changes), so
`SleeperClient` is read-only regardless of scope.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from .platform_client import FantasyPlatformClient

BASE_URL = "https://api.sleeper.app/v1"

# Fantasy-relevant positions kept from Sleeper's full /players/nfl map;
# everything else (LS, coaches, practice-squad-only entries, etc.) is
# noise for fantasyfb's purposes.
_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Sleeper's /players/nfl payload is the full static player map (~11k
# players, several MB) and Sleeper asks integrators not to hit it more
# than once a day: https://docs.sleeper.com/#fetch-all-players. Cached
# locally rather than re-fetched every run.
DEFAULT_PLAYERS_CACHE_PATH = os.path.join(
    os.path.expanduser("~"), ".cache", "fantasyfb", "sleeper_players.json"
)
PLAYERS_CACHE_TTL_SECONDS = 24 * 60 * 60

# Direct 1:1 mappings from Sleeper scoring_settings keys to fantasyfb's
# internal scoring schema (see FantasyScorer / configs.apply_default_scoring_categories).
_DIRECT_SCORING_MAP = {
    "pass_yd": "Pass Yds",
    "pass_cmp": "Pass Comp",
    "pass_td": "Pass TD",
    "pass_fd": "Pass 1D",
    "pass_int": "Int Thrown",
    "pass_2pt": "2-PT",
    "rush_yd": "Rush Yds",
    "rush_att": "Rush Att",
    "rush_td": "Rush TD",
    "rush_fd": "Rush 1D",
    "rush_2pt": "2-PT",
    "rec": "Rec",
    "rec_yd": "Rec Yds",
    "rec_td": "Rec TD",
    "rec_fd": "Rec 1D",
    "rec_2pt": "2-PT",
    "fum_lost": "Fum Lost",
    "fum_rec_td": "Fum Ret TD",
    "bonus_rec_te": "TE Rec Bonus",
    "bonus_fd_te": "TE 1D Bonus",
    "bonus_pass_yd_300": "Pass 300+",
    "bonus_pass_yd_400": "Pass 400+",
    "bonus_rush_yd_100": "Rush 100+",
    "bonus_rush_yd_200": "Rush 200+",
    "bonus_rec_yd_100": "Rec 100+",
    "bonus_rec_yd_200": "Rec 200+",
    "bonus_rush_rec_yd_100": "Rush+Rec 100+",
    "bonus_rush_rec_yd_200": "Rush+Rec 200+",
    "sack": "Sack",
    "int": "Int",
    "fum_rec": "Fum Rec",
    "safe": "Safe",
    "blk_kick": "Blk Kick",
    "fgm_0_19": "FG 0-19",
    "fgm_20_29": "FG 20-29",
    "fgm_30_39": "FG 30-39",
    "fgm_40_49": "FG 40-49",
    "fgm_50p": "FG 50+",
    "xpm": "PAT Made",
    "pts_allow_0": "Pts Allow 0",
    "pts_allow_1_6": "Pts Allow 1-6",
    "pts_allow_7_13": "Pts Allow 7-13",
    "pts_allow_14_20": "Pts Allow 14-20",
    "pts_allow_21_27": "Pts Allow 21-27",
    "pts_allow_28_34": "Pts Allow 28-34",
    "pts_allow_35p": "Pts Allow 35+",
}

# Return-TD keys: whichever of these fires, it's the same "Ret TD" bucket
# FantasyScorer already uses for kick/punt/fumble/INT return scores.
_RET_TD_KEYS = ("st_td", "def_st_td")

# Return-yardage keys: FantasyScorer applies one combined rate to
# (kick_ret_yds + punt_ret_yds), so Sleeper's split kr_yd/pr_yd rates can
# only be translated exactly when they match. Falls back to whichever is
# non-zero when they differ.
_RET_YD_KEYS = ("kr_yd", "pr_yd")

# Sleeper keys that are intentionally NOT translated: per-play "long play"
# bonuses (a 40+ yard completion/rush, a 20-29/30-39/40+ yard reception)
# require play-by-play data to compute -- FantasyScorer only has per-game
# box-score aggregates. Listed here so a future pass wiring up
# nflreadpy play-by-play knows exactly what's missing.
UNSUPPORTED_SCORING_KEYS = (
    "pass_cmp_40p", "pass_td_40p", "rush_40p",
    "rec_40p", "rec_20_29", "rec_30_39",
    "bonus_sack_2p", "bonus_tkl_10p",
)

# Sleeper roster-slot labels -> fantasyfb roster_spots position labels.
_POSITION_MAP = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "DEF": "DEF",
    "FLEX": "W/R/T",
    "SUPER_FLEX": "Q/W/R/T",
    "WRRB_FLEX": "W/R/T",
    "REC_FLEX": "W/R/T",
    "BN": "BN",
    "IR": "IR",
}


def fetch_league(league_id: str) -> Dict:
    """
    Pull raw league settings from Sleeper's public API.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        Raw league JSON, including 'scoring_settings' and 'roster_positions'.
    """
    resp = requests.get(f"{BASE_URL}/league/{league_id}")
    resp.raise_for_status()
    return resp.json()


def translate_scoring_settings(scoring_settings: Dict[str, float]) -> Dict[str, float]:
    """
    Convert Sleeper's scoring_settings dict into fantasyfb's internal schema.

    Args:
        scoring_settings: the 'scoring_settings' block of a Sleeper league payload.

    Returns:
        Dict keyed by fantasyfb scoring category names.
    """
    from ..configs import apply_default_scoring_categories

    scoring: Dict[str, float] = {}
    for sleeper_key, fantasyfb_key in _DIRECT_SCORING_MAP.items():
        value = scoring_settings.get(sleeper_key, 0.0)
        if fantasyfb_key == "2-PT":
            # All three 2pt variants map to one category; keep the max
            # magnitude in the (expected) common case they all agree.
            scoring[fantasyfb_key] = max(scoring.get(fantasyfb_key, 0.0), value)
        else:
            scoring[fantasyfb_key] = value

    ret_td_values = [scoring_settings.get(k, 0.0) for k in _RET_TD_KEYS]
    scoring["Ret TD"] = max(ret_td_values) if ret_td_values else 0.0

    ret_yd_values = [scoring_settings.get(k, 0.0) for k in _RET_YD_KEYS]
    nonzero_ret_yds = [v for v in ret_yd_values if v != 0.0]
    scoring["Ret Yds"] = nonzero_ret_yds[0] if nonzero_ret_yds else 0.0

    return apply_default_scoring_categories(scoring)


def translate_roster_positions(roster_positions: List[str]) -> pd.DataFrame:
    """
    Convert Sleeper's flat roster_positions list into a fantasyfb roster_spots DataFrame.

    Args:
        roster_positions: the 'roster_positions' list of a Sleeper league payload,
            e.g. ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", ...].

    Returns:
        DataFrame with 'position' and 'count' columns.
    """
    counts: Dict[str, int] = {}
    for slot in roster_positions:
        mapped = _POSITION_MAP.get(slot, slot)
        counts[mapped] = counts.get(mapped, 0) + 1

    return pd.DataFrame(
        {"position": list(counts.keys()), "count": list(counts.values())}
    )


def get_league_config(league_id: str) -> Dict:
    """
    Fetch and translate a Sleeper league's scoring/roster settings.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        Dict with 'scoring' and 'roster_spots' keys, matching the shape
        of the static configs in fantasyfb.configs (e.g. DRAFTKINGS_CONFIG)
        so it can be used interchangeably wherever a league config is expected.
    """
    league = fetch_league(league_id)
    return {
        "scoring": translate_scoring_settings(league["scoring_settings"]),
        "roster_spots": translate_roster_positions(league["roster_positions"]),
    }


def fetch_draft(draft_id: str) -> Dict:
    """
    Pull raw draft settings from Sleeper's public API.

    Args:
        draft_id: numeric Sleeper draft ID (found on the league payload's
            'draft_id' field, e.g. via fetch_league()).

    Returns:
        Raw draft JSON, including the 'settings' block ('reversal_round',
        'rounds', 'teams', etc.).
    """
    resp = requests.get(f"{BASE_URL}/draft/{draft_id}")
    resp.raise_for_status()
    return resp.json()


def get_reversal_round(league_id: str) -> int:
    """
    Look up a league's Third-Round Reversal setting directly from Sleeper.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        The round number TRR applies at, or 0 if disabled -- matches the
        `reversal_round` kwarg on drafts.tools.MockDraft / the
        `--reversal-round` CLI flag on snake-draft and draft-prep mock.
    """
    league = fetch_league(league_id)
    draft = fetch_draft(league["draft_id"])
    return draft["settings"].get("reversal_round", 0)


def fetch_users(league_id: str) -> List[Dict]:
    """
    Pull raw league membership (one entry per Sleeper account) from Sleeper's public API.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        List of user JSON objects, including 'user_id', 'display_name', and
        'metadata' (which may carry a commissioner-set 'team_name').
    """
    resp = requests.get(f"{BASE_URL}/league/{league_id}/users")
    resp.raise_for_status()
    return resp.json()


def fetch_rosters(league_id: str) -> List[Dict]:
    """
    Pull raw current rosters from Sleeper's public API.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        List of roster JSON objects, including 'roster_id', 'owner_id',
        'players' (full roster), 'starters', and 'reserve' (IR-tagged players).
    """
    resp = requests.get(f"{BASE_URL}/league/{league_id}/rosters")
    resp.raise_for_status()
    return resp.json()


def fetch_matchups(league_id: str, week: int) -> List[Dict]:
    """
    Pull raw per-team matchup data for a single week from Sleeper's public API.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).
        week: week number to pull matchups for.

    Returns:
        List of per-roster matchup JSON objects, including 'roster_id',
        'matchup_id' (shared by the two rosters facing off), 'points', and
        that week's 'starters'/'players'. Empty list for weeks with no
        matchup data yet (e.g. future weeks, preseason).
    """
    resp = requests.get(f"{BASE_URL}/league/{league_id}/matchups/{week}")
    resp.raise_for_status()
    return resp.json() or []


def fetch_nfl_state() -> Dict:
    """
    Pull the current NFL/fantasy week from Sleeper's public API.

    Returns:
        Raw state JSON, including 'week' (the actual NFL week) and
        'display_week' (the week Sleeper recommends leagues use for
        fantasy purposes, which can lead 'week' during preseason).
    """
    resp = requests.get(f"{BASE_URL}/state/nfl")
    resp.raise_for_status()
    return resp.json()


def fetch_all_players(
    cache_path: str = DEFAULT_PLAYERS_CACHE_PATH,
    max_age_seconds: int = PLAYERS_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
) -> Dict[str, Dict]:
    """
    Fetch Sleeper's full static player map, using a local on-disk cache.

    Args:
        cache_path: where to read/write the cached JSON.
        max_age_seconds: how long a cached copy is considered fresh.
        force_refresh: bypass the cache and re-fetch unconditionally.

    Returns:
        Dict keyed by Sleeper player_id (numeric string for individual
        players, team abbreviation for DEF entries).
    """
    if not force_refresh and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < max_age_seconds:
            with open(cache_path) as f:
                return json.load(f)

    resp = requests.get(f"{BASE_URL}/players/nfl")
    resp.raise_for_status()
    players = resp.json()

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(players, f)

    return players


def _starting_slots(roster_positions: List[str]) -> List[str]:
    """
    Reduce a league's roster_positions list to just the starting slots, in order.

    Sleeper's per-team 'starters' arrays (from /rosters and /matchups) are
    ordered to line up 1:1 with these slots, so zipping starters against
    this list recovers each starter's selected_position.
    """
    return [
        _POSITION_MAP.get(slot, slot)
        for slot in roster_positions
        if slot not in ("BN", "IR")
    ]


class SleeperClient(FantasyPlatformClient):
    """
    Client for interacting with Sleeper's public Fantasy API.

    Covers the same surface as YahooFantasyClient (teams, rosters,
    schedule, player pool) for leagues that live entirely on Sleeper.
    Sleeper's read API needs no authentication, so there's no OAuth
    handshake or token refresh to manage; there's also no public write
    API, so this client is read-only.
    """

    def __init__(self, league_id: str, my_team_name: Optional[str] = None):
        """
        Args:
            league_id: numeric Sleeper league ID (from the league URL).
            my_team_name: team or manager display name identifying which
                roster is "mine" -- Sleeper's public API has no OAuth
                "logged in as" concept, so this is the only way to resolve
                get_my_team_key(). Optional; leave unset for read-only
                league-wide analysis with no "my team" concept.
        """
        self.league_id = league_id
        self.my_team_name = my_team_name

    def get_current_week(self) -> int:
        """
        Get the current fantasy week.

        Returns:
            Sleeper's 'display_week' (falling back to 'week' if absent) --
            the week Sleeper recommends leagues use for fantasy purposes.
        """
        state = fetch_nfl_state()
        return int(state.get("display_week") or state.get("week") or 1)

    def get_league_config(self) -> Dict:
        """
        Get league settings, scoring, and roster composition in the shape
        FantasyPlatformClient callers expect.

        Returns:
            Dict with 'settings' (playoff_start_week, num_playoff_teams,
            end_week), 'scoring', and 'roster_spots' keys.
        """
        league = fetch_league(self.league_id)
        config = get_league_config(self.league_id)

        raw_settings = league.get("settings") or {}
        # playoff_week_start is 0 for leagues that haven't configured it
        # (observed on SFB16 mid-season) -- not a valid week, so fall back
        # to fantasyfb's own default rather than deriving a bogus end_week.
        playoff_start_week = int(raw_settings.get("playoff_week_start") or 0) or 15
        num_playoff_teams = int(raw_settings.get("playoff_teams") or 0) or 6
        settings = {
            "playoff_start_week": playoff_start_week,
            "num_playoff_teams": num_playoff_teams,
            "end_week": playoff_start_week + (2 if num_playoff_teams == 6 else 1),
        }
        config["settings"] = settings
        return config

    def get_my_team_key(self) -> Optional[str]:
        """
        Get the team_key of the team identified by my_team_name.

        Returns:
            The matched team's team_key (matching name first, then
            manager), or None if my_team_name wasn't set or didn't match
            any team.
        """
        if not self.my_team_name:
            return None
        for team in self.get_fantasy_teams():
            if team["name"] == self.my_team_name:
                return team["team_key"]
        for team in self.get_fantasy_teams():
            if team["manager"] == self.my_team_name:
                return team["team_key"]
        return None

    def get_roster_percentages(
        self, players_df: pd.DataFrame, chunk_size: int = 25
    ) -> Optional[pd.DataFrame]:
        """
        Sleeper's public API exposes no roster/ownership-percentage data.

        Returns:
            None, always.
        """
        return None

    def get_fantasy_teams(self) -> List[Dict]:
        """
        Get list of all teams in the league.

        Returns:
            List of team dictionaries with keys: team_key, name, manager.
            team_key is the Sleeper roster_id (as a string), which the
            other methods on this client use to identify a team.
        """
        users = {user["user_id"]: user for user in fetch_users(self.league_id)}
        rosters = fetch_rosters(self.league_id)

        teams = []
        for roster in rosters:
            user = users.get(roster.get("owner_id"), {})
            manager = user.get("display_name") or "Unknown"
            team_name = (user.get("metadata") or {}).get("team_name") or manager
            teams.append({
                "team_key": str(roster["roster_id"]),
                "name": team_name,
                "manager": manager,
            })
        return teams

    def get_all_players(self, injury_tries: int = 10) -> pd.DataFrame:
        """
        Get all fantasy-relevant players with position, team, and injury status.

        Args:
            injury_tries: accepted for signature parity with
                YahooFantasyClient.get_all_players; unused here since
                Sleeper's static player map already carries injury_status
                (no separate polling/retry needed).

        Returns:
            DataFrame with columns: player_id, name, position,
            editorial_team_abbr, status, eligible_positions, player_id_sr,
            yahoo_id. player_id_sr is populated from Sleeper's gsis_id
            when present, which is the same ID nflreadpy's rosters/stats/
            depth-charts feeds use -- so it can be joined directly against
            NflreadpyProvider output without a name-matching fallback.
        """
        raw = fetch_all_players()

        records = []
        for player_id, info in raw.items():
            if not isinstance(info, dict):
                continue
            position = info.get("position")
            if position not in _FANTASY_POSITIONS:
                continue
            name = info.get("full_name") or " ".join(
                part for part in (info.get("first_name"), info.get("last_name")) if part
            )
            records.append({
                "player_id": player_id,
                "name": name,
                "position": position,
                "editorial_team_abbr": info.get("team"),
                "status": info.get("injury_status") or info.get("status"),
                "eligible_positions": info.get("fantasy_positions") or [position],
                "player_id_sr": info.get("gsis_id"),
                "yahoo_id": info.get("yahoo_id"),
            })

        return pd.DataFrame(records, columns=[
            "player_id", "name", "position", "editorial_team_abbr",
            "status", "eligible_positions", "player_id_sr", "yahoo_id",
        ])

    def get_team_rosters(self, teams: List[Dict], week: int) -> pd.DataFrame:
        """
        Get rosters for all teams for a given week.

        Args:
            teams: List of team dictionaries from get_fantasy_teams().
            week: Week number to get rosters for.

        Returns:
            DataFrame with columns: player_id, selected_position,
            fantasy_team. Prefers that week's actual starters (from
            /matchups/{week}) so historical lineups are reflected
            accurately; falls back to the current live roster (from
            /rosters) when the week has no matchup data yet (e.g. the
            upcoming week, or before the season starts).
        """
        team_names = {team["team_key"]: team["name"] for team in teams}
        league = fetch_league(self.league_id)
        slot_order = _starting_slots(league["roster_positions"])

        current_rosters = fetch_rosters(self.league_id)
        reserve_by_roster = {
            str(roster["roster_id"]): set(roster.get("reserve") or [])
            for roster in current_rosters
        }

        matchups = fetch_matchups(self.league_id, week)
        if not matchups or not any(entry.get("starters") for entry in matchups):
            matchups = [
                {
                    "roster_id": roster["roster_id"],
                    "starters": roster.get("starters") or [],
                    "players": roster.get("players") or [],
                }
                for roster in current_rosters
            ]

        rows = []
        for entry in matchups:
            roster_id = str(entry["roster_id"])
            team_name = team_names.get(roster_id)
            if team_name is None:
                continue
            starters = entry.get("starters") or []
            players = entry.get("players") or []
            reserve = reserve_by_roster.get(roster_id, set())

            for slot_ind, player_id in enumerate(starters):
                if not player_id or player_id == "0":
                    continue
                position = slot_order[slot_ind] if slot_ind < len(slot_order) else "BN"
                rows.append({
                    "player_id": player_id,
                    "selected_position": position,
                    "fantasy_team": team_name,
                })

            for player_id in players:
                if player_id in starters:
                    continue
                position = "IR" if player_id in reserve else "BN"
                rows.append({
                    "player_id": player_id,
                    "selected_position": position,
                    "fantasy_team": team_name,
                })

        return pd.DataFrame(
            rows, columns=["player_id", "selected_position", "fantasy_team"]
        )

    def get_schedule(
        self,
        teams: List[Dict],
        current_week: int,
        playoff_start_week: int,
        end_week: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Get the fantasy league schedule and scores.

        Args:
            teams: List of team dictionaries from get_fantasy_teams().
            current_week: Current week number.
            playoff_start_week: Week when playoffs start.
            end_week: Last playable week of the season, if known. Caps the
                query range so requesting a schedule past the end of the
                season doesn't query nonexistent weeks.

        Returns:
            DataFrame with columns: week, team_1, team_2, score_1, score_2.
        """
        team_names = {team["team_key"]: team["name"] for team in teams}
        limit = max(playoff_start_week, current_week + 1)
        if end_week:
            limit = min(limit, end_week + 1)

        rows = []
        for week in range(1, limit):
            matchups = fetch_matchups(self.league_id, week)
            if not matchups:
                continue

            by_matchup: Dict[int, List[Dict]] = {}
            for entry in matchups:
                matchup_id = entry.get("matchup_id")
                if matchup_id is None:
                    continue
                by_matchup.setdefault(matchup_id, []).append(entry)

            for pair in by_matchup.values():
                if len(pair) != 2:
                    # Byes (odd team count) surface as a single-entry
                    # matchup_id; skip since there's no opponent to pair.
                    continue
                team_1, team_2 = pair
                name_1 = team_names.get(str(team_1["roster_id"]))
                name_2 = team_names.get(str(team_2["roster_id"]))
                if name_1 is None or name_2 is None:
                    continue
                rows.append({
                    "week": week,
                    "team_1": name_1,
                    "team_2": name_2,
                    "score_1": float(team_1.get("points") or 0.0),
                    "score_2": float(team_2.get("points") or 0.0),
                })

        schedule = pd.DataFrame(
            rows, columns=["week", "team_1", "team_2", "score_1", "score_2"]
        )
        schedule["score_1"] = schedule["score_1"].astype(float)
        schedule["score_2"] = schedule["score_2"].astype(float)
        return schedule
