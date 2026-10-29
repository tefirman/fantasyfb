"""Read the SFB league list from a saved copy of the leaderboard page.

The leaderboard (https://scottfishbowl.com) links every team to its roster, and
the links hold the league IDs, so one saved copy of the page gives the whole
field without asking the SFB server again.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd

_SLEEPER = re.compile(r"sleeper\.com/roster/(\d+)/(\d+)")
_MFL = re.compile(r"myfantasyleague\.com/\d+/fantasy_box_score\?L=(\d+)&amp;F=(\d+)")
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAGS = re.compile(r"<script.*?</script>|<[^>]+>", re.S)


def parse_leaderboard(page: str) -> pd.DataFrame:
    """One row per team on the leaderboard page.

    Returns:
        DataFrame with ``platform`` ("sleeper" or "mfl"), ``league_id``,
        ``roster_id`` and the leaderboard's ``rank``, ``w``, ``l``, ``pf``,
        ``avg`` and ``pa``. Rows without a Sleeper or MyFantasyLeague link are skipped.
    """
    if "<tbody>" not in page:
        raise ValueError("No leaderboard table found in the page")
    rows = []
    for row in page.split("<tbody>", 1)[1].split("<tr>")[1:]:
        sleeper, mfl = _SLEEPER.search(row), _MFL.search(row)
        if sleeper:
            platform, (league_id, roster_id) = "sleeper", sleeper.groups()
        elif mfl:
            platform, (league_id, roster_id) = "mfl", mfl.groups()
        else:
            continue
        cells = [re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", cell))).strip()
                 for cell in _CELL.findall(row)]
        rows.append(dict(platform=platform, league_id=league_id, roster_id=int(roster_id),
                         rank=cells[0], w=cells[-5], l=cells[-4], pf=cells[-3], avg=cells[-2], pa=cells[-1]))
    return pd.DataFrame(rows)


def league_list(teams: pd.DataFrame) -> pd.DataFrame:
    """One row per league (``platform``, ``league_id``, ``n_teams``) from ``parse_leaderboard`` output.

    ``n_teams`` counts the teams the leaderboard lists, which can fall short of
    the league's real size when a team's Sleeper handle doesn't match.
    """
    return (teams.groupby(["platform", "league_id"]).size().rename("n_teams")
                 .reset_index().sort_values(["platform", "league_id"], ignore_index=True))


def read_league_ids(path, platform: str = "sleeper") -> list:
    """League IDs of one platform from a CSV written by ``league_list``."""
    leagues = pd.read_csv(Path(path), dtype={"league_id": str})
    return leagues.loc[leagues.platform == platform, "league_id"].tolist()
