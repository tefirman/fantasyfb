"""
List every NFL fantasy league/team Yahoo has on record for the authenticated
account, across all seasons, with a chain_id linking each league to its
prior/future-season renewals (i.e. the "same" league year over year). Also
lists every manager who ever played in a given league chain (defaults to the
"Mariners Fans Anonymous" chain, 2003-present), builds head-to-head records
and scoring records from 2003-present, and exports both as JSON for the
league website's Managers page
(https://github.com/tefirman/mariners-fans-anonymous).

Some leagues/managers can't be identified from the Yahoo API alone (privacy
settings hide some nicknames, and pre-2010 seasons lack the renewal metadata
used to auto-chain leagues year to year) -- MANUAL_CHAIN_OVERRIDES,
MANUAL_MANAGER_OVERRIDES, EXTRA_LEAGUES, and DISPLAY_NAMES near the top of
this file record what's been manually confirmed so far. Any manager missing
from DISPLAY_NAMES (still-hidden teams, or names like Alex/Rich/Joel/Sam/
Warren without a confirmed full name yet) is excluded from the exported
records rather than shown under a bare nickname. Update them as more
managers get identified.

Run from the fantasyfb repo root:

    uv run python scripts/list_all_leagues.py

Outputs (gitignored -- contain full names/records for a private league):
    notes/head_to_head_2003plus.json
    notes/scoring_records_2003plus.json
"""

import json

import pandas as pd
import yahoo_fantasy_api as yfa

from fantasyfb.data.yahoo_client import YahooFantasyClient

# Yahoo's renew/renewed settings are blank before 2010, so the "Mariners
# Fans Anonymous" lineage can't be auto-chained that far back. Manually
# confirmed links, mapping each early league_id to its chain root
# (242.l.53993, the 2010 "Between Kyle's Cheeks" season).
MANUAL_CHAIN_OVERRIDES = {
    "79.l.127434": "242.l.53993",  # 2003
    "101.l.77574": "242.l.53993",  # 2004
    "124.l.27721": "242.l.53993",  # 2005
    "153.l.27263": "242.l.53993",  # 2006 ("Cougar Fans Still Suck")
    "175.l.111993": "242.l.53993",  # 2007
    "199.l.39983": "242.l.53993",  # 2008
    "222.l.42158": "242.l.53993",  # 2009 (sat out, league confirmed manually)
}

# Leagues the Yahoo teams-query can't discover because you had no team that
# season (e.g. you sat out), added manually via the league's own settings page.
EXTRA_LEAGUES = [
    # (sport, season, league_id, team_name)
    ("Football", "2009", "222.l.42158", None),  # sat out; league confirmed via settings page
]

# Yahoo hides some managers' nicknames ("--hidden--"). Where the team name
# gives it away (e.g. reused in later, unhidden seasons), manually identified
# below and keyed on (league_id, manager_id) so only that exact team is patched.
MANUAL_MANAGER_OVERRIDES = {
    ("348.l.199047", "12"): "David",  # 2015 "All About the D" -- same team name David used 2016+
    ("222.l.42158", "8"): "AJ",       # 2009 "Wankstas"
    ("222.l.42158", "5"): "Aaron",    # 2009 "69ers"
    ("222.l.42158", "3"): "Drew",     # 2009 "The Sofa Kings"
    ("222.l.42158", "4"): "Trevor",   # 2009 "Crotch de Fuego"
    ("222.l.42158", "6"): "Sam",      # 2009 "Uni-Browed Commandos"
    ("79.l.127434", "2"): "Trevor",   # 2003 "Zoptoe"
    ("79.l.127434", "10"): "Rich",    # 2003 "Eagles"
    ("101.l.77574", "1"): "Trevor",   # 2004 "INVALID"
    ("101.l.77574", "9"): "Rich",     # 2004 "Wolves"
    ("124.l.27721", "3"): "Trevor",   # 2005 "T.B.H.S Crusaders"
    ("153.l.27263", "10"): "Kyle Stokes",  # 2006 "JoshBrown is my hero"
    ("153.l.27263", "2"): "Trevor",   # 2006 "Team Bitter Sweet"
    ("79.l.127434", "3"): "Sam",      # 2003 "Sammys Little Heros"
    ("79.l.127434", "8"): "Alex",     # 2003 "Mustangs"
    ("101.l.77574", "10"): "Joel",    # 2004 "big headed calvery"
    ("124.l.27721", "9"): "Joel",     # 2005 "Big Headed Cavelry"
    ("222.l.42158", "10"): "Tyler T", # 2009 "Chassidy Belt"
    ("222.l.42158", "1"): "Marc G",   # 2009 "Coming from Behind"
    ("222.l.42158", "7"): "Kyle Stokes",  # 2009 "Fuck FantasyFootball"
    ("222.l.42158", "2"): "Connor",   # 2009 "Short Bus All-stars"
    # Tentative: fits Luke's known gap (only missing year in his 2010+ span)
    # and "Rookie of the year" is a plausible name for an actual rookie
    # manager's first season -- not confirmed like the others above.
    ("222.l.42158", "9"): "LK",       # 2009 "Rookie of the year"
}

