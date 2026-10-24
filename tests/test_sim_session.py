"""SeasonSimSession must give the same standings as re-simulating everyone.

The session re-projects only the teams whose rosters changed and replays the
baseline's random draws. Here every scenario is also run the slow way
(project all teams from scratch, same draws) on a league replayed from a
recorded snapshot, and the two standings tables must be identical.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

PAYOUTS = [800, 300, 100]
pytestmark = pytest.mark.parametrize("replay_league", ["generic", "yahoo"], indirect=True)


def _my_team(league) -> str:
    return next(t["name"] for t in league.teams if t["team_key"] == league.my_team_key)


def _slow_standings(league, session) -> pd.DataFrame:
    """Everything recomputed from scratch, with the session's own draws."""
    session._normals.rewind()
    return league._simulate_season(
        league._season_projections(), True, list(PAYOUTS), normals=session._normals
    )[1]


def _assert_same(got: pd.DataFrame, want: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(
        got.reset_index(drop=True), want.reset_index(drop=True), check_exact=True
    )


def _swap(league, name_a: str, team_a, name_b: str, team_b) -> None:
    league.players.loc[league.players.name == name_a, "fantasy_team"] = team_a
    league.players.loc[league.players.name == name_b, "fantasy_team"] = team_b


def test_baseline_matches_season_sims_with_the_same_draws(replay_league):
    league = replay_league
    np.random.seed(7)
    session = league.season_sim_session(True, PAYOUTS)
    got = session.standings()
    np.random.seed(7)
    want = league._simulate_season(league._season_projections(), True, list(PAYOUTS))[1]
    _assert_same(got, want)


def test_unchanged_rosters_reproduce_the_baseline_exactly(replay_league):
    league = replay_league
    session = league.season_sim_session(True, PAYOUTS)
    base = session.standings()
    _assert_same(session.standings([_my_team(league)]), base)
    _assert_same(session.standings(), base)


def test_pickups_match_a_full_recompute(replay_league):
    league = replay_league
    me = _my_team(league)
    session = league.season_sim_session(True, PAYOUTS)
    base = session.standings()
    mine = league.players[(league.players.fantasy_team == me)
                          & ~league.players.name.str.contains("Average_")]
    free = league.players[league.players.fantasy_team.isnull()
                          & ~league.players.name.str.contains("Average_")]
    moved = 0
    for position in ["QB", "RB", "WR", "TE"]:
        drop = mine[mine.position == position].nsmallest(1, "WAR").name
        add = free[free.position == position].nlargest(1, "WAR").name
        if drop.empty or add.empty:
            continue
        drop, add = drop.iloc[0], add.iloc[0]
        _swap(league, drop, None, add, me)
        try:
            got = session.standings([me])
            want = _slow_standings(league, session)
        finally:
            _swap(league, drop, me, add, None)
        _assert_same(got, want)
        assert not got.equals(base)  # the move did change the outlook
        moved += 1
    assert moved >= 3


def test_drops_match_a_full_recompute(replay_league):
    league = replay_league
    me = _my_team(league)
    session = league.season_sim_session(True, PAYOUTS)
    session.standings()
    mine = league.players[(league.players.fantasy_team == me)
                          & ~league.players.name.str.contains("Average_")]
    for name in mine.nlargest(3, "WAR").name:
        league.players.loc[league.players.name == name, "fantasy_team"] = None
        try:
            got = session.standings([me])
            want = _slow_standings(league, session)
        finally:
            league.players.loc[league.players.name == name, "fantasy_team"] = me
        _assert_same(got, want)


def test_trades_match_a_full_recompute(replay_league):
    league = replay_league
    me = _my_team(league)
    session = league.season_sim_session(True, PAYOUTS)
    session.standings()
    real = league.players[~league.players.name.str.contains("Average_")
                          & ~league.players.position.isin(["K", "DEF"])]
    mine = real[real.fantasy_team == me].nlargest(2, "WAR")
    other_team = next(t["name"] for t in league.teams if t["name"] != me)
    theirs = real[real.fantasy_team == other_team].nlargest(2, "WAR")
    for give, get in zip(mine.name, theirs.name):
        _swap(league, give, other_team, get, me)
        try:
            got = session.standings([me, other_team])
            want = _slow_standings(league, session)
        finally:
            _swap(league, give, me, get, other_team)
        _assert_same(got, want)


def test_session_leaves_rosters_and_lineups_consistent(replay_league):
    league = replay_league
    me = _my_team(league)
    before = league.players.set_index("player_id_sr").fantasy_team.sort_index()
    session = league.season_sim_session(True, PAYOUTS)
    session.standings()
    session.standings([me])
    session.restore()
    after = league.players.set_index("player_id_sr").fantasy_team.sort_index()
    pd.testing.assert_series_equal(before, after)
    starters = league.players[league.players.starter & league.players.fantasy_team.notna()]
    assert set(starters.fantasy_team) == {t["name"] for t in league.teams}
