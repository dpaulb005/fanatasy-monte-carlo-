"""Generate a self-contained HTML report of the simulation.

The page shows every player's season distribution and then, on expanding a row,
what each of his eighteen weeks looks like. The organising idea is that a Monte
Carlo run does not produce numbers, it produces *ranges*, so the range bar is
the primary mark at both scales -- season and week -- and the point estimate is
only the tick inside it.

Everything is embedded: the data is inlined as JSON and the styling and
behaviour are inlined too, so the file works from disk with no network.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Scoring
from .engine import STATS, SIDX

# Which underlying stats are worth showing per position, and how to label them.
STAT_VIEW = {
    "QB": [("pass_yds", "Pass yd", 0), ("pass_cmp", "Cmp", 1), ("pass_att", "Att", 1),
           ("pass_td", "Pass TD", 1), ("pass_int", "INT", 1),
           ("rush_att", "Car", 1), ("rush_yds", "Rush yd", 0), ("rush_td", "Rush TD", 1)],
    "RB": [("rush_att", "Car", 1), ("rush_yds", "Rush yd", 0), ("rush_td", "Rush TD", 2),
           ("targets", "Tgt", 1), ("rec", "Rec", 1), ("rec_yds", "Rec yd", 0),
           ("rec_td", "Rec TD", 2)],
    "WR": [("targets", "Tgt", 1), ("rec", "Rec", 1), ("rec_yds", "Rec yd", 0),
           ("rec_td", "Rec TD", 2), ("rush_att", "Car", 1), ("rush_yds", "Rush yd", 0)],
    "TE": [("targets", "Tgt", 1), ("rec", "Rec", 1), ("rec_yds", "Rec yd", 0),
           ("rec_td", "Rec TD", 2)],
}


def _payload(bundle, result, df: pd.DataFrame, scoring: Scoring,
             min_points: float = 8.0) -> dict:
    pt = bundle.player_table
    df = df.copy()
    df["gindex"] = df.index
    has_weekly = "weekly_fp" in result
    weeks = int(result["weekly_fp"].shape[0]) if has_weekly else 0
    wstats = result.get("weekly_stats")
    wfp = result.get("weekly_fp")
    wplayed = result.get("weekly_played")
    wopp = result.get("week_opponent", {})

    def r(x, nd=1):
        v = float(x)
        return round(v, nd) if np.isfinite(v) else 0.0

    players = []
    for _, row in df.sort_values("points", ascending=False).iterrows():
        if row.points < min_points:
            continue
        gi = int(row.gindex)
        pos = row.pos
        view = STAT_VIEW.get(pos, STAT_VIEW["WR"])

        wk = []
        if has_weekly:
            for w in range(weeks):
                opp = wopp.get(w, {}).get(row.team) or wopp.get(str(w), {}).get(row.team)
                if opp is None:
                    wk.append(None)          # bye week
                    continue
                wk.append([
                    opp,
                    r(wfp[w, 0, gi]),                       # mean fantasy points
                    r(wfp[w, 2, gi]), r(wfp[w, 4, gi]), r(wfp[w, 6, gi]),  # p10, median, p90
                    r(wplayed[w, gi], 2),                   # share of sims available
                    *[r(wstats[w, SIDX[k], gi], nd) for k, _, nd in view],
                ])

        players.append({
            "n": row.player, "p": pos, "t": row.team, "d": int(row.depth),
            "rk": int(row.overall_rank), "pr": int(row.pos_rank), "ti": int(row.tier),
            "pts": r(row.points, 0), "p10": r(row.p10, 0), "p25": r(row.p25, 0),
            "md": r(row["median"], 0), "p75": r(row.p75, 0), "p90": r(row.p90, 0),
            "sd": r(row.sd, 0), "ppg": r(row.ppg), "g": r(row.games),
            "bm": r(row.boom, 3), "bs": r(row.bust, 3), "vor": r(row.vor, 0),
            "rook": bool(row.rookie),
            "ss": [r(row[c], nd) for c, _, nd in _season_cols(view)],
            "wk": wk,
        })

    teams = []
    ct = bundle.coach_table.set_index("team")
    for t, pts in result["team_points"].items():
        wins = result["team_wins"][t]
        c = ct.loc[t] if t in ct.index else None
        teams.append({
            "t": t, "w": r(wins.mean()), "pg": r(pts.mean() / 17.0),
            "coach": str(c.coach) if c is not None else "",
            "proe": r(float(c.proe) * 100) if c is not None else 0.0,
            "pace": r(float(c.pace)) if c is not None else 0.0,
        })

    return {
        "meta": {
            "season": int(bundle.season), "sims": int(result["n_sims"]),
            "scoring": scoring.name, "weeks": weeks,
            "generated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "players": len(players),
        },
        "headers": {k: [lbl for _, lbl, _ in v] for k, v in STAT_VIEW.items()},
        "players": players,
        "teams": sorted(teams, key=lambda x: -x["w"]),
    }


def _season_cols(view):
    """Map engine stat keys to the season-summary column names in the frame."""
    lookup = {
        "pass_yds": "pass_yds", "pass_td": "pass_td", "pass_int": "ints",
        "pass_cmp": None, "pass_att": None,
        "rush_att": "carries", "rush_yds": "rush_yds", "rush_td": "rush_td",
        "targets": "targets", "rec": "rec", "rec_yds": "rec_yds", "rec_td": "rec_td",
    }
    out = []
    for key, label, nd in view:
        col = lookup.get(key)
        out.append((col if col else "points", label, nd))
    return out


def generate(bundle, result, df: pd.DataFrame, scoring: Scoring,
             out_path: Path) -> Path:
    data = _payload(bundle, result, df, scoring)
    html = _template().replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE_PATH = Path(__file__).with_name("report_template.html")


def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")