# Full names for the league website (mariners-fans-anonymous), taken from
# docs/champions.md and docs/managers.md. Only covers the current 12-manager
# roster -- Alex/Rich/Joel/Sam/Warren don't have confirmed full names yet and
# aren't part of that roster anyway, so their games are excluded from every
# export below (win_pct comparisons stay fair; no manager is shown under a
# bare nickname on the site).
DISPLAY_NAMES = {
    "AJ": "AJ Fraiman",
    "Aaron": "Aaron Many",
    "Connor": "Connor Parish",
    "David": "David Dehart",
    "Drew": "Drew Sutton",
    "Kyle Stokes": "Kyle Stokes",
    "LK": "Luke Kartes",
    "Mac": "Mac Brooks",
    "Marc G": "Marc Gordon",
    "Taylor": "Taylor Firman",
    "Trevor": "Trevor Wood",
    "Tyler T": "Tyler Teton",
}


def main():
    client = YahooFantasyClient()
    client.gm = yfa.Game(client.oauth, "nfl")

    profile = client.gm.yhandler.get_teams_raw()["fantasy_content"]
    games = profile["users"]["0"]["user"][1]["games"]

    rows = []
    for ind in range(games["count"]):
        game = games[str(ind)]["game"]
        if isinstance(game, dict):
            continue
        sport = game[0]["name"]
        season = game[0]["season"]
        teams = game[1]["teams"]
        for t_ind in range(teams["count"]):
            team = teams[str(t_ind)]["team"][0]
            name = [val["name"] for val in team if "name" in val][0]
            team_key = [val["team_key"] for val in team if "team_key" in val][0]
            league_id = ".".join(team_key.split(".")[:3])
            rows.append((sport, season, league_id, name))

    rows.extend(EXTRA_LEAGUES)

    df = pd.DataFrame(rows, columns=["sport", "season", "league_id", "team_name"])
    df = df[df["sport"] == "Football"].reset_index(drop=True)

    # League name and prior-season link ("renew") aren't in the teams
    # payload, so look them up per league via league settings.
    league_names = {}
    renews_from = {}
    for league_id in df["league_id"].unique():
        settings = client.gm.to_league(league_id).settings()
        league_names[league_id] = settings["name"]
        renew = settings.get("renew")
        renews_from[league_id] = renew.replace("_", ".l.") if renew else None

    # Chain id: follow "renew" pointers back to each lineage's earliest
    # league_id, so every season of the "same" league shares one chain_id.
    def root(league_id):
        seen = set()
        while renews_from.get(league_id) and league_id not in seen:
            seen.add(league_id)
            league_id = renews_from[league_id]
        return league_id

    df["league_name"] = df["league_id"].map(league_names)
    df["chain_id"] = df["league_id"].map(root)
    df["chain_id"] = df["chain_id"].replace(MANUAL_CHAIN_OVERRIDES)
    df = df[["sport", "season", "chain_id", "league_id", "league_name", "team_name"]]
    df = df.sort_values(["chain_id", "season"], ascending=[True, False]).reset_index(drop=True)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", None)
    print(df)
    return client, df


