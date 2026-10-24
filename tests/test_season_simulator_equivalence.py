"""The array-based SeasonSimulator must reproduce the original pandas one.

``_legacy_season_simulator`` is a frozen copy of the simulator as it was
before the rewrite. The new code draws its random numbers in the same order,
so with the same seed both must return the same tables, not just similar
ones. Every league rule the simulator knows about gets a case here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import _legacy_season_simulator as legacy
from fantasyfb.sim import season_simulator as new

TEAMS = [f"Team {chr(65 + i)}" for i in range(12)]
PLAYOFF_START = 15


def _round_robin(num_weeks: int, teams: list[str]) -> list[tuple[int, str, str]]:
    games = []
    rotation = list(teams)
    for week in range(1, num_weeks + 1):
        half = len(rotation) // 2
        for a, b in zip(rotation[:half], rotation[::-1][:half]):
            games.append((week, a, b))
        rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]
    return games


def _league(seed=0, weeks=17, teams=TEAMS, locked_weeks=0, stdev=None, means=None):
    rng = np.random.default_rng(seed)
    games = _round_robin(weeks, teams)
    proj = pd.DataFrame([
        {
            "fantasy_team": t, "week": w,
            "points_avg": means if means is not None else rng.uniform(80, 130),
            "points_stdev": stdev if stdev is not None else rng.uniform(10, 25),
        }
        for t in teams for w in range(1, weeks + 1)
    ])
    sched = pd.DataFrame(games, columns=["week", "team_1", "team_2"])
    sched["score_1"] = 0.0
    sched["score_2"] = 0.0
    done = sched["week"] <= locked_weeks
    sched.loc[done, "score_1"] = rng.uniform(70, 140, done.sum())
    sched.loc[done, "score_2"] = rng.uniform(70, 140, done.sum())
    return proj, sched


def _settings(**kw):
    return {"playoff_start_week": PLAYOFF_START, "num_playoff_teams": 6,
            "num_teams": 12, **kw}


def _run(module, settings, proj, sched, seed=1234, num_sims=400, **kw):
    np.random.seed(seed)
    sim = module.SeasonSimulator(settings)
    return sim.simulate_season(proj, sched, num_sims=num_sims, **kw)


def _assert_same(settings, proj, sched, **kw):
    old_sched, old_stand = _run(legacy, settings, proj, sched, **kw)
    new_sched, new_stand = _run(new, settings, proj, sched, **kw)
    pd.testing.assert_frame_equal(new_sched, old_sched, check_exact=False, atol=1e-9)
    pd.testing.assert_frame_equal(
        new_stand.reset_index(drop=True), old_stand.reset_index(drop=True),
        check_exact=False, atol=1e-9,
    )
    return new_sched, new_stand


@pytest.mark.parametrize("playoff_teams", [4, 6])
@pytest.mark.parametrize("reseed", [False, True])
def test_brackets(playoff_teams, reseed):
    proj, sched = _league()
    _, stand = _assert_same(
        _settings(num_playoff_teams=playoff_teams, uses_playoff_reseeding=reseed),
        proj, sched,
    )
    assert stand["winner"].sum() == pytest.approx(1.0)
    assert stand["earnings"].sum() > 0


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_other_seeds_and_leagues(seed):
    proj, sched = _league(seed=seed)
    _assert_same(_settings(uses_playoff_reseeding=bool(seed % 2)), proj, sched,
                 seed=seed)


@pytest.mark.parametrize("num_teams,playoff_teams", [(10, 6), (10, 4), (8, 6), (14, 6)])
def test_leagues_whose_size_is_not_a_multiple_of_the_bracket(num_teams, playoff_teams):
    # The original seeded the bracket from the row index across all
    # simulations, which rotated the seeds from one simulation to the next in
    # these leagues (see the note in _legacy_season_simulator.py).
    teams = [f"Team {chr(65 + i)}" for i in range(num_teams)]
    proj, sched = _league(teams=teams)
    _, stand = _assert_same(
        _settings(num_teams=num_teams, num_playoff_teams=playoff_teams), proj, sched,
    )
    if playoff_teams == 6:
        # Seeds are by rank: the two byes always go to the two best records.
        assert stand["playoff_bye"].sum() == pytest.approx(2.0, abs=0.01)


def test_regular_season_only():
    proj, sched = _league()
    _, stand = _assert_same(_settings(), proj, sched, include_playoffs=False)
    assert (stand["winner"] == 0).all()


def test_completed_weeks_are_locked_to_real_scores():
    proj, sched = _league(locked_weeks=6)
    _assert_same(_settings(), proj, sched)


def test_fixed_winner():
    proj, sched = _league(locked_weeks=3)
    _assert_same(_settings(), proj, sched, fixed_winner=[5, TEAMS[2]])


def test_median_win():
    proj, sched = _league(locked_weeks=4)
    _assert_same(_settings(median_win=True), proj, sched)


def test_win_threshold_leagues():
    proj, sched = _league()
    sched = sched[sched.week < 12].reset_index(drop=True)
    _, stand = _assert_same(
        _settings(playoff_start_week=12, playoff_win_threshold=7), proj, sched,
    )
    assert (stand["earnings"] == stand["playoffs"]).all()


def test_unsupported_bracket_size_skips_playoffs():
    proj, sched = _league()
    _assert_same(_settings(num_playoff_teams=8), proj, sched)


def test_missing_playoff_projections_fall_back_to_defaults():
    proj, sched = _league()
    proj = proj[~((proj.fantasy_team == TEAMS[0]) & (proj.week >= PLAYOFF_START))]
    _assert_same(_settings(), proj, sched)


def test_exact_ties_break_the_same_way():
    # Every team identical and deterministic: wins, points, and every game tie.
    proj, sched = _league(stdev=0.0, means=100.0)
    _assert_same(_settings(), proj, sched, num_sims=20)


def test_repeated_matchups_in_one_week():
    proj, sched = _league(weeks=5)
    sched = pd.concat([sched, sched[sched.week == 2]], ignore_index=True)
    _assert_same(_settings(playoff_start_week=4, num_playoff_teams=4), proj, sched)


def test_best_ball_path():
    proj, sched = _league(weeks=6)
    players = []
    rng = np.random.default_rng(5)
    for _, row in proj.iterrows():
        for pos in ("QB", "RB", "RB", "WR", "WR"):
            players.append({**row.to_dict(), "position": pos,
                            "points_avg": rng.uniform(5, 25),
                            "points_stdev": rng.uniform(3, 8)})
    players = pd.DataFrame(players)
    spots = {"QB": 1, "RB": 2, "WR": 2}
    outputs = []
    for module in (legacy, new):
        np.random.seed(9)
        sim = module.SeasonSimulator(
            _settings(playoff_start_week=5, num_playoff_teams=4), roster_spots=spots,
        )
        outputs.append(sim.simulate_season(players, sched[sched.week <= 6],
                                           num_sims=200, best_ball=True))
    pd.testing.assert_frame_equal(outputs[0][0], outputs[1][0], check_exact=False, atol=1e-9)
    pd.testing.assert_frame_equal(
        outputs[0][1].reset_index(drop=True), outputs[1][1].reset_index(drop=True),
        check_exact=False, atol=1e-9,
    )


class TestCommonRandomNumbers:
    def test_replays_the_same_draws_after_rewind(self):
        crn = new.CommonRandomNumbers()
        first = crn((5, 3)).copy()
        crn.rewind()
        assert (crn((5, 3)) == first).all()

    def test_redraws_when_the_shape_changes(self):
        crn = new.CommonRandomNumbers()
        crn((5, 3))
        crn.rewind()
        assert crn((4, 3)).shape == (4, 3)

    def test_identical_rosters_give_identical_results(self):
        proj, sched = _league()
        crn = new.CommonRandomNumbers()
        results = []
        for _ in range(2):
            crn.rewind()
            sim = new.SeasonSimulator(_settings())
            results.append(sim.simulate_season(proj, sched, num_sims=300, normals=crn)[1])
        pd.testing.assert_frame_equal(results[0], results[1])
