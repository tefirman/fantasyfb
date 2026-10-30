"""Build the SFB odds page: one self-contained HTML file.

    python app/sfb_site/build.py --odds sfb/odds.csv --cut-line sfb/cut_line.csv \\
        --leaderboard notes/SFB16Leaderboard.html --data sfb/data --out sfb/index.html

Inputs are the files written by ``sfb-field simulate`` (odds.csv, cut_line.csv),
the saved leaderboard page (for handles and team names to search by), and the
collected data directory (for the week the odds are through). The page needs no
server, so it can be opened from disk or hosted anywhere static.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fantasyfb.sfb.field import Rules
from fantasyfb.sfb.leagues import parse_leaderboard

TEMPLATE = Path(__file__).with_name("template.html")


def _label(name: str) -> str:
    return name.replace("_", " ").title().replace("Semi Finals", "Semi-Finals")


def page_data(odds: pd.DataFrame, cut_line: np.ndarray, names: pd.DataFrame, through_week: int,
              rules: Rules = Rules(), bin_width: int = 5) -> dict:
    """The JSON the page reads: a row per team, the cut-line histogram, and labels."""
    odds = odds.merge(
        names.loc[names.platform == "sleeper", ["league_id", "roster_id", "manager", "handle", "league_name"]],
        on=["league_id", "roster_id"], how="left",
    ).fillna({"manager": "", "handle": "", "league_name": ""})
    later = [f"reach_{name}" for name in rules.round_names[1:]]
    teams = [
        {"l": str(r.league_id), "i": int(r.roster_id), "t": r.team, "m": r.manager, "h": r.handle, "s": r.league_name,
         "q": round(float(r.qualify), 4), "r": [round(float(getattr(r, c)), 4) for c in later],
         "w": round(float(r.win), 4), "g": round(float(r.wins), 2), "p": round(float(r.avg_ppg), 2)}
        for r in odds.itertuples(index=False)
    ]
    cut = np.asarray(cut_line, dtype=float)
    cut = cut[~np.isnan(cut)]
    start = int(np.floor(cut.min() / bin_width) * bin_width)
    edges = np.arange(start, cut.max() + bin_width, bin_width)
    counts, _ = np.histogram(cut, bins=edges)
    p5, p50, p95 = np.percentile(cut, [5, 50, 95])
    rounds = [_label(n) for n in rules.round_names]
    return {
        "through_week": through_week,
        "sims": int(len(cut_line)),
        "teams_count": len(teams),
        "leagues_count": int(odds.league_id.nunique()),
        "reg_weeks": rules.regular_season_weeks,
        "cut": {"start": start, "width": bin_width, "counts": counts.tolist(), "total": int(len(cut)),
                "p5": round(float(p5), 1), "p50": round(float(p50), 1), "p95": round(float(p95), 1)},
        "round_labels": ["Make the playoffs"] + [f"Reach {r}" for r in rounds[1:]] + ["Win the title"],
        "teams": teams,
    }


def render(data: dict, title: str, rules: Rules = Rules(), generated: str = "") -> str:
    # Names are untrusted text inside a script block: keep "<" and line separators from ending it.
    blob = (json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            .replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    scale = data["teams_count"] / rules.field_teams
    sizes = [f"{round(n * scale):,}" for n in rules.round_starts[1:]]
    sizes = ", ".join(sizes[:-1]) + f", and {sizes[-1]}"
    page = TEMPLATE.read_text(encoding="utf-8")
    for key, value in {
        "__TITLE__": html.escape(title),
        "__QUOTA__": f"{round(rules.field_quota * scale):,}",
        "__TEAMS__": f"{data['teams_count']:,}",
        "__ROUND_SIZES__": sizes,
        "__GENERATED__": generated,
        "__DATA__": blob,
    }.items():
        page = page.replace(key, value)
    return page


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--odds", required=True, help="odds.csv from sfb-field simulate")
    parser.add_argument("--cut-line", required=True, help="cut_line.csv from sfb-field simulate")
    parser.add_argument("--leaderboard", required=True, help="saved SFB leaderboard page")
    parser.add_argument("--data", required=True, help="collected data directory (for the week)")
    parser.add_argument("--out", default="index.html")
    parser.add_argument("--title", default="Scott Fish Bowl playoff odds")
    args = parser.parse_args(argv)

    odds = pd.read_csv(args.odds, dtype={"league_id": str})
    cut = pd.read_csv(args.cut_line).cut_line.to_numpy()
    names = parse_leaderboard(Path(args.leaderboard).read_text(encoding="utf-8", errors="replace"))
    first_week = int(pd.read_parquet(Path(args.data) / "settings.parquet").first_week.min())
    data = page_data(odds, cut, names, through_week=first_week - 1)
    Path(args.out).write_text(render(data, args.title, generated=datetime.date.today().strftime("%B %-d, %Y")), encoding="utf-8")
    print(f"wrote {args.out} ({Path(args.out).stat().st_size / 1e6:.2f} MB, {len(data['teams'])} teams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
