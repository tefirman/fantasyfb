"""
Fantasy football season simulation engine.

Monte Carlo simulation of fantasy football seasons, including regular season
standings, playoff brackets, and payout calculations. Completed games are
locked to their real scores so historical results aren't re-randomized;
only future weeks contribute variance.

Best ball support: pass ``best_ball=True`` to ``SeasonSimulator.simulate_season``
(with ``roster_spots`` set on the simulator) to score each week using the
optimal lineup from each team's full player pool rather than a manually-set
starter list.  The public helper ``select_optimal_lineup`` and the batch
converter ``compute_best_ball_team_projections`` are also available as
standalone functions.
"""

import pandas as pd
import numpy as np
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

# Flex slot eligibility — mirrors drafts/tools.py FLEX_ELIGIBILITY but kept
# here to avoid a sim → drafts import dependency.
_FLEX_ELIGIBILITY: Dict[str, Tuple[str, ...]] = {
    "W/T":     ("WR", "TE"),
    "W/R/T":   ("WR", "RB", "TE"),
    "Q/W/R/T": ("QB", "WR", "RB", "TE"),
}
_BASE_POSITIONS: FrozenSet[str] = frozenset(("QB", "RB", "WR", "TE", "K", "DEF"))


def select_optimal_lineup(
    positions: List[str],
    scores: np.ndarray,
    roster_spec: Dict[str, int],
) -> float:
    """Return the total score of the optimal starting lineup.

    Greedy algorithm: fill fixed-position slots (QB, RB, …) from the best
    available player at each position, then fill flex slots (W/R/T, etc.)
    from the best remaining eligible players.  This is optimal because fixed
    slots can only hold one position type, so the only real decision is which
    players fall into flex vs. bench — and that is always resolved by taking
    the highest scorer among those eligible.

    Args:
        positions: Position string for each player on the roster (length K).
        scores:    Simulated fantasy score for each player (length K).
        roster_spec: ``{slot: count}`` mapping.  BN/IR keys are ignored.

    Returns:
        Sum of scores for the optimal starting lineup.
    """
    scores = np.asarray(scores, dtype=float)
    if len(positions) == 0:
        return 0.0
    available = np.ones(len(positions), dtype=bool)
    total = 0.0

    fixed = [(s, c) for s, c in roster_spec.items()
             if s in _BASE_POSITIONS and c > 0]
    flex  = [(s, c) for s, c in roster_spec.items()
             if s in _FLEX_ELIGIBILITY and c > 0]

    for slot, count in fixed:
        pos_mask = np.array([p == slot for p in positions])
        for _ in range(count):
            eligible = pos_mask & available
            if not eligible.any():
                break
            best = int(np.where(eligible, scores, -np.inf).argmax())
            total += scores[best]
            available[best] = False

    for slot, count in flex:
        eligible_positions = _FLEX_ELIGIBILITY[slot]
        pos_mask = np.array([p in eligible_positions for p in positions])
        for _ in range(count):
            eligible = pos_mask & available
            if not eligible.any():
                break
            best = int(np.where(eligible, scores, -np.inf).argmax())
            total += scores[best]
            available[best] = False

    return total


def _lineup_score_vectorized(
    positions: np.ndarray,
    sim_scores: np.ndarray,
    roster_spec: Dict[str, int],
) -> np.ndarray:
    """Vectorized optimal lineup scorer across many simulations.

    Args:
        positions:  Shape ``(K,)`` array of position strings.
        sim_scores: Shape ``(num_sims, K)`` array of simulated player scores.
        roster_spec: ``{slot: count}`` mapping; BN/IR ignored.

    Returns:
        Shape ``(num_sims,)`` array of optimal lineup totals.
    """
    num_sims, K = sim_scores.shape
    available = np.ones((num_sims, K), dtype=bool)
    total = np.zeros(num_sims)
    sim_range = np.arange(num_sims)

    fixed = [(s, c) for s, c in roster_spec.items()
             if s in _BASE_POSITIONS and c > 0]
    flex  = [(s, c) for s, c in roster_spec.items()
             if s in _FLEX_ELIGIBILITY and c > 0]

    def _pick_best(pos_mask: np.ndarray) -> None:
        # pos_mask: (K,) boolean indicating which players are eligible by position
        eligible = available & pos_mask[np.newaxis, :]        # (num_sims, K)
        has_eligible = eligible.any(axis=1)                   # (num_sims,)
        masked = np.where(eligible, sim_scores, -np.inf)
        best_idx = masked.argmax(axis=1)                      # (num_sims,)
        total[sim_range] += np.where(
            has_eligible, sim_scores[sim_range, best_idx], 0.0,
        )
        active = np.where(has_eligible)[0]
        if active.size:
            available[active, best_idx[active]] = False

    for slot, count in fixed:
        pos_mask = positions == slot
        for _ in range(count):
            _pick_best(pos_mask)

    for slot, count in flex:
        eligible_pos = _FLEX_ELIGIBILITY[slot]
        pos_mask = np.isin(positions, eligible_pos)
        for _ in range(count):
            _pick_best(pos_mask)

    return total


