"""Tests for the SFB field simulation (fantasyfb.sfb).

Everything here is synthetic: tiny fields built in memory, no Sleeper calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasyfb.sfb import FieldData, Rules, simulate_field
from fantasyfb.sfb import collect as sfb_collect
from fantasyfb.sfb.field import (
    qualify, simulate_playoffs, simulate_regular_season, standardized_noise, team_week_matrices,
)
from fantasyfb.sfb.leagues import league_list, parse_leaderboard
from fantasyfb.sim.season_simulator import SeasonSimulator

TINY = Rules(
    auto_wins=3, field_quota=4, field_teams=8, regular_season_weeks=2,
    round_names=("r1", "r2", "r3"), playoff_weeks=(3, 4, 5),
    round_starts=(4, 2, 1), average_weights=(1.0, 0.5, 0.5),
)


def make_field(num_leagues=2, teams_per_league=4, shared_player=True):
    """Leagues with one starter per team; teams in `a` slot share a player across leagues."""
    starters, schedule, settings, teams = [], [], [], []
    for lg in range(num_leagues):
        league_id = f"L{lg}"
        names = [f"t{i}" for i in range(teams_per_league)]
        for i, name in enumerate(names):
            teams.append(dict(league_id=league_id, team=name, roster_id=i + 1))
            for week in (1, 2, 3, 4, 5):
                player = "shared" if (i == 0 and shared_player) else f"{league_id}_{name}"
                starters.append(dict(league_id=league_id, team=name, week=week, player_id=player,
                                     mu=100.0 + 10 * i, sd=20.0))
        for week in (1, 2):
            for a, b in ((0, 1), (2, 3)):
                schedule.append(dict(league_id=league_id, week=week, team_1=names[a], team_2=names[b],
                                     points_avg_1=100.0 + 10 * a, points_stdev_1=20.0,
                                     points_avg_2=100.0 + 10 * b, points_stdev_2=20.0))
        settings.append(dict(league_id=league_id, first_week=1, playoff_start_week=3,
                             num_playoff_teams=2, median_win=True, playoff_win_threshold=0,
                             num_teams=teams_per_league))
    return FieldData(
        starters=pd.DataFrame(starters), schedule=pd.DataFrame(schedule),
        settings=pd.DataFrame(settings).set_index("league_id"), teams=pd.DataFrame(teams),
    )


class TestQualify:
    def test_automatic_qualifiers_then_points_fill_the_quota(self):
        wins = np.array([[3, 3, 1, 1, 2, 0, 0, 2]], dtype=float)
        points = np.array([[10, 20, 80, 70, 60, 5, 6, 50]], dtype=float)
        qualified, auto, quota = qualify(wins, points, TINY)
        assert quota == 4
        assert auto[0].tolist() == [True, True, False, False, False, False, False, False]
        # two spots left, taken by the highest-scoring teams without enough wins
        assert qualified[0].tolist() == [True, True, True, True, False, False, False, False]

    def test_quota_scales_to_the_teams_simulated(self):
        wins = np.zeros((1, 4))
        _, _, quota = qualify(wins, np.arange(4.0)[None], TINY)
        assert quota == 2  # half of 4 teams


class TestPlayoffs:
    def test_each_round_starts_with_the_scaled_field(self):
        rng = np.random.default_rng(0)
        qualified = np.ones((200, 8), dtype=bool)
        qualified[:, 4:] = False
        total = rng.normal(200, 10, (200, 8))
        mu, sd = np.full((8, 3), 100.0), np.full((8, 3), 15.0)
        reach = simulate_playoffs(qualified, total, mu, sd, TINY)
        # 8 teams simulated -> scale 8/8; qualifiers 4 -> 2 -> 1 -> one winner
        assert reach.shape == (8, 4)
        assert reach.sum(0) == pytest.approx([4, 2, 1, 1])

    def test_unqualified_teams_never_advance(self):
        qualified = np.zeros((50, 8), dtype=bool)
        qualified[:, :4] = True
        reach = simulate_playoffs(qualified, np.full((50, 8), 200.0), np.full((8, 3), 100.0), np.full((8, 3), 10.0), TINY)
        assert (reach[4:] == 0).all()

    def test_season_average_includes_earlier_playoff_weeks(self):
        # Equal 2-game averages going in. Team 0 scores 300 in the first playoff week and team 1
        # scores 100; in round 2 (weight 1) team 1 outscores team 0 that week, 150 to 100. With the
        # average updated through week 1, team 0 leads 233.3 + 100 to 166.7 + 150 and advances;
        # with the average frozen at 200, team 1 would lead 350 to 300.
        qualified = np.zeros((1, 8), dtype=bool)
        qualified[:, :2] = True
        total = np.zeros((1, 8))
        total[:, :2] = 400.0
        mu = np.zeros((8, 3))
        mu[0] = [300, 100, 0]
        mu[1] = [100, 150, 0]
        rules = Rules(auto_wins=3, field_quota=2, field_teams=8, regular_season_weeks=2,
                      round_names=("r1", "r2", "r3"), playoff_weeks=(3, 4, 5),
                      round_starts=(2, 2, 1), average_weights=(0.0, 1.0, 0.0))
        reach = simulate_playoffs(qualified, total, mu, np.zeros((8, 3)), rules)
        assert reach[0, 2] == 1 and reach[1, 2] == 0


class TestSharedDraws:
    def test_team_noise_has_unit_variance_and_matches_team_totals(self):
        data = make_field()
        weeks, num_players = team_week_matrices(data)
        A, mu, sd = weeks[1]
        assert mu[:4].tolist() == [100.0, 110.0, 120.0, 130.0]
        assert sd[0] == pytest.approx(20.0)  # one starter with stdev 20
        draws = np.random.default_rng(0).standard_normal((num_players, 20000), dtype=np.float32)
        noise = standardized_noise(A, sd, draws)
        assert noise.std(1) == pytest.approx(np.ones(len(sd)), abs=0.03)

    def test_teams_starting_the_same_player_are_correlated_across_leagues(self):
        data = make_field()
        weeks, num_players = team_week_matrices(data)
        A, _, sd = weeks[1]
        draws = np.random.default_rng(0).standard_normal((num_players, 20000), dtype=np.float32)
        noise = standardized_noise(A, sd, draws)
        teams = data.teams
        i0 = teams.index[(teams.league_id == "L0") & (teams.team == "t0")][0]
        j0 = teams.index[(teams.league_id == "L1") & (teams.team == "t0")][0]
        j1 = teams.index[(teams.league_id == "L1") & (teams.team == "t1")][0]
        assert np.corrcoef(noise[i0], noise[j0])[0, 1] == pytest.approx(1.0, abs=1e-3)
        assert abs(np.corrcoef(noise[i0], noise[j1])[0, 1]) < 0.05

    def test_a_team_with_several_starters_adds_their_variances(self):
        data = make_field()
        extra = data.starters[(data.starters.league_id == "L0") & (data.starters.team == "t1")].assign(
            player_id="bonus", mu=50.0, sd=15.0)
        data.starters = pd.concat([data.starters, extra], ignore_index=True)
        weeks, _ = team_week_matrices(data)
        _, mu, sd = weeks[1]
        row = data.teams.index[(data.teams.league_id == "L0") & (data.teams.team == "t1")][0]
        assert mu[row] == pytest.approx(160.0)
        assert sd[row] == pytest.approx(25.0)  # sqrt(20^2 + 15^2)

    def test_unknown_team_in_starters_is_rejected(self):
        data = make_field()
        data.teams = data.teams.iloc[1:].reset_index(drop=True)
        with pytest.raises(ValueError, match="missing from the teams table"):
            team_week_matrices(data)


class TestSimulateField:
    def test_end_to_end_on_a_tiny_field(self):
        result = simulate_field(make_field(), num_sims=300, playoff_reps=3, seed=4, rules=TINY)
        teams = result.teams
        assert len(teams) == 8 and result.quota == 4
        assert teams.qualify.sum() == pytest.approx(4)
        assert teams.reach_r2.sum() == pytest.approx(2) and teams.win.sum() == pytest.approx(1)
        # the strongest team in each league beats the weakest
        strong = teams[teams.team == "t3"].qualify.mean()
        weak = teams[teams.team == "t0"].qualify.mean()
        assert strong > weak
        assert (teams.points / 2 == teams.avg_ppg).all()

    def test_shared_players_make_the_whole_field_move_together(self):
        def spread_of_field_average(shared):
            data = make_field(num_leagues=4, shared_player=shared)
            weeks, num_players = team_week_matrices(data)
            _, points = simulate_regular_season(data, weeks, num_players, 2000, np.random.default_rng(3))
            return points.mean(1).std()  # how much the field's average score varies run to run
        assert spread_of_field_average(True) > 1.2 * spread_of_field_average(False)

    def test_same_seed_gives_the_same_answer(self):
        a = simulate_field(make_field(), num_sims=100, playoff_reps=2, seed=7, rules=TINY).teams
        b = simulate_field(make_field(), num_sims=100, playoff_reps=2, seed=7, rules=TINY).teams
        pd.testing.assert_frame_equal(a, b)


def test_regular_season_results_include_median_wins():
    simulator = SeasonSimulator({
        "playoff_start_week": 2, "num_playoff_teams": 2, "num_teams": 4, "median_win": True,
    })
    games = pd.DataFrame({"week": [1, 1], "team_1": ["a", "c"], "team_2": ["b", "d"]})
    sim_1 = np.array([[100.0, 60.0]])
    sim_2 = np.array([[50.0, 40.0]])
    results = simulator.regular_season_results(games, sim_1, sim_2).set_index("team")
    # a beats b and is above the median (55); c beats d and is above it; b and d are below
    assert results.wins.to_dict() == {"a": 2.0, "b": 0.0, "c": 2.0, "d": 0.0}
    assert results.points.to_dict() == {"a": 100.0, "b": 50.0, "c": 60.0, "d": 40.0}


LEADERBOARD = """
<table><thead><tr><td>Rank</td></tr></thead><tbody>
<tr><td>1</td><td class="full">Sleeper</td><td class="full">Ann (@ann) <span>Team A</span>
<a href="javascript:openWin('https://sleeper.com/roster/1111/3')">See Team</a></td>
<td>9</td><td>3</td><td>1500.50</td><td>250.08</td><td>1200.00</td></tr>
<tr><td>2</td><td class="full">Sleeper</td><td class="full">Bo <span>Team B</span>
<a href="javascript:openWin('https://sleeper.com/roster/1111/4')">See Team</a></td>
<td>8</td><td>4</td><td>1400.00</td><td>233.33</td><td>1250.00</td></tr>
<tr><td>3</td><td class="full">MFL</td><td class="full">Cy <span>Team C</span>
<a href="javascript:openWin('https://www43.myfantasyleague.com/2026/fantasy_box_score?L=555&amp;F=0004&amp;O=07&amp;TYPE=BOTH')">See Team</a></td>
<td>7</td><td>5</td><td>1300.00</td><td>216.67</td><td>1300.00</td></tr>
<tr><td>4</td><td>no link here</td></tr>
</tbody></table>
"""


class TestLeaderboard:
    def test_parses_sleeper_and_mfl_rows(self):
        teams = parse_leaderboard(LEADERBOARD)
        assert teams[["platform", "league_id", "roster_id"]].values.tolist() == [
            ["sleeper", "1111", 3], ["sleeper", "1111", 4], ["mfl", "555", 4]]
        first = teams.iloc[0]
        assert (first["rank"], first.w, first.l, first.pf, first.avg, first.pa) == (
            "1", "9", "3", "1500.50", "250.08", "1200.00")

    def test_league_list_counts_listed_teams(self):
        leagues = league_list(parse_leaderboard(LEADERBOARD))
        assert leagues.to_dict("records") == [
            {"platform": "mfl", "league_id": "555", "n_teams": 1},
            {"platform": "sleeper", "league_id": "1111", "n_teams": 2},
        ]

    def test_page_without_a_table_is_rejected(self):
        with pytest.raises(ValueError, match="No leaderboard table"):
            parse_leaderboard("<html></html>")


class TestRequestLimiter:
    def test_spaces_requests_and_counts_them(self):
        limiter = sfb_collect.RequestLimiter(max_per_minute=6000)  # 10 ms apart
        sent = []

        def send(url):
            sent.append(url)
            return type("R", (), {"status_code": 200})()

        for url in "abc":
            limiter.get(send, url)
        assert sent == ["a", "b", "c"] and limiter.calls == 3

    def test_stops_everything_after_a_429(self):
        limiter = sfb_collect.RequestLimiter(max_per_minute=6000)

        def send(url):
            return type("R", (), {"status_code": 429})()

        limiter.get(send, "x")
        assert limiter.rate_limited == 1
        with pytest.raises(RuntimeError, match="429"):
            limiter.get(send, "y")

    def test_throttled_requests_restores_requests_get(self):
        import requests
        original = requests.get
        with sfb_collect.throttled_requests(6000):
            assert requests.get is not original
        assert requests.get is original


class TestCollectField:
    def fake_league(self, league_id):
        return dict(
            starters=pd.DataFrame({"league_id": [league_id], "team": ["t"], "week": [7], "player_id": ["p"], "mu": [1.0], "sd": [1.0]}),
            schedule=pd.DataFrame({"league_id": [league_id], "week": [1]}),
            settings=pd.DataFrame({"league_id": [league_id], "first_week": [7]}),
            teams=pd.DataFrame({"league_id": [league_id], "team": ["t"], "roster_id": [1]}),
        )

    def test_failures_are_reported_and_retries_merge_into_existing_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sfb_collect, "League", lambda **kwargs: object())
        fail = {"B"}

        def fake_collect(template, league_id):
            if league_id in fail:
                raise RuntimeError("404")
            return self.fake_league(league_id)

        monkeypatch.setattr(sfb_collect, "collect_league", fake_collect)
        errors = sfb_collect.collect_field(["A", "B", "C"], tmp_path, workers=1, log=lambda *_: None)
        assert errors == [("B", "RuntimeError: 404")]
        assert sorted(pd.read_parquet(tmp_path / "settings.parquet").league_id) == ["A", "C"]

        fail.clear()
        assert sfb_collect.collect_field(["B", "A"], tmp_path, workers=1, log=lambda *_: None) == []
        settings = pd.read_parquet(tmp_path / "settings.parquet")
        assert sorted(settings.league_id) == ["A", "B", "C"]  # A refreshed in place, not duplicated
