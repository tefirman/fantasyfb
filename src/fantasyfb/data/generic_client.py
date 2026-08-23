"""
Generic (no Yahoo/Sleeper) mock-draft client.

Backs a fully synthetic mock draft: no real league, no OAuth, no league
ID -- just an NFL player pool (from `NflreadpyProvider`) and a scoring
preset (standard / half-PPR / PPR, see `fantasyfb.configs`), used to
sanity-check VORP rankings against a scoring system with a familiar
baseline. See issue #47.

Since there's no real league to query, several methods synthesize what a
real platform client would otherwise fetch:
- Teams are named "Team 1".."Team N" (or `my_team_name`, for whichever
  slot represents the user's own team).
- Rosters start empty -- a from-scratch mock draft has no existing
  picks/keepers.
- The schedule is a synthetic round-robin across the regular season
  (playoff brackets are simulated separately by `SeasonSimulator`, so
  only regular-season weeks need real matchups).
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional

import pandas as pd

from .nflreadpy_provider import NflreadpyProvider
from .platform_client import FantasyPlatformClient

_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

# Position codes accepted in a custom roster_spots DataFrame: the base
# positions plus Yahoo-style flex codes (see FLEX_ELIGIBILITY in
# drafts/tools.py) plus bench/IR. Kept independent of drafts/tools to
# avoid this module importing the drafts package.
_VALID_ROSTER_POSITIONS = {
    "QB", "RB", "WR", "TE", "K", "DEF",
    "W/T", "W/R/T", "Q/W/R/T",
    "BN", "IR",
}


def _validate_roster_spots(roster_spots: pd.DataFrame) -> None:
    if not isinstance(roster_spots, pd.DataFrame) or list(roster_spots.columns[:2]) != ["position", "count"]:
        raise ValueError(
            "roster_spots must be a DataFrame with 'position' and 'count' columns"
        )
    unknown = sorted(set(roster_spots["position"]) - _VALID_ROSTER_POSITIONS)
    if unknown:
        raise ValueError(
            f"Unknown roster_spots position code(s): {unknown}. "
            f"Valid codes are: {sorted(_VALID_ROSTER_POSITIONS)}"
        )

# Fallback defaults when Sleeper's public /state/nfl endpoint (used for
# get_current_week) is unreachable -- a mock draft has no real league to
# ask instead, so "week 1" is as good a guess as any offline.
_DEFAULT_CURRENT_WEEK = 1

# No real league to pull playoff settings from; matches the defaults
# SleeperClient falls back to when a league hasn't configured them.
_DEFAULT_PLAYOFF_START_WEEK = 15
_DEFAULT_NUM_PLAYOFF_TEAMS = 6
_DEFAULT_END_WEEK = _DEFAULT_PLAYOFF_START_WEEK + 2


def _round_robin_pairings(team_names: List[str]) -> List[List[tuple]]:
    """Standard circle-method round robin.

    Returns a list of rounds, each a list of (team_1, team_2) pairs. Odd
    team counts get a bye (one team sits out) each round.
    """
    teams = list(team_names)
    if len(teams) % 2 == 1:
        teams.append(None)  # bye placeholder
    n = len(teams)
    if n < 2:
        return []

    fixed, rotating = teams[0], teams[1:]
    rounds = []
    for _ in range(n - 1):
        round_teams = [fixed] + rotating
        pairs = [
            (round_teams[i], round_teams[n - 1 - i])
            for i in range(n // 2)
            if round_teams[i] is not None and round_teams[n - 1 - i] is not None
        ]
        rounds.append(pairs)
        rotating = [rotating[-1]] + rotating[:-1]
    return rounds


class GenericClient(FantasyPlatformClient):
    """
    Client for a fully synthetic mock draft with no real fantasy league.

    Still pulls real NFL player data from `NflreadpyProvider`, but every
    league-shaped concept (teams, rosters, schedule) is synthesized.
    """

    def __init__(
        self,
        num_teams: int = 12,
        scoring: str = "ppr",
        my_team_name: Optional[str] = None,
        season: Optional[int] = None,
        nfl_provider: Optional[NflreadpyProvider] = None,
        roster_spots: Optional[pd.DataFrame] = None,
    ):
        """
        Args:
            num_teams: number of teams in the mock draft, defaults to 12.
            scoring: which generic scoring preset to use -- "standard",
                "half_ppr", or "ppr" (see fantasyfb.configs). Defaults to "ppr".
            my_team_name: display name for the user's own team. If given,
                one of the synthesized teams is named this (so
                get_my_team_key() can resolve it); otherwise there's no
                "my team" concept, same as SleeperClient with no
                my_team_name.
            season: NFL season to pull the player pool for, defaults to
                the most recently completed season (matching League's
                own auto-detect).
            nfl_provider: NflreadpyProvider instance to source players
                from. Defaults to a new instance; pass League's own
                instance to share its parquet cache.
            roster_spots: optional custom roster shape, as a DataFrame
                with 'position'/'count' columns -- same schema as
                `League.roster_spots` (base positions QB/RB/WR/TE/K/DEF,
                flex codes W/T, W/R/T, Q/W/R/T, plus BN/IR). Lets callers
                mock-draft against leagues with an extra flex, superflex
                (Q/W/R/T), different bench sizes, etc. Defaults to None,
                which falls back to the fixed shape from the chosen
                `scoring` preset (see issue #59). Raises ValueError on an
                unrecognized position code.
        """
        self.num_teams = num_teams
        self.scoring = scoring
        self.my_team_name = my_team_name
        self.season = season or (
            datetime.datetime.now().year - int(datetime.datetime.now().month < 6)
        )
        self.nfl_provider = nfl_provider if nfl_provider is not None else NflreadpyProvider()
        if roster_spots is not None:
            _validate_roster_spots(roster_spots)
        self.roster_spots = roster_spots

    def get_current_week(self) -> int:
        """
        Get the current NFL week.

        Returns:
            Sleeper's public (unauthenticated, no league ID needed)
            '/state/nfl' display_week, same source SleeperClient uses --
            there's no real league to ask, but this is still the actual
            current NFL week. Falls back to 1 if that endpoint is
            unreachable (e.g. no network for an offline mock draft).
        """
        from .sleeper_client import fetch_nfl_state
        import requests

        try:
            state = fetch_nfl_state()
        except requests.exceptions.RequestException:
            return _DEFAULT_CURRENT_WEEK
        return int(state.get("display_week") or state.get("week") or _DEFAULT_CURRENT_WEEK)

    def get_league_config(self) -> Dict:
        """
        Get the selected generic scoring preset plus synthetic settings.

        Returns:
            Dict with 'settings' (playoff_start_week, num_playoff_teams,
            end_week), 'scoring', and 'roster_spots' keys. 'roster_spots'
            is the custom shape passed to __init__, if given, otherwise
            the fixed default for the chosen scoring preset.
        """
        from ..configs import get_league_config as _get_config

        config = dict(_get_config(self.scoring) or _get_config("ppr"))
        if self.roster_spots is not None:
            config["roster_spots"] = self.roster_spots
        config["settings"] = {
            "playoff_start_week": _DEFAULT_PLAYOFF_START_WEEK,
            "num_playoff_teams": _DEFAULT_NUM_PLAYOFF_TEAMS,
            "end_week": _DEFAULT_END_WEEK,
        }
        return config

    def get_fantasy_teams(self) -> List[Dict]:
        """
        Get the synthesized list of teams.

        Returns:
            List of team dicts with keys: team_key, name, manager.
            `my_team_name`, if given, replaces the first team's name/manager
            so get_my_team_key() can resolve it.
        """
        teams = [
            {"team_key": str(i), "name": f"Team {i}", "manager": f"Team {i}"}
            for i in range(1, self.num_teams + 1)
        ]
        if self.my_team_name and teams:
            teams[0]["name"] = self.my_team_name
            teams[0]["manager"] = self.my_team_name
        return teams

    def get_all_players(self, injury_tries: int = 10) -> pd.DataFrame:
        """
        Get the fantasy-relevant player pool from NflreadpyProvider directly.

        Args:
            injury_tries: accepted for signature parity with the other
                clients; unused, since there's no injury-status polling here.

        Returns:
            DataFrame with columns: player_id, name, position,
            editorial_team_abbr, status, eligible_positions, player_id_sr,
            yahoo_id. player_id (and player_id_sr) is nflreadpy's gsis_id --
            there's no separate platform ID to reconcile against, since
            there's no real platform. Includes one synthetic row per NFL
            team for the DEF roster slot (nflreadpy's roster feed only
            lists individual players, not team defenses).
        """
        # Two-year window (rather than just self.season) so a mock draft
        # run before nflverse has published the upcoming season's roster
        # parquet (e.g. preseason) still gets a full player pool from the
        # prior season instead of an empty one.
        rosters = self.nfl_provider.get_rosters(self.season - 1, self.season)
        rosters = rosters.sort_values("season").drop_duplicates(
            subset="player_id_sr", keep="last"
        )
        offense = rosters[rosters["position"].isin(_FANTASY_POSITIONS)].copy()
        offense["player_id"] = offense["player_id_sr"]
        offense["editorial_team_abbr"] = offense["current_team"]
        offense["status"] = None
        offense["eligible_positions"] = offense["position"].apply(lambda p: [p])
        offense["yahoo_id"] = offense.get("yahoo_id")

        team_abbrevs = sorted(self.nfl_provider.team_aliases()["real_abbrev"].unique())
        defense = pd.DataFrame({
            "player_id": team_abbrevs,
            "name": team_abbrevs,
            "position": "DEF",
            "editorial_team_abbr": team_abbrevs,
            "status": None,
            "eligible_positions": [["DEF"]] * len(team_abbrevs),
            "player_id_sr": team_abbrevs,
            "yahoo_id": None,
        })

        cols = [
            "player_id", "name", "position", "editorial_team_abbr",
            "status", "eligible_positions", "player_id_sr", "yahoo_id",
        ]
        return pd.concat([offense[cols], defense[cols]], ignore_index=True)

    def get_team_rosters(self, teams: List[Dict], week: int) -> pd.DataFrame:
        """
        A from-scratch mock draft has no pre-existing rosters.

        Returns:
            Empty DataFrame with columns: player_id, selected_position,
            fantasy_team.
        """
        return pd.DataFrame(columns=["player_id", "selected_position", "fantasy_team"])

    def get_schedule(
        self,
        teams: List[Dict],
        current_week: int,
        playoff_start_week: int,
        end_week: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Get a synthetic round-robin regular-season schedule.

        SeasonSimulator simulates playoff brackets separately from the
        schedule, so only regular-season weeks (1..playoff_start_week - 1)
        need real matchups here. Every score starts at 0.0 -- a mock draft
        has no games played yet.

        Returns:
            DataFrame with columns: week, team_1, team_2, score_1, score_2.
        """
        team_names = [team["name"] for team in teams]
        rounds = _round_robin_pairings(team_names)
        rows = []
        if rounds:
            for week in range(1, playoff_start_week):
                for team_1, team_2 in rounds[(week - 1) % len(rounds)]:
                    rows.append({
                        "week": week, "team_1": team_1, "team_2": team_2,
                        "score_1": 0.0, "score_2": 0.0,
                    })
        return pd.DataFrame(
            rows, columns=["week", "team_1", "team_2", "score_1", "score_2"]
        )

    def get_roster_percentages(
        self, players_df: pd.DataFrame, chunk_size: int = 25
    ) -> Optional[pd.DataFrame]:
        """
        A mock draft has no real ownership/roster-percentage data.

        Returns:
            None, always.
        """
        return None

    def get_my_team_key(self) -> Optional[str]:
        """
        Get the team_key of the team identified by my_team_name.

        Returns:
            The matched team's team_key, or None if my_team_name wasn't set.
        """
        if not self.my_team_name:
            return None
        for team in self.get_fantasy_teams():
            if team["name"] == self.my_team_name:
                return team["team_key"]
        return None