def compute_best_ball_team_projections(
    player_projections: pd.DataFrame,
    roster_spots,
    n_samples: int = 1000,
) -> pd.DataFrame:
    """Convert per-player projections into team-level best-ball projections.

    For each ``(fantasy_team, week)`` group, simulates ``n_samples`` sets of
    player scores, selects the optimal lineup for each, and returns the mean
    and standard deviation of the resulting team scores.  The output has the
    same ``[fantasy_team, week, points_avg, points_stdev]`` schema as the
    team-level projections expected by ``SeasonSimulator.simulate_season``.

    Args:
        player_projections: One row per player per week, with columns
            ``[fantasy_team, week, position, points_avg, points_stdev]``.
        roster_spots: Roster-spots DataFrame (``position``/``count`` columns)
            or ``{slot: count}`` dict.  BN/IR are stripped automatically.
        n_samples: Number of lineup simulations per ``(team, week)`` used
            to estimate the best-ball score distribution.

    Returns:
        DataFrame with columns ``[fantasy_team, week, points_avg, points_stdev]``.
    """
    if isinstance(roster_spots, pd.DataFrame):
        spec: Dict[str, int] = {
            row["position"]: int(row["count"])
            for _, row in roster_spots.iterrows()
            if row["position"] not in ("BN", "IR") and int(row["count"]) > 0
        }
    else:
        spec = {
            k: int(v) for k, v in roster_spots.items()
            if k not in ("BN", "IR") and int(v) > 0
        }

    rows = []
    for (team, week), group in player_projections.groupby(["fantasy_team", "week"]):
        positions = group["position"].to_numpy(dtype=str)
        avgs = group["points_avg"].to_numpy(dtype=float)
        stds = group["points_stdev"].fillna(0.0).to_numpy(dtype=float)
        K = len(positions)

        sim_scores = np.random.normal(
            loc=avgs[np.newaxis, :],
            scale=np.maximum(stds[np.newaxis, :], 0.0),
            size=(n_samples, K),
        )
        lineup_scores = _lineup_score_vectorized(positions, sim_scores, spec)

        rows.append({
            "fantasy_team": team,
            "week": week,
            "points_avg": float(lineup_scores.mean()),
            "points_stdev": float(lineup_scores.std()),
        })

    return pd.DataFrame(rows)


NormalSource = Callable[[Tuple[int, ...]], np.ndarray]


def _global_normals(shape: Tuple[int, ...]) -> np.ndarray:
    """Standard-normal draws from numpy's global random state."""
    return np.random.normal(loc=0, scale=1, size=shape)


class CommonRandomNumbers:
    """Standard-normal draws that repeat from one simulation run to the next.

    Pass an instance as ``normals`` to ``SeasonSimulator.simulate_season``.
    The first run draws fresh numbers and remembers them; call ``rewind``
    before each later run to replay the same draws in the same order. Every
    run then sees the same luck, so differences between two rosters reflect
    the rosters rather than Monte Carlo noise. A draw whose shape no longer
    matches the remembered one is redrawn.
    """

    def __init__(self):
        self._draws: List[np.ndarray] = []
        self._next = 0

    def rewind(self) -> None:
        self._next = 0

    def __call__(self, shape: Tuple[int, ...]) -> np.ndarray:
        if self._next < len(self._draws) and self._draws[self._next].shape == tuple(shape):
            draw = self._draws[self._next]
        else:
            draw = _global_normals(shape)
            del self._draws[self._next:]
            self._draws.append(draw)
        self._next += 1
        return draw


