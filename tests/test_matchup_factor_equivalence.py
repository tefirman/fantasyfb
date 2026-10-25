"""The memoized MatchupModel.apply_factors must equal the original row-by-row one.

``_LegacyMatchupModel`` is the implementation as it was before the speedup
(``iterrows`` plus a DataFrame filter per ``_z_allowed`` call). Both run over
the replayed snapshot league's real players and schedule for every week, and
the factors must match to the last bit.
"""

from __future__ import annotations

import pandas as pd
import pytest
import snapshot_io

from fantasyfb.scoring.matchup_model import MatchupModel

SNAPSHOTS = snapshot_io.snapshot_dirs()

pytestmark = pytest.mark.skipif(not SNAPSHOTS, reason="no recorded snapshots")


class _LegacyMatchupModel(MatchupModel):
    def apply_factors(self, players, schedule, as_of):
        season, week = divmod(as_of, 100)
        week_sched = schedule[
            (schedule["season"] == season) & (schedule["week"] == week)
        ][["team", "opp_team", "implied_total", "opp_implied_total"]]
        players = players.drop(
            columns=["opp_team", "implied_total", "opp_implied_total"],
            errors="ignore",
        )
        out = players.merge(
            week_sched.rename(columns={"team": "current_team"}),
            on="current_team",
            how="left",
        )
        out["matchup_factor"] = [
            self.factor(
                position=row["position"],
                team_implied_total=row.get("implied_total") or self._implied_total_mean,
                opp_implied_total=row.get("opp_implied_total") or self._implied_total_mean,
                opp_team=row.get("opp_team") or "",
                string=row.get("string", 1.0) or 1.0,
            )
            if pd.notna(row.get("implied_total"))
            else 1.0
            for _, row in out.iterrows()
        ]
        return out

    def _z_allowed(self, opp_team, position):
        if self._allowed_table is None or position not in self._allowed_per_pos_mean:
            return 0.0
        match = self._allowed_table[
            (self._allowed_table["opponent"] == opp_team)
            & (self._allowed_table["position"] == position)
        ]
        if match.empty:
            return 0.0
        allowed = float(match.iloc[0]["allowed_per_game"])
        return (allowed - self._allowed_per_pos_mean[position]) / self._allowed_per_pos_std[position]


def test_factors_match_the_original_for_every_week(replay_league):
    new = replay_league.matchup_model
    old = _LegacyMatchupModel()
    old.__dict__.update(new.__dict__)
    checked = 0
    for week in range(1, 19):
        as_of = replay_league.season * 100 + week
        got = new.apply_factors(replay_league.players, replay_league.nfl_schedule, as_of)
        want = old.apply_factors(replay_league.players, replay_league.nfl_schedule, as_of)
        pd.testing.assert_frame_equal(got, want, check_exact=True)
        checked += (got.matchup_factor != 1.0).sum()
    assert checked > 1000  # real, non-neutral factors were compared


def test_factors_vary_so_the_comparison_is_meaningful(replay_league):
    as_of = replay_league.season * 100 + replay_league.week
    out = replay_league.matchup_model.apply_factors(replay_league.players, replay_league.nfl_schedule, as_of)
    assert out.matchup_factor.nunique() > 20
