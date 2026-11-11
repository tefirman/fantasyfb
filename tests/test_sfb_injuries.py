import pandas as pd
import pytest

from fantasyfb.sfb.injuries import rostered_counts, scan_injuries, validate_injured_list


def rosters(counts):
    """One row per (league, team) for each player, ``counts`` teams each."""
    rows = [(f"L{i}", "t", pid) for pid, n in counts.items() for i in range(n)]
    return pd.DataFrame(rows, columns=["league_id", "team", "player_id"])


PLAYERS = pd.DataFrame({
    "player_id": ["1", "2", "3", "4", "5"],
    "player_id_sr": ["g1", "g2", "g3", "g4", None],
    "name": ["Star", "Bench", "Listed", "Healed", "NoGsis"],
    "position": ["RB", "WR", "WR", "QB", "TE"],
    "status": ["Out", "Out", "Out", None, "Out"],
})
LISTED = pd.DataFrame({
    "player_id_sr": ["g3", "g4", "gone"], "name": ["Listed", "Healed", "Gone"],
    "position": ["WR", "QB", "RB"], "until": [12, 12, 12],
})


class TestScanInjuries:
    def scan(self, **kwargs):
        counts = {"1": 30, "2": 5, "3": 40, "4": 40, "5": 40}
        return scan_injuries(rosters(counts), PLAYERS, LISTED, 9, **kwargs)

    def test_new_injuries_are_widely_rostered_out_players_not_on_the_list(self):
        new, _ = self.scan()
        assert new.name.tolist() == ["Star"]  # Bench is under 20 teams, Listed is covered, NoGsis has no ID
        assert new.teams.tolist() == [30]

    def test_min_teams_sets_the_floor(self):
        new, _ = self.scan(min_teams=5)
        assert new.name.tolist() == ["Star", "Bench"]

    def test_a_list_row_that_ran_out_is_not_covering_the_player(self):
        stale = LISTED.assign(until=[8, 12, 12])
        new, _ = scan_injuries(rosters({"3": 40}), PLAYERS, stale, 9)
        assert new.name.tolist() == ["Listed"]

    def test_old_injuries_are_listed_players_who_no_longer_carry_a_designation(self):
        _, old = self.scan()
        assert old.name.tolist() == ["Healed"]  # Gone isn't in Sleeper's pool, so it is left alone

    def test_questionable_is_not_out(self):
        questionable = PLAYERS.assign(status=["Questionable"] * 5)
        new, _ = scan_injuries(rosters({"1": 30}), questionable, LISTED.iloc[0:0], 9)
        assert new.empty

    def test_a_stray_space_in_sleepers_id_does_not_hide_a_listed_player(self):
        spaced = PLAYERS.assign(player_id_sr=[" g1", " g2", " g3", " g4", None])
        new, old = scan_injuries(rosters({"1": 30, "3": 40, "4": 40}), spaced, LISTED, 9)
        assert new.name.tolist() == ["Star"]  # Listed is covered even though Sleeper's ID has a space
        assert new.player_id_sr.tolist() == ["g1"]  # and the ID written out is clean
        assert old.name.tolist() == ["Healed"]

    def test_a_team_rostering_a_player_twice_counts_once(self):
        doubled = pd.concat([rosters({"1": 3})] * 2)
        assert rostered_counts(doubled)["1"] == 3


class TestValidateInjuredList:
    def check(self, after, **kwargs):
        validate_injured_list(LISTED, after, ["g1", "g2", "g3", "g4"], **kwargs)

    def test_an_unchanged_list_passes(self):
        self.check(LISTED)

    def test_adding_a_known_player_passes(self):
        self.check(pd.concat([LISTED, pd.DataFrame([["g1", "Star", "RB", 10]], columns=LISTED.columns)]))

    @pytest.mark.parametrize("until", [0, 19, 9.5, None])
    def test_until_must_be_a_week(self, until):
        with pytest.raises(ValueError, match="whole week"):
            self.check(LISTED.assign(until=[until, 12, 12]))

    def test_schema_changes_are_rejected(self):
        with pytest.raises(ValueError, match="columns"):
            self.check(LISTED.rename(columns={"until": "week"}))

    def test_duplicates_and_unknown_players_are_rejected(self):
        extra = pd.DataFrame([["g3", "Listed", "WR", 12], ["zzz", "Nobody", "RB", 12]], columns=LISTED.columns)
        with pytest.raises(ValueError, match="duplicate.*not in Sleeper"):
            self.check(pd.concat([LISTED, extra]))

    def test_too_many_changes_are_rejected(self):
        with pytest.raises(ValueError, match="rows changed"):
            self.check(LISTED.assign(until=[13, 13, 13]), max_changes=2)
