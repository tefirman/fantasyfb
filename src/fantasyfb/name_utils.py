"""
Shared player-name normalization for cross-source joins.

Different data sources spell the same player differently -- FantasyPros-style
ADP exports and Yahoo both append generational suffixes ("James Cook III",
"KC Concepcion Jr.") that nflreadpy's `name` column generally omits ("James
Cook", "KC Concepcion"). Left alone, these break exact-string joins, silently
dropping data for a couple dozen players a season including early-round
starters and rookies.
"""

import re

import pandas as pd

_NAME_SUFFIX_RE = re.compile(
    r"\s+(?:jr|sr|ii|iii|iv|v)\.?$", flags=re.IGNORECASE
)


def normalize_name_key(names: pd.Series) -> pd.Series:
    """Build a join-key copy of a name column: trailing generational
    suffix stripped, whitespace collapsed, lowercased. Never overwrites
    the display name -- callers merge on this and keep `name` as-is."""
    key = names.astype(str).str.strip()
    key = key.str.replace(_NAME_SUFFIX_RE, "", regex=True)
    key = key.str.replace(r"\s+", " ", regex=True).str.strip().str.lower()
    return key
