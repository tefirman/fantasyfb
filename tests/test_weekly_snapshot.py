"""End-to-end regression test of the weekly ``fantasyfb`` run.

Replays each recorded snapshot under tests/snapshots/ (see
tests/snapshot_io.py) through the real pipeline -- League construction,
projections, lineups, live-week actuals, season sims, adds/drops, Excel
export -- offline, with the clock frozen at record time, and checks
invariants any correct run must satisfy regardless of the exact numbers.

These target the class of bug recent releases kept finding on game day
(#78, #80, #81, #86, #89): the pipeline runs without error but quietly
produces a duplicated player, an unfilled or double-counted lineup, a
finished game still carrying projection variance, or probabilities that
don't add up.

A snapshot pins the *inputs*, not the outputs, so these checks survive
model changes. If the pipeline starts making a provider/client call the
snapshot never saw, replay fails with SnapshotMiss -- re-record with
scripts/record_snapshot.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import snapshot_io

SNAPSHOTS = snapshot_io.snapshot_dirs()

pytestmark = pytest.mark.skipif(not SNAPSHOTS, reason="no recorded snapshots")


@pytest.fixture(scope="module", params=SNAPSHOTS, ids=[p.name for p in SNAPSHOTS])
def replay(request, tmp_path_factory):
    snapshot_dir: Path = request.param
    meta = snapshot_io.load_meta(snapshot_dir)
    store = snapshot_io.SnapshotStore.load(snapshot_dir)
    with snapshot_io.frozen_environment(snapshot_dir, meta["as_of"], offline=True):
        league = snapshot_io.build_league(
            meta,
            snapshot_io.ReplayProxy(store, "provider"),
            snapshot_io.ReplayProxy(store, "client"),
        )
        out = snapshot_io.run_weekly(league, tmp_path_factory.mktemp(snapshot_dir.name))
    out["league"] = league
    out["meta"] = meta
    return out


def _starting_slots(league) -> int:
    spots = league.roster_spots
    return int(spots.loc[~spots.position.isin(["BN", "IR"]), "count"].sum())


def _real(players: pd.DataFrame) -> pd.DataFrame:
    """Drop the synthetic Average_* league-baseline rows get_rates adds."""
    return players[~players.player_id_sr.astype(str).str.startswith("avg_")]


class TestReplayMatchesRecording:
    def test_week_and_clock(self, replay):
        league, meta = replay["league"], replay["meta"]
        assert league.week == meta["week"]
        assert league.current_week == meta["current_week"]
        assert league.season == meta["season"]


class TestPlayers:
    def test_no_duplicate_rostered_players(self, replay):
        # #80: depth-chart fan-out duplicated rows for players with a
        # secondary (KR/PR) role, each able to take a lineup slot.
        rostered = _real(replay["players"]).dropna(subset=["fantasy_team"])
        dupes = rostered[rostered.duplicated("player_id_sr", keep=False)]
        assert dupes.empty, dupes[["name", "position", "fantasy_team"]].to_string()

    def test_no_duplicate_players_overall(self, replay):
        players = _real(replay["players"]).dropna(subset=["player_id_sr"])
        dupes = players[players.duplicated("player_id_sr", keep=False)]
        assert dupes.empty, dupes[["name", "position", "current_team"]].to_string()

    def test_projections_are_finite_and_plausible(self, replay):
        rostered = _real(replay["players"]).dropna(subset=["fantasy_team"])
        assert np.isfinite(rostered.points_avg).all()
        assert np.isfinite(rostered.points_stdev).all()
        assert (rostered.points_stdev >= 0).all()
        assert rostered.points_avg.between(-10, 60).all(), rostered.loc[
            ~rostered.points_avg.between(-10, 60), ["name", "position", "points_avg"]
        ].to_string()

    def test_top_projected_players_are_real_starters(self, replay):
        # #78: a string penalty that crushed real WR2/RB2/TE2 starters.
        # Every position's top five should be projected well above zero.
        players = _real(replay["players"])
        for pos in ["QB", "RB", "WR", "TE"]:
            top = players[players.position == pos].nlargest(5, "points_avg")
            assert (top.points_avg > 5).all(), f"{pos}:\n{top[['name', 'points_avg']]}"

    def test_war_computed_for_rostered(self, replay):
        rostered = _real(replay["players"]).dropna(subset=["fantasy_team"])
        assert rostered.WAR.notna().all()


class TestLineups:
    def test_every_team_fills_its_starting_lineup(self, replay):
        league, players = replay["league"], replay["players"]
        starters = players[players.starter & players.fantasy_team.notna()]
        counts = starters.groupby("fantasy_team").size()
        slots = _starting_slots(league)
        assert set(counts.index) == {t["name"] for t in league.teams}
        assert (counts == slots).all(), counts[counts != slots].to_string()

    def test_starters_are_rostered_and_unique(self, replay):
        starters = replay["players"][replay["players"].starter]
        assert starters.fantasy_team.notna().all()
        assert not starters.player_id_sr.duplicated().any()

    def test_position_counts_respect_roster_shape(self, replay):
        league = replay["league"]
        players = replay["players"]
        starters = players[players.starter & players.fantasy_team.notna()]
        spots = league.roster_spots.set_index("position")["count"]
        flex = {"W/T": {"WR", "TE"}, "W/R/T": {"WR", "RB", "TE"}, "Q/W/R/T": {"QB", "WR", "RB", "TE"}}
        for team, group in starters.groupby("fantasy_team"):
            by_pos = group.position.value_counts()
            for pos in ["QB", "RB", "WR", "TE", "K", "DEF"]:
                base = int(spots.get(pos, 0))
                extra = sum(int(spots.get(f, 0)) for f, elig in flex.items() if pos in elig)
                assert base <= by_pos.get(pos, 0) <= base + extra, (team, pos, by_pos.to_dict())


class TestLiveWeek:
    def test_snapshot_is_mid_slate(self, replay):
        # Guards the fixture itself: the live-week checks below are only
        # meaningful if some of this week's games are final and some not.
        league = replay["league"]
        done = set(replay["completed_teams"])
        week_teams = set(
            league.nfl_schedule.loc[
                (league.nfl_schedule.season == league.season)
                & (league.nfl_schedule.week == league.week),
                "team",
            ]
        )
        if not done or done == week_teams:
            pytest.skip("snapshot wasn't recorded mid-slate")

    def test_finished_game_starters_are_locked_to_actuals(self, replay):
        # #18 / #81: starters whose game is over carry their real points
        # with zero variance; everyone else keeps projection variance.
        live = replay["live_week_players"]
        done = replay["completed_teams"]
        actuals = replay["actuals"]
        if actuals.empty:
            pytest.skip("no finished games in this snapshot's live week")

        starters = live[live.starter & live.fantasy_team.notna()]
        locked = starters[starters.player_id_sr.isin(actuals.index)]
        assert not locked.empty
        assert (locked.points_stdev == 0).all()
        np.testing.assert_allclose(
            locked.points_avg.to_numpy(),
            locked.player_id_sr.map(actuals).to_numpy(),
        )
        pending = starters[~starters.current_team.isin(done)]
        assert (pending.points_stdev > 0).all(), pending[["name", "current_team"]].to_string()

    def test_players_already_played_are_not_benched(self, replay):
        # #81: a player whose game is final and who was in the real
        # lineup must count as a starter.
        players = replay["players"]
        done = replay["completed_teams"]
        if "selected_position" not in players.columns or not done:
            pytest.skip("no platform lineup or no finished games")
        played = players[
            players.current_team.isin(done)
            & players.fantasy_team.notna()
            & players.selected_position.notna()
            & ~players.selected_position.isin(["BN", "IR"])
        ]
        assert played.starter.all(), played.loc[~played.starter, ["name", "fantasy_team"]].to_string()


class TestSeasonSims:
    def test_matchup_win_probabilities_sum_to_one(self, replay):
        schedule = replay["schedule_sim"]
        total = schedule.win_1 + schedule.win_2
        assert np.allclose(total, 1.0, atol=0.02), schedule[~np.isclose(total, 1.0, atol=0.02)]

    def test_standings_probabilities_are_consistent(self, replay):
        league, standings = replay["league"], replay["standings_sim"]
        n = len(league.teams)
        assert len(standings) == n
        assert standings.playoffs.sum() == pytest.approx(league.settings["num_playoff_teams"], abs=0.01)
        assert standings.winner.sum() == pytest.approx(1.0, abs=0.01)
        assert standings.earnings.sum() == pytest.approx(sum(snapshot_io.SNAPSHOT_PAYOUTS), rel=0.01)
        for col in ["playoffs", "playoff_bye", "winner"]:
            assert standings[col].between(0, 1).all()

    def test_total_wins_match_games_played(self, replay):
        league, standings = replay["league"], replay["standings_sim"]
        regular = league.schedule[league.schedule.week < league.settings["playoff_start_week"]]
        # Every regular-season matchup hands out exactly one win (ties
        # split), so league-wide wins equal the number of matchups.
        assert standings.wins_avg.sum() == pytest.approx(len(regular), abs=0.05 * len(regular))

    def test_played_weeks_keep_real_results(self, replay):
        league, schedule = replay["league"], replay["schedule_sim"]
        played = league.schedule[league.schedule.week < league.week]
        if played.empty:
            pytest.skip("no completed fantasy weeks")
        merged = played.merge(schedule, on=["week", "team_1", "team_2"], suffixes=("", "_sim"))
        assert len(merged) == len(played)
        real_winner_1 = merged.score_1 > merged.score_2
        assert (merged.loc[real_winner_1, "win_1"] == 1).all()
        assert (merged.loc[~real_winner_1 & (merged.score_1 < merged.score_2), "win_2"] == 1).all()


class TestMovesAndExport:
    def test_adds_and_drops_produce_rows(self, replay):
        for key in ["adds", "drops"]:
            df = replay[key]
            assert isinstance(df, pd.DataFrame) and not df.empty, key

    def test_move_analysis_restores_rosters(self, replay):
        # possible_adds/drops temporarily reassign players in place;
        # every roster must be exactly as it was once they return.
        def owners(df):
            return _real(df).set_index("player_id_sr").fantasy_team.sort_index()

        pd.testing.assert_series_equal(
            owners(replay["players"]), owners(replay["players_after_moves"])
        )

    def test_excel_report_has_every_sheet(self, replay):
        sheets = pd.ExcelFile(replay["excel_file"]).sheet_names
        for sheet in ["Rosters", "Available", "Schedule", "Standings", "Adds", "Drops"]:
            assert sheet in sheets, sheets
