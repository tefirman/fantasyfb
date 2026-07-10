"""
Sleeper Fantasy API client.

Sleeper's league-settings API is public and read-only -- no OAuth, no app
registration, just a league ID off the league's URL
(sleeper.com/leagues/<league_id>/...). This module only covers pulling
scoring/roster settings (e.g. for Scott Fish Bowl, which runs on Sleeper);
it is intentionally not a full replacement for YahooFantasyClient (no
roster/matchup/standings pulls) -- that's a separate follow-up.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import requests

BASE_URL = "https://api.sleeper.app/v1"

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
        of the static configs in fantasyfb.configs (e.g. SFB_CONFIG) so
        it can be used interchangeably wherever a league config is expected.
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