def team_manager(league_id: str, team: dict) -> dict | None:
    """Resolve a team's primary manager, applying the same hidden/override
    logic used everywhere else -- or None if the team has no primary manager
    (shouldn't happen, but keeps callers honest).
    """
    managers = [m["manager"] for m in team.get("managers", [])]

    # Drop co-managers when the team also has a primary (non-comanager)
    # manager -- we only want the primary manager per team, whether or
    # not the co-manager's nickname happens to be visible.
    primary = [m for m in managers if not m.get("is_comanager")]
    if primary:
        managers = primary
    if not managers:
        return None

    m = managers[0]
    nickname = m["nickname"]
    # Yahoo's early (2003/2004-era) API defaults unclaimed team slots to
    # display the commissioner's own nickname instead of hiding them --
    # only trust it when it's actually your own login, otherwise treat it
    # as an unidentified manager.
    if nickname == "Taylor" and not m.get("is_current_login"):
        nickname = "--hidden--"
    nickname = MANUAL_MANAGER_OVERRIDES.get((league_id, m["manager_id"]), nickname)
    return {"manager_id": m["manager_id"], "nickname": nickname}


def chain_managers(client: YahooFantasyClient, df: pd.DataFrame, chain_id: str) -> pd.DataFrame:
    """List every manager who ever had a team in the given league chain."""
    chain = df[df["chain_id"] == chain_id]

    rows = []
    for _, row in chain.iterrows():
        lg = client.gm.to_league(row["league_id"])
        for team in lg.teams().values():
            manager = team_manager(row["league_id"], team)
            rows.append((row["season"], manager["manager_id"], manager["nickname"], team.get("name")))

    managers_df = pd.DataFrame(rows, columns=["season", "manager_id", "manager", "team_name"])
    return managers_df.sort_values(["manager", "season"]).reset_index(drop=True)


def head_to_head(client: YahooFantasyClient, df: pd.DataFrame, chain_id: str, min_season: str) -> pd.DataFrame:
    """Every regular-season matchup in the chain from min_season onward, as
    one row per matchup with both sides' manager, the winner, and each side's
    score -- including matchups where one or both managers are still
    unidentified ("--hidden--").

    This is intentionally unfiltered: a known manager's win or loss still
    counts toward their real career record even when their opponent that
    week isn't identified yet (dropping it would silently understate both
    their win/loss totals and, if summed by season, their season point
    total). Consumers that need *both* sides known -- the heatmap grid and
    head_to_head_win_pct -- filter for that themselves; consumers that only
    care about one manager's own result (career record, scoring records)
    should just filter out "--hidden--" on the side(s) they read.
    """
    chain = df[(df["chain_id"] == chain_id) & (df["season"].astype(int) >= int(min_season))]

    rows = []
    for _, row in chain.iterrows():
        lg = client.gm.to_league(row["league_id"])
        settings = lg.settings()
        playoff_start_week = int(settings["playoff_start_week"])
        weeks = ",".join(str(w) for w in range(1, playoff_start_week))

        raw = lg.yhandler.get_scoreboard_raw(row["league_id"], week=weeks)
        scoreboard = raw["fantasy_content"]["league"][1]["scoreboard"]
        for week_key, week_block in scoreboard.items():
            if week_key == "week":
                continue
            for m_key, m_block in week_block["matchups"].items():
                if m_key == "count":
                    continue
                matchup = m_block["matchup"]
                if matchup.get("is_tied") == 1 or not matchup.get("winner_team_key"):
                    continue

                teams = matchup["0"]["teams"]
                team_a, team_a_stats = teams["0"]["team"][0], teams["0"]["team"][1]
                team_b, team_b_stats = teams["1"]["team"][0], teams["1"]["team"][1]
                key_a = [v["team_key"] for v in team_a if "team_key" in v][0]
                mgr_a = team_manager(row["league_id"], {"managers": [v["managers"][0] for v in team_a if "managers" in v]})
                mgr_b = team_manager(row["league_id"], {"managers": [v["managers"][0] for v in team_b if "managers" in v]})
                points_a = float(team_a_stats["team_points"]["total"])
                points_b = float(team_b_stats["team_points"]["total"])

                winner = mgr_a["nickname"] if matchup["winner_team_key"] == key_a else mgr_b["nickname"]
                loser = mgr_b["nickname"] if winner == mgr_a["nickname"] else mgr_a["nickname"]
                winner_points = points_a if winner == mgr_a["nickname"] else points_b
                loser_points = points_b if winner == mgr_a["nickname"] else points_a
                rows.append((
                    row["season"], matchup["week"], winner, loser, winner_points, loser_points
                ))

    return pd.DataFrame(
        rows, columns=["season", "week", "winner", "loser", "winner_points", "loser_points"]
    )


