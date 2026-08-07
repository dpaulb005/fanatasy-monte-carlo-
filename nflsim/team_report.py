"""Everything the simulation knows about one team.

The draft board answers "who should I take". This answers "what does the model
actually believe about this offence, and why" -- the fitted coaching identity
and team strength that drove the season, the usage shares each player was
given, the full simulated stat line, and the correlation structure between
teammates that only a play-by-play simulation produces.

The last of those is the part worth reading. A quarterback and his top receiver
come out positively correlated, two backs in the same committee negatively, and
nothing in the model was told to make that happen -- it falls out of having
simulated the same drives.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .analysis import fantasy_points
from .board import _console, _fmt
from .config import Scoring
from .engine import SIDX

try:
    from rich.table import Table
    from rich import box
    _RICH = True
except ImportError:                                   # pragma: no cover
    _RICH = False


def _table(con, title, cols, rows, note=None):
    if not _RICH:
        print(f"\n{title}")
        for r in rows:
            print("  " + "  ".join(str(x) for x in r))
        return
    t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold", title_style="bold")
    for c, j in cols:
        t.add_column(c, justify=j)
    for r in rows:
        t.add_row(*[str(x) for x in r])
    con.print(t)
    if note:
        con.print(f"[grey58]{note}[/]")


def report(bundle, result, scoring: Scoring, team: str, df: pd.DataFrame) -> None:
    con = _console()
    tm = bundle.teams.get(team)
    if tm is None:
        raise KeyError(f"unknown team {team!r}")

    pt = bundle.player_table
    sl = pt.loc[tm.gidx]
    fp = fantasy_points(result["totals"], scoring)
    tot = result["totals"]
    gp = result["games_played"]
    n_sims = result["n_sims"]

    wins = result["team_wins"][team]
    pts = result["team_points"][team]

    # ---- 1. team identity ----------------------------------------------
    ct = bundle.coach_table.set_index("team").loc[team]
    st = bundle.strength_table.set_index("team").loc[team] \
        if team in set(bundle.strength_table.team) else None
    rows = [
        ["projected wins", f"{wins.mean():.2f}", f"p10 {np.percentile(wins,10):.0f} · p90 {np.percentile(wins,90):.0f}"],
        ["points / game", f"{pts.mean()/17:.1f}", ""],
        ["head coach", str(ct.coach), "new staff" if ct.get("new") else ""],
        ["pass rate over expected", f"{ct.proe*100:+.1f}%", "run-leaning" if ct.proe < 0 else "pass-leaning"],
        ["neutral pace", f"{ct.pace:.1f}s/play", ""],
        ["4th-down aggression", f"{ct.go_oe*100:+.1f}%", "vs league baseline"],
        ["roster continuity", f"{ct.continuity*100:.0f}%", "of last year's snaps returning"],
    ]
    if st is not None:
        for label, key in [("offence: pass EPA/play", "off_pass_epa"),
                           ("offence: rush EPA/play", "off_rush_epa"),
                           ("defence: pass EPA/play allowed", "def_pass_epa"),
                           ("defence: rush EPA/play allowed", "def_rush_epa")]:
            v = float(st[key])
            good = (v > 0) if "offence" in label else (v < 0)
            rows.append([label, f"{v:+.3f}", "above average" if good else "below average"])
    _table(con, f"{team} · team identity as fitted",
           [("", "left"), ("value", "right"), ("", "left")], rows)

    # ---- 2. win distribution -------------------------------------------
    rows = []
    for k in range(int(wins.min()), int(wins.max()) + 1):
        share = float((wins == k).mean())
        if share < 0.002:
            continue
        rows.append([f"{k}", "█" * int(share * 170), f"{share*100:.1f}%"])
    _table(con, f"{team} · win total across {n_sims:,} simulated seasons",
           [("wins", "right"), ("", "left"), ("share", "right")], rows)

    # ---- 3. usage shares -----------------------------------------------
    rows = []
    order = np.argsort(-(tm.target_share + tm.rush_share))
    for i in order:
        if tm.target_share[i] < 0.005 and tm.rush_share[i] < 0.005 and sl.pos.values[i] != "QB":
            continue
        rows.append([
            sl.name.values[i], sl.pos.values[i], str(sl.depth_rank.values[i]),
            f"{tm.target_share[i]*100:.1f}%", f"{tm.rz_target_share[i]*100:.1f}%",
            f"{tm.gl_target_share[i]*100:.1f}%",
            f"{tm.rush_share[i]*100:.1f}%", f"{tm.gl_share[i]*100:.1f}%",
            f"{tm.adot[i]:.1f}" if sl.pos.values[i] != "QB" else f"{tm.qb_adot[i]:.1f}",
            f"{sl.conf.values[i]:.2f}",
        ])
    _table(con, f"{team} · usage shares the engine was given",
           [("Player", "left"), ("Pos", "center"), ("Dp", "center"),
            ("Tgt%", "right"), ("RZ tgt%", "right"), ("GL tgt%", "right"),
            ("Rush%", "right"), ("GL rush%", "right"), ("aDOT", "right"),
            ("conf", "right")],
           rows,
           note="RZ = inside the 20, GL = inside the 5. conf = weight placed on the "
                "player's own history vs the depth-chart baseline.")

    # ---- 4. full stat lines --------------------------------------------
    sub = df[df.team == team].sort_values("points", ascending=False)
    rows = []
    for _, r in sub.iterrows():
        if r.points < 5:
            continue
        rows.append([
            r.player, r.pos, f"{r.games:.1f}",
            _fmt(r.pass_yds, 0), _fmt(r.pass_td, 1), _fmt(r.ints, 1),
            _fmt(r.carries, 0), _fmt(r.rush_yds, 0), _fmt(r.rush_td, 1),
            _fmt(r.targets, 0), _fmt(r.rec, 0), _fmt(r.rec_yds, 0), _fmt(r.rec_td, 1),
            _fmt(r.points, 0), _fmt(r.ppg, 1),
        ])
    _table(con, f"{team} · projected statistics (mean of {n_sims:,} seasons)",
           [("Player", "left"), ("Pos", "center"), ("G", "right"),
            ("PaYd", "right"), ("PaTD", "right"), ("Int", "right"),
            ("Car", "right"), ("RuYd", "right"), ("RuTD", "right"),
            ("Tgt", "right"), ("Rec", "right"), ("ReYd", "right"), ("ReTD", "right"),
            ("Pts", "right"), ("PPG", "right")], rows)

    # ---- 5. distribution ------------------------------------------------
    rows = []
    for _, r in sub.iterrows():
        if r.points < 5:
            continue
        rows.append([
            r.player, r.pos,
            _fmt(r.p10, 0), _fmt(r.p25, 0), _fmt(r["median"], 0),
            _fmt(r.p75, 0), _fmt(r.p90, 0), _fmt(r.sd, 0),
            f"{r.boom*100:.0f}%", f"{r.bust*100:.0f}%",
            _fmt(r.vor, 0), str(int(r.pos_rank)), str(int(r.overall_rank)),
        ])
    _table(con, f"{team} · outcome distribution · {scoring.name}",
           [("Player", "left"), ("Pos", "center"),
            ("p10", "right"), ("p25", "right"), ("med", "right"),
            ("p75", "right"), ("p90", "right"), ("sd", "right"),
            ("Boom", "right"), ("Bust", "right"),
            ("VOR", "right"), ("PosRk", "right"), ("Ovr", "right")], rows,
           note="Percentiles are ordering information, not calibrated probabilities: "
                "the backtest showed p10-p90 covering ~68% of outcomes against a nominal 80%.")

    # ---- 6. correlation structure ---------------------------------------
    keep = [i for i in range(tm.n) if fp[:, tm.gidx[i]].mean() >= 40]
    keep = sorted(keep, key=lambda i: -fp[:, tm.gidx[i]].mean())[:8]
    if len(keep) >= 2:
        names = [sl.name.values[i] for i in keep]
        mat = np.corrcoef(np.stack([fp[:, tm.gidx[i]] for i in keep]))
        rows = []
        for a, i in enumerate(keep):
            cells = []
            for bi in range(len(keep)):
                v = mat[a, bi]
                if a == bi:
                    cells.append("[grey42]—[/]" if _RICH else "—")
                else:
                    colour = "green" if v > 0.05 else ("red" if v < -0.05 else "grey58")
                    cells.append(f"[{colour}]{v:+.2f}[/]" if _RICH else f"{v:+.2f}")
            rows.append([names[a][:18]] + cells)
        _table(con, f"{team} · teammate correlation in season fantasy points",
               [("", "left")] + [(n.split()[-1][:8], "right") for n in names], rows,
               note="Emergent, not imposed: nothing in the model was told that a passer "
                    "and his receivers rise together or that two backs split a workload. "
                    "It falls out of having simulated the same drives.")

    # ---- 7. availability -------------------------------------------------
    rows = []
    for i in np.argsort(-fp[:, tm.gidx].mean(axis=0))[:10]:
        gi = tm.gidx[i]
        g = gp[:, gi]
        rows.append([
            sl.name.values[i], sl.pos.values[i],
            f"{sl.age.values[i]:.1f}" if np.isfinite(sl.age.values[i]) else "-",
            f"{bundle.injury_rate[gi]*100:.1f}%",
            f"{bundle.injury_dur[gi]:.1f}",
            f"{g.mean():.1f}", f"{np.percentile(g,10):.0f}",
            f"{(g >= 16).mean()*100:.0f}%",
        ])
    _table(con, f"{team} · availability model",
           [("Player", "left"), ("Pos", "center"), ("Age", "right"),
            ("Weekly hazard", "right"), ("Avg absence", "right"),
            ("Games", "right"), ("p10 G", "right"), ("16+ G", "right")], rows,
           note="Hazard is per-week probability of a new absence, adjusted for age and "
                "the player's own durability record. Absence length in games.")
