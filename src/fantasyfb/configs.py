"""
Predefined league configurations for fantasy football platforms.

This module contains scoring settings and roster configurations for
various fantasy platforms like Scott Fish Bowl, DraftKings, Underdog, etc.
"""

import pandas as pd

# Scott Fish Bowl 13 configuration (commented out - historical)
# SFB13_CONFIG = {
#     'settings': {
#         'playoff_start_week': 12,
#         'num_playoff_teams': 6
#     },
#     'scoring': {
#         'Pass Yds': 0.04, 'Pass Comp': 0.1, 'Pass TD': 6.0, 'Pass 1D': 0.1, 'Pass 300+': 0.0,
#         'Int Thrown': 0.0, 'Rush Yds': 0.1, 'Rush Att': 0.25, 'Rush TD': 6.0, 'Rush 1D': 1.0, 'Rush 100+': 0.0,
#         'Rec Yds': 0.1, 'Rec': 1.0, 'Rec TD': 6.0, 'Rec 1D': 1.0, 'Rec 100+': 0.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
#         'TE Rec Bonus': 1.0, 'TE 1D Bonus': 1.0, '2-PT': 2.0, 'Fum Lost': 0.0, 'Fum Ret TD': 6.0,
#         'FG 0-19': 2.0, 'FG 20-29': 2.5, 'FG 30-39': 3.5, 'FG 40-49': 4.5, 'FG 50+': 5.5, 'PAT Made': 3.3,
#         'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
#         'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
#         'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
#     },
#     'roster_spots': pd.DataFrame({
#         'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
#         'count': [1, 2, 3, 1, 2, 1, 1, 11]
#     })
# }

# Scott Fish Bowl 14 configuration (commented out - historical)
# SFB14_CONFIG = {
#     'scoring': {
#         'Pass Yds': 0.02, 'Pass Comp': 0.0, 'Pass TD': 6.0, 'Pass 1D': 0.0, 'Pass 300+': 0.0,
#         'Int Thrown': 0.0, 'Rush Yds': 0.1, 'Rush Att': 0.25, 'Rush TD': 6.0, 'Rush 1D': 0.5, 'Rush 100+': 0.0,
#         'Rec Yds': 0.1, 'Rec': 0.75, 'Rec TD': 6.0, 'Rec 1D': 0.5, 'Rec 100+': 0.0, 'Ret Yds': 0.2, 'Ret TD': 10.0,
#         'TE Rec Bonus': 0.75, 'TE 1D Bonus': 1.0, '2-PT': 2.0, 'Fum Lost': 0.0, 'Fum Ret TD': 6.0,
#         'FG 0-19': 2.0, 'FG 20-29': 2.5, 'FG 30-39': 3.5, 'FG 40-49': 4.5, 'FG 50+': 5.5, 'PAT Made': 3.3,
#         'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
#         'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
#         'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
#     },
#     'roster_spots': pd.DataFrame({
#         'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
#         'count': [1, 1, 1, 1, 5, 1, 1, 11]
#     })
# }

# Scott Fish Bowl 15 configuration (historical)
# SFB_CONFIG = {
#     'scoring': {
#         'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 6.0, 'Pass 1D': 0.0, 'Pass 300+': 0.0,
#         'Int Thrown': 0.0, 'Rush Yds': 0.1, 'Rush Att': 0.5, 'Rush TD': 6.0, 'Rush 1D': 1.0, 'Rush 100+': 0.0,
#         'Rec Yds': 0.1, 'Rec': 2.5, 'Rec TD': 6.0, 'Rec 1D': 1.0, 'Rec 100+': 0.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
#         'TE Rec Bonus': 1.0, 'TE 1D Bonus': 1.0, '2-PT': 2.0, 'Fum Lost': 0.0, 'Fum Ret TD': 6.0,
#         'FG 0-19': 0.0, 'FG 20-29': 0.0, 'FG 30-39': 0.0, 'FG 40-49': 0.0, 'FG 50+': 0.0, 'PAT Made': 0.0,
#         'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
#         'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
#         'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
#     },
#     'roster_spots': pd.DataFrame({
#         'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
#         'count': [0, 0, 0, 0, 9, 2, 0, 11]
#     })
# }