def head_to_head_win_pct(h2h_df: pd.DataFrame) -> pd.DataFrame:
    """Manager x manager grid of win pct (row manager's win pct vs column
    manager). Only counts matchups where both sides are known -- a cell needs
    both a row-manager and a column-manager identity to mean anything.
    """
    known = h2h_df[(h2h_df["winner"] != "--hidden--") & (h2h_df["loser"] != "--hidden--")]
    managers = sorted(set(known["winner"]) | set(known["loser"]))
    grid = pd.DataFrame(index=managers, columns=managers, dtype=float)

    for row_mgr in managers:
        for col_mgr in managers:
            if row_mgr == col_mgr:
                continue
            wins = ((known["winner"] == row_mgr) & (known["loser"] == col_mgr)).sum()
            losses = ((known["winner"] == col_mgr) & (known["loser"] == row_mgr)).sum()
            total = wins + losses
            if total:
                grid.loc[row_mgr, col_mgr] = round(100 * wins / total, 1)

    return grid


def games_long(h2h_df: pd.DataFrame) -> pd.DataFrame:
    """One row per team-game (each matchup contributes two rows) for every
    *known* manager, keeping their own score regardless of whether that
    week's opponent is identified -- used for single-game and season-total
    scoring records, which only depend on one side's score.

    Deliberately does not require the opponent to be known: dropping a
    manager's game just because their opponent that week is still hidden
    would silently understate their season total (e.g. a manager who faced
    2 hidden-team opponents in an otherwise-full 14-game season would only
    get 12 games counted, making a normal season look like a scoring low).
    """
    winners = h2h_df.rename(columns={"winner": "manager", "winner_points": "points"})[
        ["season", "week", "manager", "points"]
    ]
    losers = h2h_df.rename(columns={"loser": "manager", "loser_points": "points"})[
        ["season", "week", "manager", "points"]
    ]
    games = pd.concat([winners, losers], ignore_index=True)
    return games[games["manager"] != "--hidden--"].reset_index(drop=True)


def scoring_records(h2h_df: pd.DataFrame, top_n: int = 5) -> dict:
    """League scoring records: single-game highs/lows, season-total
    highs/lows, biggest blowouts, and closest finishes.

    Single-game/season-total records only need one side's score, so they're
    built from every known manager's games (see games_long). Blowouts and
    closest finishes are inherently a comparison between two scores, so they
    need both sides known and are filtered down separately.
    """
    games = games_long(h2h_df)

    single_game_high = games.nlargest(top_n, "points")
    single_game_low = games.nsmallest(top_n, "points")

    season_totals = games.groupby(["manager", "season"])["points"].sum().reset_index()
    season_high = season_totals.nlargest(top_n, "points")
    season_low = season_totals.nsmallest(top_n, "points")

    known = h2h_df[(h2h_df["winner"] != "--hidden--") & (h2h_df["loser"] != "--hidden--")]
    margins = known.copy()
    margins["margin"] = margins["winner_points"] - margins["loser_points"]
    biggest_blowouts = margins.nlargest(top_n, "margin")
    closest_games = margins.nsmallest(top_n, "margin")

    return {
        "single_game_high": single_game_high,
        "single_game_low": single_game_low,
        "season_high": season_high,
        "season_low": season_low,
        "biggest_blowouts": biggest_blowouts,
        "closest_games": closest_games,
    }


