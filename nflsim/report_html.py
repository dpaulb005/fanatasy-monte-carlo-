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
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import fantasy_points
from .config import League, Scoring
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


def _decision_metrics(bundle, result, scoring: Scoring, league: League) -> tuple[dict, np.ndarray]:
    """Joint-distribution draft metrics and per-simulation value.

    Replacement is recalculated inside every simulated season.  This matters
    for cross-position comparisons: a QB and RB should be compared by what
    each adds over the player freely available at his own position, not by raw
    fantasy points.
    """
    fp = fantasy_points(result["totals"], scoring)
    pt = bundle.player_table
    value = np.zeros_like(fp, dtype=float)
    metrics = {}
    replacement_ranks = league.replacement_ranks()

    for pos, labels in pt.groupby("pos").groups.items():
        idx = np.asarray(list(labels), dtype=int)
        sub = fp[:, idx]
        order = np.argsort(-sub, axis=1)
        ranks = np.empty_like(order)
        np.put_along_axis(
            ranks, order,
            np.broadcast_to(np.arange(sub.shape[1]), sub.shape), axis=1,
        )
        ranks += 1
        replacement_rank = min(replacement_ranks.get(pos, 24), sub.shape[1])
        replacement = np.take_along_axis(
            sub, order[:, replacement_rank - 1:replacement_rank], axis=1,
        )
        pos_value = sub - replacement
        value[:, idx] = pos_value
        for j, gi in enumerate(idx):
            r = ranks[:, j]
            metrics[int(gi)] = {
                "eq1": float((r == 1).mean()),
                "eq3": float((r <= 3).mean()),
                "start": float((r <= replacement_rank).mean()),
                "beat": float((pos_value[:, j] > 0).mean()),
                "v10": float(np.percentile(pos_value[:, j], 10)),
                "v90": float(np.percentile(pos_value[:, j], 90)),
            }
    return metrics, value


def _pairwise_value_probability(value: np.ndarray, indices: list[int]) -> list[list[float]]:
    """P(row has more season-specific replacement value than column)."""
    out = []
    for a in indices:
        row = []
        for b in indices:
            if a == b:
                row.append(0.5)
            else:
                av, bv = value[:, a], value[:, b]
                row.append(round(float((av > bv).mean() + 0.5 * (av == bv).mean()), 3))
        out.append(row)
    return out


def _payload(bundle, result, df: pd.DataFrame, scoring: Scoring,
             league: League | None = None, min_points: float = 8.0,
             lab_size: int = 80) -> dict:
    league = league or League()
    pt = bundle.player_table
    df = df.copy()
    df["gindex"] = df.index
    has_weekly = "weekly_fp" in result
    weeks = int(result["weekly_fp"].shape[0]) if has_weekly else 0
    wstats = result.get("weekly_stats")
    wfp = result.get("weekly_fp")
    wplayed = result.get("weekly_played")
    # Optional: result files written before weekly stat ranges existed have
    # only the means, and the report falls back to showing those.
    wsq = result.get("weekly_stat_q")
    wfpl = result.get("weekly_fp_live")
    wopp = result.get("week_opponent", {})

    def r(x, nd=1):
        v = float(x)
        return round(v, nd) if np.isfinite(v) else 0.0

    decision, decision_value = _decision_metrics(bundle, result, scoring, league)
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
                # Each stat is shipped as [p10, mean, p90] over the weeks he
                # played, not as a bare mean. A mean across ten thousand
                # universes puts a hundred-yard receiver at a hundred yards
                # every single week, which reads as a model that cannot produce
                # a thirty-yard game -- and it can, the mean was just hiding it.
                cells = []
                for k, _, nd in view:
                    m = r(wstats[w, SIDX[k], gi], nd)
                    if wsq is None:
                        cells.append(m)
                    else:
                        cells.append([r(wsq[w, 0, SIDX[k], gi], nd), m,
                                      r(wsq[w, 2, SIDX[k], gi], nd)])
                lo, hi = (r(wfpl[w, 0, gi]), r(wfpl[w, 1, gi])) if wfpl is not None \
                    else (r(wfp[w, 2, gi]), r(wfp[w, 6, gi]))
                wk.append([
                    opp,
                    r(wfp[w, 0, gi]),                       # mean fantasy points
                    lo, r(wfp[w, 4, gi]), hi,               # floor, median, ceiling
                    r(wplayed[w, gi], 2),                   # share of sims available
                    *cells,
                ])

        dm = decision[gi]
        players.append({
            "id": gi,
            "n": row.player, "p": pos, "t": row.team, "d": int(row.depth),
            "rk": int(row.overall_rank), "pr": int(row.pos_rank), "ti": int(row.tier),
            "pts": r(row.points, 0), "p10": r(row.p10, 0), "p25": r(row.p25, 0),
            "md": r(row["median"], 0), "p75": r(row.p75, 0), "p90": r(row.p90, 0),
            "sd": r(row.sd, 0), "ppg": r(row.ppg), "g": r(row.games),
            "bm": r(row.boom, 3), "bs": r(row.bust, 3), "vor": r(row.vor, 0),
            "eq1": r(dm["eq1"], 3), "eq3": r(dm["eq3"], 3),
            "start": r(dm["start"], 3), "beat": r(dm["beat"], 3),
            "v10": r(dm["v10"], 0), "v90": r(dm["v90"], 0),
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

    lab_players = sorted(range(len(players)), key=lambda i: players[i]["rk"])[:lab_size]
    lab_gi = [players[i]["id"] for i in lab_players]
    for lab_index, player_index in enumerate(lab_players):
        players[player_index]["di"] = lab_index
    for p in players:
        p.setdefault("di", -1)

    return {
        "meta": {
            "season": int(bundle.season), "sims": int(result["n_sims"]),
            "scoring": scoring.name, "weeks": weeks,
            "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "players": len(players),
        },
        "headers": {k: [lbl for _, lbl, _ in v] for k, v in STAT_VIEW.items()},
        "players": players,
        "teams": sorted(teams, key=lambda x: -x["w"]),
        "lab": {
            "player_indexes": lab_players,
            "win": _pairwise_value_probability(decision_value, lab_gi),
            "limit": 4,
        },
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
             out_path: Path, league: League | None = None) -> Path:
    data = _payload(bundle, result, df, scoring, league=league)
    html = _template().replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE_PATH = Path(__file__).with_name("report_template.html")


def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")