# Scott Fish Bowl 16 configuration (current), pulled from Sleeper league
# 1367870433398915072 on 2026-07-05 via sleeper_client.get_league_config().
# Note: Sleeper's per-play "long play" bonuses (40+ yard completions/rushes,
# 20-29/30-39/40+ yard receptions, all worth +10 each) are NOT modeled here --
# they need play-by-play data, not the per-game box-score stats FantasyScorer
# works from. See sleeper_client.UNSUPPORTED_SCORING_KEYS.
SFB_CONFIG = {
    'scoring': {
        'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 6.0, 'Pass 1D': 0.0, 'Pass 300+': 10.0, 'Pass 400+': 20.0,
        'Int Thrown': 0.0, 'Rush Yds': 0.1, 'Rush Att': 0.0, 'Rush TD': 6.0, 'Rush 1D': 0.5, 'Rush 100+': 0.0, 'Rush 200+': 0.0,
        'Rec Yds': 0.1, 'Rec': 0.5, 'Rec TD': 6.0, 'Rec 1D': 0.5, 'Rec 100+': 0.0, 'Rec 200+': 0.0,
        'Rush+Rec 100+': 10.0, 'Rush+Rec 200+': 20.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
        'TE Rec Bonus': 1.0, 'TE 1D Bonus': 1.0, '2-PT': 2.0, 'Fum Lost': 0.0, 'Fum Ret TD': 6.0,
        'FG 0-19': 0.0, 'FG 20-29': 0.0, 'FG 30-39': 0.0, 'FG 40-49': 0.0, 'FG 50+': 0.0, 'PAT Made': 0.0,
        'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
        'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
        'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
    },
    'roster_spots': pd.DataFrame({
        'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
        'count': [0, 0, 0, 0, 8, 2, 0, 10]
    })
}


def get_sfb_config_from_sleeper(league_id: str):
    """
    Fetch the current SFB scoring/roster config directly from Sleeper.

    Prefer this over the static SFB_CONFIG snapshot above when you have a
    concrete league ID (e.g. next year's SFB draft) -- it reflects
    whatever the commissioner actually configured instead of a
    point-in-time transcription.

    Args:
        league_id: numeric Sleeper league ID (from the league URL).

    Returns:
        Dict containing 'scoring' and 'roster_spots', same shape as SFB_CONFIG.
    """
    from .data.sleeper_client import get_league_config as _fetch

    return _fetch(league_id)

# DraftKings Best Ball configuration
DRAFTKINGS_CONFIG = {
    'settings': {
        'playoff_start_week': 14,
        'num_playoff_teams': 2
    },
    'scoring': {
        'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 4.0, 'Pass 1D': 0.0, 'Pass 300+': 3.0,
        'Int Thrown': -1.0, 'Rush Yds': 0.1, 'Rush Att': 0.0, 'Rush TD': 6.0, 'Rush 1D': 0.0, 'Rush 100+': 3.0,
        'Rec Yds': 0.1, 'Rec': 1.0, 'Rec TD': 6.0, 'Rec 1D': 0.0, 'Rec 100+': 3.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
        'TE Rec Bonus': 0.0, 'TE 1D Bonus': 0.0, '2-PT': 2.0, 'Fum Lost': -1.0, 'Fum Ret TD': 6.0,
        'FG 0-19': 0.0, 'FG 20-29': 0.0, 'FG 30-39': 0.0, 'FG 40-49': 0.0, 'FG 50+': 0.0, 'PAT Made': 0.0,
        'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
        'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
        'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
    },
    'roster_spots': pd.DataFrame({
        'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
        'count': [1, 2, 3, 1, 1, 0, 0, 12]
    })
}

# Underdog Best Ball configuration
UNDERDOG_CONFIG = {
    'settings': {
        'playoff_start_week': 14,
        'num_playoff_teams': 2
    },
    'scoring': {
        'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 4.0, 'Pass 1D': 0.0, 'Pass 300+': 0.0,
        'Int Thrown': -1.0, 'Rush Yds': 0.1, 'Rush Att': 0.0, 'Rush TD': 6.0, 'Rush 1D': 0.0, 'Rush 100+': 0.0,
        'Rec Yds': 0.1, 'Rec': 0.5, 'Rec TD': 6.0, 'Rec 1D': 0.0, 'Rec 100+': 0.0, 'Ret Yds': 0.0, 'Ret TD': 0.0,
        'TE Rec Bonus': 0.0, 'TE 1D Bonus': 0.0, '2-PT': 2.0, 'Fum Lost': -2.0, 'Fum Ret TD': 0.0,
        'FG 0-19': 0.0, 'FG 20-29': 0.0, 'FG 30-39': 0.0, 'FG 40-49': 0.0, 'FG 50+': 0.0, 'PAT Made': 0.0,
        'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
        'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
        'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
    },
    'roster_spots': pd.DataFrame({
        'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
        'count': [1, 2, 3, 1, 1, 0, 0, 10]
    })
}