def manager_seasons(managers_df: pd.DataFrame) -> pd.DataFrame:
    """One row per manager, with the list of seasons they played."""
    summary = (
        managers_df.groupby("manager")["season"]
        .apply(lambda s: ", ".join(sorted(s.unique(), key=int)))
        .reset_index()
        .rename(columns={"season": "seasons_played"})
    )
    return summary.sort_values("manager").reset_index(drop=True)


if __name__ == "__main__":
    yahoo_client, leagues_df = main()

    MARINERS_CHAIN_ID = "242.l.53993"
    managers_df = chain_managers(yahoo_client, leagues_df, MARINERS_CHAIN_ID)

    print("\nSeason-by-season manager/team breakdown:")
    print(managers_df.sort_values(["season", "manager"]).to_string(index=False))

    print("\nManagers who have played in the Mariners Fans Anonymous chain, with seasons played:")
    print(manager_seasons(managers_df).to_string(index=False))

    print("\nManager count per season (sanity check -- should match league size each year):")
    print(managers_df.groupby("season").size().to_string())

    print("\nBuilding head-to-head records (2003-present, regular season only)...")
    h2h_df = head_to_head(yahoo_client, leagues_df, MARINERS_CHAIN_ID, min_season="2003")

    print("\nCareer regular-season record, 2003-present:")
    wins = h2h_df["winner"].value_counts()
    losses = h2h_df["loser"].value_counts()
    career = pd.DataFrame({"wins": wins, "losses": losses}).fillna(0).astype(int)
    career["win_pct"] = (100 * career["wins"] / (career["wins"] + career["losses"])).round(1)
    print(career.sort_values("win_pct", ascending=False).to_string())

    print("\nHead-to-head win pct (row manager's win pct vs column manager), 2003-present:")
    print(head_to_head_win_pct(h2h_df).to_string())

    # Every export below sticks to the current, fully-identified roster.
    # Managers without a confirmed full name (still-hidden teams, plus
    # non-roster names like Alex/Rich/Joel/Sam/Warren) are treated exactly
    # like "--hidden--" everywhere downstream -- games_long/scoring_records
    # still credit the *known* side of such a matchup (so e.g. Marc G's
    # score against a non-roster opponent still counts toward his season
    # total), while the win/loss heatmap (which needs both sides on the
    # roster) is built from a separate, stricter view below.
    roster_h2h_df = h2h_df.copy()
    roster_h2h_df.loc[~roster_h2h_df["winner"].isin(DISPLAY_NAMES), "winner"] = "--hidden--"
    roster_h2h_df.loc[~roster_h2h_df["loser"].isin(DISPLAY_NAMES), "loser"] = "--hidden--"

    known_h2h_df = roster_h2h_df[
        (roster_h2h_df["winner"] != "--hidden--") & (roster_h2h_df["loser"] != "--hidden--")
    ]

    # Export for the heatmap artifact: career record + per-pair win/loss counts.
    managers_sorted = [
        m for m in career.sort_values("win_pct", ascending=False).index.tolist()
        if m in DISPLAY_NAMES
    ]
    cells = []
    for row_mgr in managers_sorted:
        for col_mgr in managers_sorted:
            if row_mgr == col_mgr:
                continue
            wins = int(((known_h2h_df["winner"] == row_mgr) & (known_h2h_df["loser"] == col_mgr)).sum())
            losses = int(((known_h2h_df["winner"] == col_mgr) & (known_h2h_df["loser"] == row_mgr)).sum())
            if wins + losses:
                cells.append({
                    "row": DISPLAY_NAMES[row_mgr], "col": DISPLAY_NAMES[col_mgr],
                    "wins": wins, "losses": losses,
                })

    export = {
        "managers": [DISPLAY_NAMES[m] for m in managers_sorted],
        "career": [
            {"manager": DISPLAY_NAMES[m], "wins": int(career.loc[m, "wins"]), "losses": int(career.loc[m, "losses"]),
             "win_pct": float(career.loc[m, "win_pct"])}
            for m in managers_sorted
        ],
        "cells": cells,
    }
    with open("notes/head_to_head_2003plus.json", "w") as f:
        json.dump(export, f, indent=2)
    print("\nExported notes/head_to_head_2003plus.json for the heatmap artifact.")

    print("\nScoring records, 2003-present (regular season only):")
    # Pass roster_h2h_df (not known_h2h_df) -- single-game/season-total
    # records only need one side to be a roster manager (see games_long), so
    # requiring "both sides known/roster" here would silently understate a
    # manager's season total whenever an opponent that year is still hidden
    # or isn't on the current roster, and could let a non-roster manager's
    # score bump a real roster manager out of the top N entirely.
    records = scoring_records(roster_h2h_df)
    for label, rec_df in records.items():
        print(f"\n{label}:")
        print(rec_df.to_string(index=False))

    def record_rows(rec_df: pd.DataFrame, kind: str) -> list[dict]:
        # records was built from roster_h2h_df, which already collapses any
        # non-roster manager to "--hidden--" (dropped upstream), so every row
        # here should have a DISPLAY_NAMES entry -- these checks are just a
        # defensive backstop.
        out = []
        if kind == "single_game":
            for _, r in rec_df.iterrows():
                if r["manager"] not in DISPLAY_NAMES:
                    continue
                out.append({"manager": DISPLAY_NAMES[r["manager"]], "season": r["season"], "week": r["week"], "points": round(r["points"], 2)})
        elif kind == "season_total":
            for _, r in rec_df.iterrows():
                if r["manager"] not in DISPLAY_NAMES:
                    continue
                out.append({"manager": DISPLAY_NAMES[r["manager"]], "season": r["season"], "points": round(r["points"], 2)})
        elif kind == "matchup":
            for _, r in rec_df.iterrows():
                if r["winner"] not in DISPLAY_NAMES or r["loser"] not in DISPLAY_NAMES:
                    continue
                out.append({
                    "season": r["season"], "week": r["week"],
                    "winner": DISPLAY_NAMES[r["winner"]], "winner_points": round(r["winner_points"], 2),
                    "loser": DISPLAY_NAMES[r["loser"]], "loser_points": round(r["loser_points"], 2),
                    "margin": round(r["margin"], 2),
                })
        return out

    records_export = {
        "single_game_high": record_rows(records["single_game_high"], "single_game"),
        "single_game_low": record_rows(records["single_game_low"], "single_game"),
        "season_high": record_rows(records["season_high"], "season_total"),
        "season_low": record_rows(records["season_low"], "season_total"),
        "biggest_blowouts": record_rows(records["biggest_blowouts"], "matchup"),
        "closest_games": record_rows(records["closest_games"], "matchup"),
    }
    with open("notes/scoring_records_2003plus.json", "w") as f:
        json.dump(records_export, f, indent=2)
    print("\nExported notes/scoring_records_2003plus.json.")

    print("\nStill-unidentified teams (season, team name) -- for tracking down real managers:")
    hidden = managers_df[managers_df["manager"] == "--hidden--"][["season", "team_name"]]
    hidden = hidden.sort_values(["season", "team_name"]).reset_index(drop=True)
    print(hidden.to_string(index=False))
