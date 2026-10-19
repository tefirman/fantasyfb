"""
Sleeper league lookups for the web app's league picker.

Sleeper's read API is public, so this only needs a league ID: no sign-in and
no tokens to store.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from fantasyfb.data import sleeper_client

# Sleeper league IDs are long numeric snowflakes (18-19 digits today).
_ID_RE = re.compile(r"^\d{6,25}$")
# e.g. https://sleeper.com/leagues/1367870433398915072/matchup
_URL_RE = re.compile(r"sleeper\.(?:com|app)/leagues/(\d{6,25})")


def parse_league_id(text: str) -> Optional[str]:
    """
    Pull a Sleeper league ID out of a bare ID or a pasted league URL.

    Returns:
        The numeric ID as a string, or None if ``text`` contains neither.
    """
    text = (text or "").strip()
    if _ID_RE.match(text):
        return text
    match = _URL_RE.search(text)
    return match.group(1) if match else None


class LeagueNotFound(LookupError):
    """Sleeper has no league with that ID."""


def league_summary(league_id: str) -> Dict:
    """
    League name, season, status, and team list for the picker.

    Raises:
        LeagueNotFound: Sleeper answered, but has no such league
        requests.RequestException: Sleeper couldn't be reached
    """
    league = sleeper_client.fetch_league(league_id)
    # Sleeper answers 200 with a JSON ``null`` body for an unknown league.
    if not league:
        raise LeagueNotFound(league_id)
    client = sleeper_client.SleeperClient(league_id)
    teams = sorted(client.get_fantasy_teams(), key=lambda t: t["name"].lower())
    return {
        "league_id": league_id,
        "name": league.get("name") or "Sleeper league",
        "season": int(league.get("season") or 0),
        # pre_draft / drafting / in_season / complete
        "status": league.get("status") or "unknown",
        "teams": [{"name": t["name"], "manager": t["manager"]} for t in teams],
    }
