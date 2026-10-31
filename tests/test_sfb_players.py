"""Tests for the SFB player swings (fantasyfb.sfb.players), on synthetic fields."""

from __future__ import annotations

import numpy as np
import pytest

from fantasyfb.sfb.players import PlayoffSwing, qualification_swing, standardized_output


def test_qualification_swing_matches_the_normal_density_at_zero():
    # Everyone owns the player and qualifies exactly when his output is positive, so the slope of
    # the qualification rate on a standard normal is E[x * 1(x > 0)] = 1 / sqrt(2 pi).
    output = np.random.default_rng(0).standard_normal((200_000, 1)).astype(np.float32)
    qualified = np.repeat(output > 0, 3, axis=1)
    swing = qualification_swing(qualified, np.ones((3, 1), dtype=np.float32), output)
    assert swing[0] == pytest.approx(1 / np.sqrt(2 * np.pi), abs=0.01)


def test_playoff_swing_recovers_the_slope_and_ignores_teams_that_missed_the_playoffs():
    rng = np.random.default_rng(1)
    output = rng.standard_normal((5000, 1)).astype(np.float32)
    qualified = np.array([[True, True, False]] * 5000)
    advanced = np.column_stack([2 * output[:, 0], 2 * output[:, 0], 100 * output[:, 0]]).astype(np.float32)
    tracker = PlayoffSwing(qualified, np.ones((3, 1), dtype=np.float32))
    tracker.add(advanced, output)
    assert tracker.swing()[0] == pytest.approx(2.0, abs=1e-3)
    assert tracker.playoff_share()[0] == pytest.approx(1.0)


def test_swings_are_missing_for_a_player_nobody_starts():
    own = np.zeros((3, 1), dtype=np.float32)
    output = np.random.default_rng(2).standard_normal((50, 1)).astype(np.float32)
    assert np.isnan(qualification_swing(np.ones((50, 3), dtype=bool), own, output)[0])
    tracker = PlayoffSwing(np.ones((50, 3), dtype=bool), own)
    tracker.add(np.ones((50, 3), dtype=np.float32), output)
    assert np.isnan(tracker.swing()[0])


def test_standardized_output_has_unit_variance_and_zero_for_no_variance():
    rng = np.random.default_rng(3)
    draws = {1: rng.standard_normal((2, 20_000)).astype(np.float32),
             2: rng.standard_normal((2, 20_000)).astype(np.float32)}
    sds = np.array([[10.0, 0.0], [30.0, 0.0]])
    out = standardized_output(draws, sds, [1, 2])
    assert out[:, 0].std() == pytest.approx(1.0, abs=0.02)
    assert (out[:, 1] == 0).all()
