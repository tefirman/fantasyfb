"""Live NFL game state (how much of each game is left), from ESPN's scoreboard.

nflverse publishes box scores hours after the final whistle and has no game
clock, so the only way to tell how far along an in-progress game is comes from a
live feed. ESPN's public scoreboard endpoint is free and keyless, but it is
unofficial, so every failure here degrades to "no live state" rather than
raising: callers then fall back to the finished-or-not behavior.
"""

from __future__ import annotations

import time
import warnings
from typing import Dict, Optional

import requests

ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)

# ESPN team abbreviation -> nflreadpy code, for the two that differ.
_ESPN_TO_NFL_TEAM = {"LAR": "LA", "WSH": "WAS"}

REGULATION_MINUTES = 60.0
QUARTER_MINUTES = 15.0


def _clock_minutes(display_clock: str) -> float:
    """``"7:42"`` -> 7.7 minutes. Sub-minute clocks like ``"0:41.0"`` are fine."""
    minutes, _, seconds = str(display_clock).partition(":")
    return int(minutes or 0) + float(seconds or 0) / 60.0


def fraction_remaining(state: str, period: int, display_clock: str) -> float:
    """Fraction of regulation (60 min) still to be played, in [0, 1].

    ``state`` is ESPN's ``status.type.state``: ``pre``, ``in`` or ``post``.
    Overtime counts as 0 remaining, so a game in overtime is treated as having
    played out its projection window: the points scored so far are all we credit.
    """
    if state == "pre":
        return 1.0
    if state == "post":
        return 0.0
    if period > 4:
        return 0.0
    left = (4 - period) * QUARTER_MINUTES + _clock_minutes(display_clock)
    return min(max(left / REGULATION_MINUTES, 0.0), 1.0)


def parse_scoreboard(payload: dict) -> Dict[str, dict]:
    """Turn an ESPN scoreboard payload into ``{team: {state, remaining, game}}``.

    Teams use nflreadpy codes (``LA``, ``WAS``) so they join straight onto
    ``players.current_team``. Bye-week teams are absent.
    """
    out: Dict[str, dict] = {}
    for event in payload.get("events", []):
        status = event.get("status", {})
        state = status.get("type", {}).get("state")
        if state not in ("pre", "in", "post"):
            continue
        remaining = fraction_remaining(
            state, int(status.get("period", 0)), status.get("displayClock", "0:00")
        )
        for comp in event.get("competitions", [])[:1]:
            for competitor in comp.get("competitors", []):
                abbr = competitor.get("team", {}).get("abbreviation")
                if not abbr:
                    continue
                out[_ESPN_TO_NFL_TEAM.get(abbr, abbr)] = {
                    "state": state,
                    "remaining": remaining,
                    "game": event.get("shortName"),
                }
    return out


class EspnGameStateProvider:
    """Fetches per-team game progress from ESPN's scoreboard."""

    def __init__(
        self,
        url: str = ESPN_SCOREBOARD_URL,
        timeout: float = 15.0,
        attempts: int = 2,
        retry_wait: float = 2.0,
    ):
        self.url = url
        self.timeout = timeout
        self.attempts = attempts
        self.retry_wait = retry_wait

    def get_game_state(self, week: Optional[int] = None) -> Dict[str, dict]:
        """``{team: {state, remaining, game}}`` for the current scoreboard.

        The scoreboard defaults to the NFL's current week; ``week`` is passed
        through so a stale caller can't be handed a different week's games.
        Returns ``{}`` (with a warning) when ESPN is unreachable or the payload
        isn't what we expect.
        """
        params = {"week": week} if week is not None else None
        exc: Exception = RuntimeError("no attempt made")
        for attempt in range(self.attempts):
            try:
                resp = requests.get(self.url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                return parse_scoreboard(resp.json())
            except (requests.RequestException, ValueError, KeyError, TypeError) as err:
                exc = err
                if attempt + 1 < self.attempts:
                    time.sleep(self.retry_wait)
        warnings.warn(
            f"Could not fetch live game state from ESPN ({exc}); "
            "in-progress games will keep their full projections "
            "and lineups won't lock for games that have started.",
            stacklevel=2,
        )
        return {}
