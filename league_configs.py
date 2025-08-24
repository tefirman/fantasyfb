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

# Scott Fish Bowl 15 configuration (current)
SFB_CONFIG = {
    'scoring': {
        'Pass Yds': 0.04, 'Pass Comp': 0.0, 'Pass TD': 6.0, 'Pass 1D': 0.0, 'Pass 300+': 0.0,
        'Int Thrown': 0.0, 'Rush Yds': 0.1, 'Rush Att': 0.5, 'Rush TD': 6.0, 'Rush 1D': 1.0, 'Rush 100+': 0.0,
        'Rec Yds': 0.1, 'Rec': 2.5, 'Rec TD': 6.0, 'Rec 1D': 1.0, 'Rec 100+': 0.0, 'Ret Yds': 0.0, 'Ret TD': 6.0,
        'TE Rec Bonus': 1.0, 'TE 1D Bonus': 1.0, '2-PT': 2.0, 'Fum Lost': 0.0, 'Fum Ret TD': 6.0,
        'FG 0-19': 0.0, 'FG 20-29': 0.0, 'FG 30-39': 0.0, 'FG 40-49': 0.0, 'FG 50+': 0.0, 'PAT Made': 0.0,
        'Sack': 0.0, 'Int': 0.0, 'Fum Rec': 0.0, 'TD': 0.0, 'Safe': 0.0, 'Blk Kick': 0.0,
        'Pts Allow 0': 0.0, 'Pts Allow 1-6': 0.0, 'Pts Allow 7-13': 0.0, 'Pts Allow 14-20': 0.0,
        'Pts Allow 21-27': 0.0, 'Pts Allow 28-34': 0.0, 'Pts Allow 35+': 0.0, 'XPR': 0.0
    },
    'roster_spots': pd.DataFrame({
        'position': ['QB', 'RB', 'WR', 'TE', 'W/R/T', 'Q/W/R/T', 'K', 'BN'],
        'count': [0, 0, 0, 0, 9, 2, 0, 11]
    })
}

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


def get_league_config(platform: str):
    """
    Get predefined configuration for a specific platform.
    
    Args:
        platform: Platform name ('sfb', 'draftkings'/'dk', 'underdog')
        
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
        'TE Rec Bonus', 'TE 1D Bonus', 'Pass 300+', 'Rush 100+', 'Rec 100+'
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
