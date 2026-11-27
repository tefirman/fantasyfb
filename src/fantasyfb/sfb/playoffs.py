"""Read the SFB playoff field from the round pages on scottfishbowl.com.

Once the regular season ends, who qualified is a fact: ``playoffs-SFB.php?week=N``
lists the teams that start round N with the season average each one carries into
it, and a link to every Sleeper roster. That list replaces the regular-season
simulation, so the odds are only about the rounds still to play.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

ROUND_URL = "https://scottfishbowl.com/playoffs-SFB.php?week={round}"
NUM_ROUNDS = 6

_SLEEPER = re.compile(r"sleeper\.com/roster/(\d+)/(\d+)")
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAGS = re.compile(r"<script.*?</script>|<[^>]+>", re.S)
_NEEDED = re.compile(r"score needed to advance:\s*([\d.]+)")
_UPDATED = re.compile(r"Last Updated:\s*([^<]*?)\s*<", re.S)
_HEADLINE = re.compile(r"(\d[\d,]*)\s+Teams\s*-\s*Top\s+(\d[\d,]*)\s+advance")


@dataclass
class RoundField:
    """The teams that start one round.

    ``teams`` has ``league_id``, ``roster_id`` and ``avg`` for each Sleeper team (the
    MyFantasyLeague teams in the round are counted in ``size`` but not simulated).
    ``advance`` is how many teams of ``size`` move on (0 for the finals), ``needed``
    the score that would advance a team right now, and ``updated`` the SFB's own timestamp.
    """
    round: int
    size: int
    advance: int
    needed: Optional[float]
    updated: str
    teams: pd.DataFrame


def parse_round(page: str, round: int) -> Optional[RoundField]:
    """The field in a round page, or ``None`` when the round has no teams yet."""
    if "<tbody>" not in page:
        return None
    rows = page.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("<tr")[1:]
    teams, size = [], 0
    for row in rows:
        cells = [re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", c))).strip() for c in _CELL.findall(row)]
        if len(cells) < 5:
            continue
        size += 1
        link = _SLEEPER.search(row)
        if link:
            teams.append((link.group(1), int(link.group(2)), float(cells[3])))
    if not size:
        return None
    needed, updated, headline = _NEEDED.search(page), _UPDATED.search(page), _HEADLINE.search(page)
    advance = int(headline.group(2).replace(",", "")) if headline else 0
    return RoundField(
        round=round, size=size, advance=advance, needed=float(needed.group(1)) if needed else None,
        updated=updated.group(1).strip() if updated else "",
        teams=pd.DataFrame(teams, columns=["league_id", "roster_id", "avg"]))


def fetch_field(get: Optional[Callable[[str], str]] = None) -> RoundField:
    """The field for the round being played: the latest round whose page lists teams.

    Args:
        get: ``get(url)`` returning page text; defaults to ``requests`` with a timeout.
    """
    if get is None:
        import requests

        def get(url):
            response = requests.get(url, timeout=120, headers={"User-Agent": "fantasyfb-sfb-odds"})
            response.raise_for_status()
            return response.text
    current = None
    for round in range(1, NUM_ROUNDS + 1):
        found = parse_round(get(ROUND_URL.format(round=round)), round)
        if found is None:
            break
        current = found
    if current is None:
        raise ValueError("no SFB round page lists any teams")
    return current