# Shared base for the three generic (no Yahoo/Sleeper) mock-draft scoring
# presets -- standard 4pt passing TD / 6pt rushing+receiving TD, no
# yardage-bonus tiers, standard kicker/defense scoring. Only 'Rec' differs
# between the three (0 / 0.5 / 1 point per reception).
#
# Note: FantasyScorer only ever reads the 'FG 0-19' key for made field
# goals -- it doesn't have per-distance box-score stats to bucket kicks by
# range (same limitation noted on SFB_CONFIG above) -- so the other 'FG
# *-*' keys below are unused; kept populated for schema completeness.
_GENERIC_SCORING_BASE = {
    'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 4.0, 'Pass 1D': 0.0, 'Pass 300+': 0.0, 'Pass 400+': 0.0,
    'Int Thrown': -1.0, 'Rush Yds': 0.1, 'Rush Att': 0.0, 'Rush TD': 6.0, 'Rush 1D': 0.0, 'Rush 100+': 0.0, 'Rush 200+': 0.0,
    'Rec Yds': 0.1, 'Rec TD': 6.0, 'Rec 1D': 0.0, 'Rec 100+': 0.0, 'Rec 200+': 0.0,
    'Rush+Rec 100+': 0.0, 'Rush+Rec 200+': 0.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
    'TE Rec Bonus': 0.0, 'TE 1D Bonus': 0.0, '2-PT': 2.0, 'Fum Lost': -2.0, 'Fum Ret TD': 6.0,
    'FG 0-19': 3.0, 'FG 20-29': 3.0, 'FG 30-39': 3.0, 'FG 40-49': 4.0, 'FG 50+': 5.0, 'PAT Made': 1.0,
    'Sack': 1.0, 'Int': 2.0, 'Fum Rec': 2.0, 'TD': 6.0, 'Safe': 2.0, 'Blk Kick': 2.0,
    'Pts Allow 0': 10.0, 'Pts Allow 1-6': 7.0, 'Pts Allow 7-13': 4.0, 'Pts Allow 14-20': 1.0,
    'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': -1.0, 'Pts Allow 35+': -4.0, 'XPR': 0.0,
}

# Fixed roster shape for all three generic-draft presets (see issue #47):
# 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF, 7 BN. No custom roster editor
# in v1.
_GENERIC_ROSTER_SPOTS = pd.DataFrame({
    'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'K', 'DEF', 'BN'],
    'count': [1, 2, 2, 1, 1, 1, 1, 7]
})

# Standard (non-PPR) scoring for a generic mock draft.
STANDARD_CONFIG = {
    'scoring': {**_GENERIC_SCORING_BASE, 'Rec': 0.0},
    'roster_spots': _GENERIC_ROSTER_SPOTS.copy()
}

# Half-PPR scoring for a generic mock draft.
HALF_PPR_CONFIG = {
    'scoring': {**_GENERIC_SCORING_BASE, 'Rec': 0.5},
    'roster_spots': _GENERIC_ROSTER_SPOTS.copy()
}

# Full-PPR scoring for a generic mock draft.
PPR_CONFIG = {
    'scoring': {**_GENERIC_SCORING_BASE, 'Rec': 1.0},
    'roster_spots': _GENERIC_ROSTER_SPOTS.copy()
}


def get_league_config(platform: str):
    """
    Get predefined configuration for a specific platform.

    Args:
        platform: Platform name ('sfb', 'draftkings'/'dk', 'underdog',
            'standard', 'half_ppr'/'half-ppr', 'ppr')

    Returns:
        Dict containing scoring and roster configuration, or None if not found
    """
    platform_lower = platform.lower()

    if platform_lower == 'sfb':
        return SFB_CONFIG
    elif platform_lower in ['dk', 'draftkings']:
        return DRAFTKINGS_CONFIG
    elif platform_lower == 'underdog':
        return UNDERDOG_CONFIG
    elif platform_lower in ['standard', 'std']:
        return STANDARD_CONFIG
    elif platform_lower in ['half_ppr', 'half-ppr', 'halfppr']:
        return HALF_PPR_CONFIG
    elif platform_lower == 'ppr':
        return PPR_CONFIG
    else:
        return None


def apply_default_scoring_categories(scoring: dict):
    """
    Add missing scoring categories with default values of 0.0.
    
    Args:
        scoring: Dictionary of scoring settings
        
    Returns:
        Dictionary with all expected scoring categories
    """
    default_categories = [
        'Pass Comp', 'Pass 1D', 'Rush Att', 'Rush 1D', 'Rec 1D',
        'TE Rec Bonus', 'TE 1D Bonus', 'Pass 300+', 'Pass 400+',
        'Rush 100+', 'Rush 200+', 'Rec 100+', 'Rec 200+',
        'Rush+Rec 100+', 'Rush+Rec 200+',
    ]
    
    for category in default_categories:
        if category not in scoring:
            scoring[category] = 0.0
    
    # Set default kicker scoring if missing
    if "FG 0-19" not in scoring:
        scoring["FG 0-19"] = 3
    
    # Set default reception scoring if missing
    if "Rec" not in scoring:
        scoring["Rec"] = 0
    
    # Set default return yardage scoring if missing
    if "Ret Yds" not in scoring:
        scoring["Ret Yds"] = 0
    
    return scoring