class SeasonSimulator:
    """
    Simulates fantasy football seasons using Monte Carlo methods.

    Handles regular season play, playoff brackets, and outcome probabilities
    for any fantasy football league structure.
    """

    def __init__(self, league_settings: Dict, roster_spots=None):
        """
        Initialize simulator with league-specific settings.

        Args:
            league_settings: Dictionary containing:
                - playoff_start_week: Week when playoffs begin
                - num_playoff_teams: Number of teams making playoffs
                - uses_playoff_reseeding: Whether to reseed after each round
                - num_teams: Total teams in league
                - median_win: Optional. When true, each regular-season week
                  also pays a win to every team scoring above that week's
                  league median (half a win for a tie at the median)
                - playoff_win_threshold: Optional. For leagues whose playoffs
                  are field-wide (Scott Fish Bowl), a team "makes the
                  playoffs" by reaching this many wins. No bracket is
                  simulated, and ``earnings`` becomes that probability so
                  the move analysis still has an objective to rank by.
            roster_spots: Roster-spots DataFrame (position/count columns) or
                {slot: count} dict.  Required when ``simulate_season`` is
                called with ``best_ball=True``.
        """
        self.settings = league_settings
        self.roster_spots = roster_spots

        required_keys = ['playoff_start_week', 'num_playoff_teams']
        if not all(key in league_settings for key in required_keys):
            raise ValueError(f"league_settings must contain: {required_keys}")

    def simulate_season(self,
                       player_projections: pd.DataFrame,
                       schedule_df: pd.DataFrame,
                       num_sims: int = 10000,
                       best_ball: bool = False,
                       include_playoffs: bool = True,
                       payouts: List[float] = [800, 300, 100],
                       fixed_winner: Optional[List] = None,
                       normals: Optional[NormalSource] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Simulate a complete fantasy season with playoffs.

        Args:
            player_projections: DataFrame with columns [fantasy_team, week, points_avg, points_stdev].
                When ``best_ball=True``, must also have ``position`` column and one row per
                player per week; the simulator converts these to team-level projections via
                optimal lineup selection before running the Monte Carlo.
            schedule_df: DataFrame with columns [week, team_1, team_2, score_1, score_2]
            num_sims: Number of Monte Carlo simulations
            best_ball: When True, compute weekly team scores using the optimal lineup
                from each team's full player pool (best ball mode).  Requires
                ``roster_spots`` to be set on this simulator instance.
            include_playoffs: Whether to simulate playoffs
            payouts: Prize amounts for [1st, 2nd, 3rd, ...]
            fixed_winner: Optional [week, team_name] to force a specific outcome
            normals: Optional source of standard-normal draws, called with an
                array shape. Defaults to ``np.random.normal``. Pass a
                ``CommonRandomNumbers`` to reuse the same draws across runs.

        Returns:
            Tuple of (schedule_results, standings_results) DataFrames
        """
        if self.settings.get('playoff_win_threshold'):
            include_playoffs = False

        if best_ball:
            if self.roster_spots is None:
                raise ValueError(
                    "roster_spots must be provided on SeasonSimulator "
                    "to use best_ball=True."
                )
            player_projections = compute_best_ball_team_projections(
                player_projections, self.roster_spots
            )

        # Lock in real scores for completed games before any simulation runs.
        # Both the regular-season Monte Carlo and the playoff bracket then
        # inherit deterministic outcomes for anything already played.
        locked_projections = self._lock_completed_weeks(player_projections, schedule_df)

        schedule_with_projections = self._merge_schedule_projections(schedule_df, locked_projections)

        if fixed_winner:
            schedule_with_projections = self._apply_fixed_winner(schedule_with_projections, fixed_winner)

        normals = normals or _global_normals
        sim_1, sim_2 = self._simulate_all_matchups(
            schedule_with_projections, num_sims, normals
        )

        standings_sims, order, teams = self._calculate_regular_season_standings(
            schedule_with_projections, sim_1, sim_2
        )

        final_results = None
        if include_playoffs:
            final_results = self._simulate_playoffs(
                order, teams, locked_projections, normals
            )

        schedule_results = self._aggregate_schedule_results(
            schedule_with_projections, sim_1, sim_2
        )
        standings_results = self._aggregate_standings_results(standings_sims, final_results, payouts)

        return schedule_results, standings_results

    def _lock_completed_weeks(self, projections_df: pd.DataFrame,
                              schedule_df: pd.DataFrame) -> pd.DataFrame:
        """Override projections with real scores for completed games.

        For any (fantasy_team, week) where the team played in a game that
        already has a non-zero score, set points_avg to the real score and
        points_stdev to 0. Downstream Monte Carlo then produces a
        deterministic outcome for that matchup. Future weeks are untouched.
        """
        team1 = schedule_df[['week', 'team_1', 'score_1']].rename(
            columns={'team_1': 'fantasy_team', 'score_1': 'real_score'}
        )
        team2 = schedule_df[['week', 'team_2', 'score_2']].rename(
            columns={'team_2': 'fantasy_team', 'score_2': 'real_score'}
        )
        team_scores = pd.concat([team1, team2], ignore_index=True)
        # _clean_schedule zeros out scores for unplayed weeks, so a positive
        # real_score is the marker that the game is in the books.
        team_scores = team_scores[team_scores['real_score'].astype(float) > 0]

        if team_scores.empty:
            return projections_df.copy()

        locked = projections_df.merge(
            team_scores, on=['week', 'fantasy_team'], how='left'
        )
        completed = locked['real_score'].notna()
        locked.loc[completed, 'points_avg'] = locked.loc[completed, 'real_score'].astype(float)
        locked.loc[completed, 'points_stdev'] = 0.0
        return locked.drop(columns=['real_score'])

    def _simulate_playoffs(self, order: np.ndarray, teams: np.ndarray,
                          projections_df: pd.DataFrame,
                          normals: NormalSource) -> Optional[Dict[str, pd.Series]]:
        """Simulate playoff brackets for every simulation at once.

        Args:
            order: ``(num_sims, num_teams)`` team indices, best seed first.
            teams: Team names, indexed by the values in ``order``.
            projections_df: Locked team-week projections.
            normals: Source of standard-normal draws.

        Returns:
            ``{'winners', 'runners_up', 'third_place'}`` Series of title
            probabilities indexed by team, or None for unsupported brackets.
        """
        num_playoff_teams = self.settings['num_playoff_teams']
        if num_playoff_teams not in {4, 6}:
            # Only 4- and 6-team brackets are supported. For best-ball leagues
            # with no traditional playoff (e.g. DraftKings), call
            # simulate_season with include_playoffs=False instead.
            return None

        num_sims = order.shape[0]
        rows = np.arange(num_sims)
        start = self.settings['playoff_start_week']

        def seeded(seed):
            return order[:, seed]

        def params(week):
            return self._team_week_params(projections_df, week, teams)

        if num_playoff_teams == 6:
            # Seeds 0 and 1 have byes; 2v5 and 3v4 play the wild card round.
            (w25, _), (w34, _) = self._play_matchups(
                [(seeded(2), seeded(5)), (seeded(3), seeded(4))],
                *params(start), normals,
            )
            semifinalists = np.column_stack([seeded(0), seeded(1), w25, w34])
            if self.settings.get('uses_playoff_reseeding', False):
                rank = np.argsort(order, axis=1)
                seeds = rank[rows[:, None], semifinalists]
                semifinalists = np.take_along_axis(
                    semifinalists, np.argsort(seeds, axis=1), axis=1
                )
                top, second, third, bottom = semifinalists.T
                matchups = [(top, bottom), (second, third)]
            else:
                # Fixed bracket: the 1 seed meets the 3v4 winner.
                matchups = [(semifinalists[:, 0], semifinalists[:, 3]),
                            (semifinalists[:, 1], semifinalists[:, 2])]
            semifinal_week = start + 1
            championship_week = start + 2
        else:
            matchups = [(seeded(0), seeded(3)), (seeded(1), seeded(2))]
            semifinal_week = start
            championship_week = start + 1

        (w1, l1), (w2, l2) = self._play_matchups(
            matchups, *params(semifinal_week), normals
        )
        mu, sd = params(championship_week)
        [(winners, runners_up)] = self._play_matchups([(w1, w2)], mu, sd, normals)
        [(third_place, _)] = self._play_matchups([(l1, l2)], mu, sd, normals)

        def share(team_idx):
            counts = np.bincount(team_idx, minlength=len(teams))
            return pd.Series(counts / num_sims, index=teams)

        return {
            'winners': share(winners),
            'runners_up': share(runners_up),
            'third_place': share(third_place),
        }

    @staticmethod
    def _team_week_params(projections_df: pd.DataFrame, week: int,
                          teams: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Mean and stdev of each team's score in ``week``.

        A team with no projection that week falls back to 100 +/- 10.
        """
        week_df = (
            projections_df[projections_df['week'] == week]
            .drop_duplicates('fantasy_team')
            .set_index('fantasy_team')
            .reindex(teams)
        )
        mu = week_df['points_avg'].fillna(100.0).to_numpy(dtype=float)
        sd = week_df['points_stdev'].fillna(10.0).to_numpy(dtype=float)
        return mu, sd

    @staticmethod
    def _play_matchups(matchups: List[Tuple[np.ndarray, np.ndarray]],
                      mu: np.ndarray, sd: np.ndarray,
                      normals: NormalSource) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Play one game per ``(team_a, team_b)`` pair in every simulation.

        Each pair is two ``(num_sims,)`` arrays of team indices. Returns a
        ``(winner, loser)`` pair of arrays per matchup; a tie goes to team_a.
        """
        num_sims = len(matchups[0][0])
        z = normals((num_sims, 2 * len(matchups)))
        results = []
        for j, (team_a, team_b) in enumerate(matchups):
            score_a = z[:, 2 * j] * sd[team_a] + mu[team_a]
            score_b = z[:, 2 * j + 1] * sd[team_b] + mu[team_b]
            a_wins = score_a >= score_b
            results.append((np.where(a_wins, team_a, team_b),
                            np.where(a_wins, team_b, team_a)))
        return results

    def _merge_schedule_projections(self, schedule_df: pd.DataFrame,
                                  projections_df: pd.DataFrame) -> pd.DataFrame:
        """Merge schedule with team projections for each week."""
        schedule = schedule_df.copy()

        schedule = pd.merge(
            left=schedule,
            right=projections_df.rename(columns={
                'fantasy_team': 'team_1',
                'points_avg': 'points_avg_1',
                'points_stdev': 'points_stdev_1'
            }),
            how='left',
            on=['week', 'team_1']
        )

        schedule = pd.merge(
            left=schedule,
            right=projections_df.rename(columns={
                'fantasy_team': 'team_2',
                'points_avg': 'points_avg_2',
                'points_stdev': 'points_stdev_2'
            }),
            how='left',
            on=['week', 'team_2']
        )

        proj_cols = ['points_avg_1', 'points_avg_2', 'points_stdev_1', 'points_stdev_2']
        for col in proj_cols:
            schedule[col] = schedule[col].fillna(0.0)

        return schedule

    def _apply_fixed_winner(self, schedule_df: pd.DataFrame,
                           fixed_winner: List) -> pd.DataFrame:
        """Apply a fixed winner for a specific week/team."""
        week, team_name = fixed_winner
        schedule = schedule_df.copy()

        matchup_mask = (
            (schedule['week'] == week) &
            ((schedule['team_1'] == team_name) | (schedule['team_2'] == team_name))
        )

        if matchup_mask.any():
            if (schedule.loc[matchup_mask, 'team_1'] == team_name).any():
                winner_col, loser_col = 'points_avg_1', 'points_avg_2'
                winner_std, loser_std = 'points_stdev_1', 'points_stdev_2'
            else:
                winner_col, loser_col = 'points_avg_2', 'points_avg_1'
                winner_std, loser_std = 'points_stdev_2', 'points_stdev_1'

            schedule.loc[matchup_mask, winner_col] = 100.1
            schedule.loc[matchup_mask, loser_col] = 100.0
            schedule.loc[matchup_mask, winner_std] = 0.0
            schedule.loc[matchup_mask, loser_std] = 0.0

        return schedule

    def _simulate_all_matchups(self, schedule_df: pd.DataFrame, num_sims: int,
                              normals: NormalSource = _global_normals
                              ) -> Tuple[np.ndarray, np.ndarray]:
        """Draw both teams' scores for every game in every simulation.

        Returns two ``(num_sims, num_games)`` arrays in schedule row order.
        """
        shape = (num_sims, len(schedule_df))
        sim_1 = (
            normals(shape) * schedule_df['points_stdev_1'].to_numpy(dtype=float)
            + schedule_df['points_avg_1'].to_numpy(dtype=float)
        )
        sim_2 = (
            normals(shape) * schedule_df['points_stdev_2'].to_numpy(dtype=float)
            + schedule_df['points_avg_2'].to_numpy(dtype=float)
        )
        return sim_1, sim_2

    def _calculate_regular_season_standings(
        self, schedule_df: pd.DataFrame, sim_1: np.ndarray, sim_2: np.ndarray,
    ) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        """Win/loss records and rankings from simulated regular-season games.

        Args:
            schedule_df: Schedule with ``week``, ``team_1`` and ``team_2``.
            sim_1, sim_2: ``(num_sims, num_games)`` scores, row-aligned with
                ``schedule_df``.

        Returns:
            ``(standings, order, teams)``: ``standings`` has one row per
            simulation and team, best finish first within each simulation;
            ``order`` is the ``(num_sims, num_teams)`` team indices in that
            same ranking; ``teams`` maps those indices to names.
        """
        regular = (schedule_df['week'] < self.settings['playoff_start_week']).to_numpy()
        sim_1, sim_2 = sim_1[:, regular], sim_2[:, regular]
        weeks = schedule_df['week'].to_numpy()[regular]
        team_1 = schedule_df['team_1'].to_numpy()[regular]
        team_2 = schedule_df['team_2'].to_numpy()[regular]

        teams = np.unique(np.concatenate([team_1, team_2]))
        idx_1 = np.searchsorted(teams, team_1)
        idx_2 = np.searchsorted(teams, team_2)
        num_sims, num_games = sim_1.shape

        # (num_games, num_teams) 0/1 maps from games to the teams in them.
        to_team_1 = np.zeros((num_games, len(teams)))
        to_team_1[np.arange(num_games), idx_1] = 1.0
        to_team_2 = np.zeros((num_games, len(teams)))
        to_team_2[np.arange(num_games), idx_2] = 1.0

        win_1 = (sim_1 > sim_2).astype(float)
        win_2 = 1.0 - win_1
        if self.settings.get('median_win'):
            # Rank every team against the same week's scores in the same
            # simulation. Completed weeks carry their real scores in every
            # simulation, so they pay out the real median result.
            for week in np.unique(weeks):
                games = np.flatnonzero(weeks == week)
                median = np.median(
                    np.concatenate([sim_1[:, games], sim_2[:, games]], axis=1),
                    axis=1, keepdims=True,
                )
                for scores, wins in ((sim_1, win_1), (sim_2, win_2)):
                    block = scores[:, games]
                    wins[:, games] += (block > median) + 0.5 * (block == median)

        wins = win_1 @ to_team_1 + win_2 @ to_team_2
        points = sim_1 @ to_team_1 + sim_2 @ to_team_2

        # Rank by wins, then points (both descending). Stable sorts leave
        # exact ties in team-name order.
        by_points = np.argsort(-points, axis=1, kind='stable')
        wins_in_points_order = np.take_along_axis(wins, by_points, axis=1)
        by_wins = np.argsort(-wins_in_points_order, axis=1, kind='stable')
        order = np.take_along_axis(by_points, by_wins, axis=1)

        num_teams = len(teams)
        standings = pd.DataFrame({
            'num_sim': np.repeat(np.arange(num_sims), num_teams),
            'team': teams[order].ravel(),
            'wins': np.take_along_axis(wins, order, axis=1).ravel(),
            'points': np.take_along_axis(points, order, axis=1).ravel(),
        })

        rank = np.tile(np.arange(num_teams), num_sims)
        standings['playoffs'] = (rank < self.settings['num_playoff_teams']).astype(int)

        threshold = self.settings.get('playoff_win_threshold')
        if threshold:
            standings['playoffs'] = (standings['wins'] >= threshold).astype(int)

        standings['playoff_bye'] = 0
        if self.settings['num_playoff_teams'] == 6 and not threshold:
            standings['playoff_bye'] = (rank < 2).astype(int)

        return standings, order, teams

    def _aggregate_schedule_results(self, schedule_df: pd.DataFrame,
                                    sim_1: np.ndarray,
                                    sim_2: np.ndarray) -> pd.DataFrame:
        """Average each game's projections, scores and outcomes over the simulations."""
        results = schedule_df[[
            'week', 'team_1', 'team_2',
            'points_avg_1', 'points_stdev_1', 'points_avg_2', 'points_stdev_2',
        ]].copy()
        team_1_won = sim_1 > sim_2
        results['sim_1'] = sim_1.mean(axis=0)
        results['sim_2'] = sim_2.mean(axis=0)
        results['win_1'] = team_1_won.mean(axis=0)
        results['win_2'] = (~team_1_won).mean(axis=0)
        # The same pairing can appear twice in a week; the mean of per-row
        # means equals the pooled mean since every row has num_sims draws.
        return results.groupby(['week', 'team_1', 'team_2']).mean().round(3).reset_index()
    def _aggregate_standings_results(self, standings_sims: pd.DataFrame,
                                   playoff_results: Optional[Dict],
                                   payouts: List[float]) -> pd.DataFrame:
        """Aggregate simulated standings results."""
        standings = standings_sims.groupby('team').agg({
            'wins': ['mean', 'std'],
            'points': ['mean', 'std'],
            'playoffs': 'mean',
            'playoff_bye': 'mean'
        }).round(3).reset_index()

        standings.columns = [
            'team', 'wins_avg', 'wins_stdev', 'points_avg', 'points_stdev',
            'playoffs', 'playoff_bye'
        ]

        if playoff_results:
            standings['winner'] = standings['team'].map(playoff_results.get('winners', {})).fillna(0.0)
            standings['runner_up'] = standings['team'].map(playoff_results.get('runners_up', {})).fillna(0.0)
            standings['third'] = standings['team'].map(playoff_results.get('third_place', {})).fillna(0.0)

            earnings = (
                standings['winner'] * payouts[0] +
                standings['runner_up'] * payouts[1] +
                standings['third'] * payouts[2] if len(payouts) > 2 else 0
            )
            standings['earnings'] = earnings.round(2)
        else:
            standings['winner'] = 0.0
            standings['runner_up'] = 0.0
            standings['third'] = 0.0
            standings['earnings'] = 0.0
            if self.settings.get('playoff_win_threshold'):
                standings['earnings'] = standings['playoffs']

        standings = standings.sort_values(
            ['earnings', 'wins_avg', 'points_avg'],
            ascending=[False, False, False],
        )

        return standings


def simulate_season(player_projections: pd.DataFrame,
                   schedule_df: pd.DataFrame,
                   league_settings: Dict,
                   num_sims: int = 10000,
                   payouts: List[float] = [800, 300, 100],
                   best_ball: bool = False,
                   roster_spots=None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convenience function to simulate a season in one call.

    Args:
        player_projections: Team projections by week (or per-player projections
            when ``best_ball=True``).
        schedule_df: League schedule
        league_settings: League configuration
        num_sims: Number of simulations
        payouts: Prize distribution
        best_ball: Use optimal-lineup scoring (requires ``roster_spots``).
        roster_spots: Roster-spots DataFrame or dict; required when
            ``best_ball=True``.

    Returns:
        Tuple of (schedule_results, standings_results)
    """
    simulator = SeasonSimulator(league_settings, roster_spots=roster_spots)
    return simulator.simulate_season(
        player_projections, schedule_df, num_sims,
        best_ball=best_ball, include_playoffs=True, payouts=payouts,
    )
