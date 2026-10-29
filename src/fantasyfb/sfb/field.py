"""Simulate the whole SFB field with player draws shared across leagues.

Each week a player gets one standard-normal draw per simulation, used by every
team in every league that starts him: a team's score is the sum over its
starters of (mean + stdev x draw). Each team's score keeps the same
distribution as drawing it on its own (mean = sum of means, variance = sum of
variances); what the shared draws add is the correlation between teams, which
widens the field-wide cut line a great deal.

Regular-season weeks use each league's schedule and median games. Playoff
weeks reuse the same player pool with fresh draws for every replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import pandas as pd

from ..sim.season_simulator import SeasonSimulator


@dataclass(frozen=True)
class Rules:
    """SFB qualification and playoff rules (see https://scottfishbowl.com/rules2026.php).

    ``round_starts`` is the number of teams that start each round across the full
    field. The rules page calls the cut "X%" and finalizes it after week 11, so
    these are the values to change when the real numbers are published.
    """
    auto_wins: int = 13
    field_quota: int = 2500
    field_teams: int = 5004
    regular_season_weeks: int = 11
    round_names: Tuple[str, ...] = (
        "wild_card_1", "wild_card_2", "wild_card_3", "wild_card_4", "semi_finals", "finals",
    )
    playoff_weeks: Tuple[int, ...] = (12, 13, 14, 15, 16, 17)
    round_starts: Tuple[int, ...] = (2500, 2000, 1500, 1000, 500, 50)
    # Share of the points-per-game average added to each round's score. The
    # average covers every game played before that week, playoff weeks included.
    average_weights: Tuple[float, ...] = (1.0, 1.0, 1.0, 0.5, 0.5, 0.5)


@dataclass
class FieldData:
    """What a field simulation needs from the leagues (written by ``sfb.collect``)."""
    starters: pd.DataFrame  # league_id, team, week, player_id, mu, sd
    schedule: pd.DataFrame  # league_id, week, team_1, team_2, points_avg_1/2, points_stdev_1/2
    settings: pd.DataFrame  # league_id, first_week, playoff_start_week, num_playoff_teams, ...
    teams: pd.DataFrame     # league_id, team, roster_id

    @classmethod
    def load(cls, path) -> "FieldData":
        path = Path(path)
        return cls(
            starters=pd.read_parquet(path / "starters.parquet"),
            schedule=pd.read_parquet(path / "schedule.parquet"),
            settings=pd.read_parquet(path / "settings.parquet").set_index("league_id"),
            teams=pd.read_parquet(path / "teams.parquet"),
        )


@dataclass
class FieldResult:
    """Output of ``simulate_field``.

    ``teams`` has one row per team with its ``qualify`` probability, the chance
    of starting each later round (``reach_<round>``), ``win``, and expected
    ``wins``, ``points`` and ``avg_ppg`` for the regular season. ``cut_line`` is
    the points total of the last team to qualify on points, per simulation.
    """
    teams: pd.DataFrame
    cut_line: np.ndarray
    quota: int


def simulate_field(
    data: FieldData,
    num_sims: int = 1000,
    playoff_reps: int = 20,
    seed: int = 1,
    rules: Rules = Rules(),
) -> FieldResult:
    """Simulates every league's regular season, the qualification cut, and the playoffs.

    Args:
        data: collected league data.
        num_sims: number of regular-season simulations of the whole field.
        playoff_reps: playoff replays per regular-season simulation, averaged.
            Each replay draws new player scores for weeks 12-17, which steadies
            the late-round odds without more regular-season work.
        seed: random seed.
        rules: qualification and playoff rules.
    """
    rng = np.random.default_rng(seed)
    weeks, num_players = team_week_matrices(data)
    wins, points = simulate_regular_season(data, weeks, num_players, num_sims, rng)
    qual, auto, quota = qualify(wins, points, rules)

    by_points = qual & ~auto
    cut_line = np.array([points[i][by_points[i]].min() if by_points[i].any() else np.nan
                         for i in range(num_sims)])

    mu = np.column_stack([weeks[w][1] for w in rules.playoff_weeks])
    sd = np.column_stack([weeks[w][2] for w in rules.playoff_weeks])

    def draws(prng, r):
        A, _, team_sd = weeks[rules.playoff_weeks[r]]
        return standardized_noise(A, team_sd, prng.standard_normal((num_players, num_sims), dtype=np.float32)).T

    reach = simulate_playoffs(qual, points, mu, sd, rules, seed=seed, reps=playoff_reps, draws=draws)
    teams = data.teams.copy()
    teams["qualify"] = qual.mean(0)
    for i, name in enumerate(rules.round_names[1:], start=1):
        teams[f"reach_{name}"] = reach[:, i]
    teams["win"] = reach[:, -1]
    teams["wins"] = wins.mean(0)
    teams["points"] = points.mean(0)
    teams["avg_ppg"] = teams.points / rules.regular_season_weeks
    return FieldResult(teams=teams, cut_line=cut_line, quota=quota)


def team_week_matrices(data: FieldData):
    """Per week: (num_team, num_player) starter stdevs, team mean and team stdev.

    Returns:
        ``({week: (A, mu, sd)}, num_players)``; row ``i`` of each array is
        ``data.teams.iloc[i]``.
    """
    team_index = pd.MultiIndex.from_frame(data.teams[["league_id", "team"]])
    starters = data.starters
    team_i = team_index.get_indexer(pd.MultiIndex.from_frame(starters[["league_id", "team"]]))
    if (team_i < 0).any():
        raise ValueError("starters include teams missing from the teams table")
    player_i, players = pd.factorize(starters.player_id)
    out = {}
    for week, rows in starters.assign(team_i=team_i, player_i=player_i).groupby("week"):
        A = np.zeros((len(data.teams), len(players)), dtype=np.float32)
        np.add.at(A, (rows.team_i.to_numpy(), rows.player_i.to_numpy()), rows.sd.to_numpy(dtype=np.float32))
        mu = np.bincount(rows.team_i, weights=rows.mu, minlength=len(data.teams))
        sd = np.sqrt(np.bincount(rows.team_i, weights=rows.sd.to_numpy() ** 2, minlength=len(data.teams)))
        out[int(week)] = (A, mu, sd)
    return out, len(players)


def standardized_noise(A: np.ndarray, team_sd: np.ndarray, draws: np.ndarray) -> np.ndarray:
    """(num_team, num_sim) unit-variance team-score noise from per-player draws.

    Args:
        A: (num_team, num_player) starter stdevs.
        team_sd: (num_team,) stdev of each team's score.
        draws: (num_player, num_sim) standard-normal draws.
    """
    noise = A @ draws
    return noise / np.where(team_sd > 0, team_sd, 1.0)[:, None].astype(np.float32)


def simulate_regular_season(
    data: FieldData, weeks: dict, num_players: int, num_sims: int, rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    """Wins and points, as (num_sim, num_team) arrays, for every league with shared player draws."""
    settings = data.settings
    team_index = pd.MultiIndex.from_frame(data.teams[["league_id", "team"]])
    first_week = int(settings.first_week.min())
    noise = {}
    for week in range(first_week, int(settings.playoff_start_week.max())):
        A, _, team_sd = weeks[week]
        draws = rng.standard_normal((num_players, num_sims), dtype=np.float32)
        noise[week] = standardized_noise(A, team_sd, draws)

    wins = np.zeros((num_sims, len(data.teams)), dtype=np.float32)
    points = np.zeros_like(wins)
    for league_id, games in data.schedule.groupby("league_id", sort=False):
        cfg = settings.loc[league_id]
        games = games[games.week < cfg.playoff_start_week].reset_index(drop=True)
        idx_1 = team_index.get_indexer(pd.MultiIndex.from_arrays([games.league_id, games.team_1]))
        idx_2 = team_index.get_indexer(pd.MultiIndex.from_arrays([games.league_id, games.team_2]))
        z_1 = np.zeros((num_sims, len(games)), dtype=np.float32)
        z_2 = np.zeros_like(z_1)
        for week in games.week.unique():
            if week in noise:  # earlier weeks are locked to real scores (stdev 0)
                rows = np.flatnonzero(games.week.to_numpy() == week)
                z_1[:, rows] = noise[week][idx_1[rows]].T
                z_2[:, rows] = noise[week][idx_2[rows]].T
        sim_1 = z_1 * games.points_stdev_1.to_numpy() + games.points_avg_1.to_numpy()
        sim_2 = z_2 * games.points_stdev_2.to_numpy() + games.points_avg_2.to_numpy()
        simulator = SeasonSimulator({
            "playoff_start_week": int(cfg.playoff_start_week),
            "num_playoff_teams": int(cfg.num_playoff_teams),
            "num_teams": int(cfg.num_teams),
            "median_win": bool(cfg.median_win),
            "playoff_win_threshold": int(cfg.playoff_win_threshold) or None,
        })
        results = simulator.regular_season_results(games, sim_1, sim_2)
        cols = team_index.get_indexer(pd.MultiIndex.from_arrays(
            [np.full(len(results), league_id), results.team.to_numpy()]))
        wins[results.num_sim.to_numpy(), cols] = results.wins.to_numpy()
        points[results.num_sim.to_numpy(), cols] = results.points.to_numpy()
    return wins, points


def qualify(wins: np.ndarray, points: np.ndarray, rules: Rules = Rules()):
    """Who makes the playoffs in each simulation.

    Teams with ``auto_wins`` or more wins qualify; the rest of the field's
    quota is filled by points. The quota is scaled to the number of teams
    simulated.

    Returns:
        ``(qualified, automatic, quota)``: two (num_sim, num_team) bool arrays and the quota.
    """
    quota = round(rules.field_quota * wins.shape[1] / rules.field_teams)
    auto = wins >= rules.auto_wins
    need = quota - auto.sum(1)
    rank_rest = np.argsort(np.argsort(np.where(auto, np.inf, -points), axis=1), axis=1)
    return auto | (rank_rest < need[:, None]), auto, quota


def simulate_playoffs(
    qualified: np.ndarray,
    total: np.ndarray,
    mu: np.ndarray,
    sd: np.ndarray,
    rules: Rules = Rules(),
    seed: int = 0,
    reps: int = 1,
    draws: Optional[Callable] = None,
) -> np.ndarray:
    """Plays the playoff rounds for each simulation.

    In each round a team scores ``average_weight x (points per game so far) +
    that week's score``, and the top teams advance (the next round's starting
    field, scaled to the teams simulated). The last round has a single winner.

    Args:
        qualified: (num_sim, num_team) bool, who makes the playoffs.
        total: (num_sim, num_team) regular-season points scored.
        mu, sd: (num_team, num_rounds) projected mean and stdev of each team's playoff-week score.
        draws: optional ``draws(rng, r)`` returning (num_sim, num_team) standard normals for
            round ``r`` (e.g. shared player draws); defaults to independent draws per team.
        reps: replays per regular-season simulation, averaged.

    Returns:
        (num_team, num_rounds + 1): the probability of starting each round, then of winning.
    """
    if reps > 1:
        return np.mean([simulate_playoffs(qualified, total, mu, sd, rules, seed + i, draws=draws)
                        for i in range(reps)], axis=0)
    rng = np.random.default_rng(seed)
    scale = qualified.shape[1] / rules.field_teams
    alive = qualified.copy()
    total = total.astype(np.float64)
    reached = []
    for r in range(len(rules.round_starts)):
        reached.append(alive.mean(0))
        z = draws(rng, r) if draws else rng.standard_normal(total.shape)
        week = mu[:, r] + sd[:, r] * z
        score = rules.average_weights[r] * total / (rules.regular_season_weeks + r) + week
        total = total + week
        last = r + 1 == len(rules.round_starts)
        keep = 1 if last else max(1, round(rules.round_starts[r + 1] * scale))
        rank = np.argsort(np.argsort(np.where(alive, -score, np.inf), axis=1), axis=1)
        alive = alive & (rank < keep)
    reached.append(alive.mean(0))
    return np.column_stack(reached)
