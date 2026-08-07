"""Top projected performers, and where the model disagrees with last season.

A projection that merely reproduces last year's finish is worth nothing -- you
already have last year's finish. The interesting rows are the ones where the
simulation says something different, and those rows are also where the model is
most likely to be wrong. Printing them together is the point: it puts the
model's convictions and its exposure on the same page.

Disagreements are measured in two ways because they answer different questions.
The points delta says who gains or loses the most fantasy value. The positional
rank delta says who moves in the draft order, which is what actually changes a
decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data
from .board import _console, _fmt
from .config import FANTASY_POSITIONS, Scoring

try:
    from rich.table import Table
    from rich import box
    _RICH = True
except ImportError:                                   # pragma: no cover
    _RICH = False


def prior_season(season: int, scoring: Scoring) -> pd.DataFrame:
    """What each player actually scored, and where he finished, last year."""
    pw = data.player_week([season])
    pw = pw[(pw.season_type == "REG") & pw.position.isin(FANTASY_POSITIONS)]
    s = scoring
    fp = (
        pw.passing_yards.fillna(0) * s.pass_yards
        + pw.passing_tds.fillna(0) * s.pass_td
        + pw.passing_interceptions.fillna(0) * s.interception
        + pw.rushing_yards.fillna(0) * s.rush_yards
        + pw.rushing_tds.fillna(0) * s.rush_td
        + pw.receptions.fillna(0) * s.reception
        + pw.receiving_yards.fillna(0) * s.rec_yards
        + pw.receiving_tds.fillna(0) * s.rec_td
        + (pw.rushing_fumbles_lost.fillna(0) + pw.receiving_fumbles_lost.fillna(0)
           + pw.sack_fumbles_lost.fillna(0)) * s.fumble_lost
    )
    out = pw.assign(fp=fp).groupby("player_id").agg(
        prior_pts=("fp", "sum"), prior_games=("week", "nunique"),
        prior_team=("team", "last"), pos=("position", "last"),
    ).reset_index().rename(columns={"player_id": "gsis_id"})
    out["prior_pos_rank"] = out.groupby("pos").prior_pts.rank(
        ascending=False, method="min").astype(int)
    return out


def build_table(df: pd.DataFrame, bundle, scoring: Scoring) -> pd.DataFrame:
    """Join projections to last season's actuals."""
    proj = df.copy()
    # df comes back sorted by value, so identities must join on the index.
    proj["gsis_id"] = bundle.player_table.gsis_id.reindex(proj.index)
    prior = prior_season(bundle.season - 1, scoring)
    m = proj.merge(prior[["gsis_id", "prior_pts", "prior_games", "prior_team",
                          "prior_pos_rank"]], on="gsis_id", how="left")
    m["prior_pts"] = m.prior_pts.fillna(0.0)
    m["delta"] = m.points - m.prior_pts
    # Season totals confound role with availability. A projection is a mean over
    # simulated seasons that include the games a player misses; last year's
    # actual is one realisation from a player who may have played all seventeen.
    # Comparing the two makes every healthy player look like a decline. Points
    # per game removes the confound and is what actually says whether the model
    # thinks his role changed.
    m["prior_ppg"] = np.where(m.prior_games > 0, m.prior_pts / m.prior_games, np.nan)
    m["ppg_delta"] = m.ppg - m.prior_ppg
    m["rank_delta"] = m.prior_pos_rank - m.pos_rank      # positive = improving
    m["moved"] = (m.prior_team.notna()) & (m.prior_team != m.team)
    return m


def _table(con, title, cols, rows, note=None):
    if not _RICH:
        print(f"\n{title}")
        for r in rows:
            print("  " + "  ".join(str(x) for x in r))
        return
    t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
              title_style="bold")
    for c, j in cols:
        t.add_column(c, justify=j)
    for r in rows:
        t.add_row(*[str(x) for x in r])
    con.print(t)
    if note:
        con.print(f"[grey58]{note}[/]")


def _row(r, prior_label: str):
    was = "rookie" if r.rookie else (
        f"{r.prior_pts:,.0f}" if r.prior_pts > 0 else "did not play")
    rk = "-" if not np.isfinite(r.prior_pos_rank) else f"{r.pos}{int(r.prior_pos_rank)}"
    move = f"  [grey42]{r.prior_team}→{r.team}[/]" if r.moved and _RICH else (
        f"  {r.prior_team}->{r.team}" if r.moved else "")
    ppg_d = "-" if not np.isfinite(r.ppg_delta) else f"{r.ppg_delta:+.1f}"
    prior_ppg = "-" if not np.isfinite(r.prior_ppg) else f"{r.prior_ppg:.1f}"
    return [
        f"{r.player}{move}", r.pos, r.team,
        _fmt(r.points, 0), _fmt(r.p10, 0), _fmt(r.p90, 0),
        f"{r.pos}{int(r.pos_rank)}", rk, was, f"{r.delta:+,.0f}",
        prior_ppg, _fmt(r.ppg, 1), ppg_d,
    ]


COLS = [("Player", "left"), ("Pos", "center"), ("Tm", "center"),
        ("Proj", "right"), ("Floor", "right"), ("Ceil", "right"),
        ("Rank", "center"), ("Was", "center"), ("Last yr", "right"),
        ("Δ pts", "right"),
        ("PPG was", "right"), ("PPG proj", "right"), ("Δ PPG", "right")]


# A player is worth comparing against his past only if he is rosterable in one
# direction or the other. Without this the movement lists fill with backup
# quarterbacks: a passer who started eight games has a real per-game rate and
# now projects near zero behind a starter, which swamps every genuine outlier.
# That he lost the job is a fact you already have, not something the model found.
RELEVANT_RANK = {"QB": 26, "RB": 50, "WR": 60, "TE": 26}


def report(df: pd.DataFrame, bundle, scoring: Scoring, top: int = 25,
           n_outliers: int = 15, min_prior_games: int = 6) -> None:
    con = _console()
    m = build_table(df, bundle, scoring)
    prev = bundle.season - 1

    # ---- headline: the best projected seasons -------------------------
    best = m.nlargest(top, "points")
    _table(con, f"Top {top} projected fantasy seasons  ·  {scoring.name}  ·  "
                f"{bundle.season}",
           COLS, [_row(r, str(prev)) for _, r in best.iterrows()],
           note=f"'Was' and 'Last yr' are the player's actual {prev} finish and "
                f"points. Δ is the change the model is projecting.")

    for pos in ("QB", "RB", "WR", "TE"):
        sub = m[m.pos == pos].nlargest(12 if pos in ("QB", "TE") else 18, "points")
        _table(con, f"{pos}{len(sub)} projected  ·  {scoring.name}",
               COLS, [_row(r, str(prev)) for _, r in sub.iterrows()])

    # ---- where the model disagrees with last season -------------------
    # Restrict to players who actually had a season to compare against, so the
    # list is genuine disagreement rather than an artefact of missing data.
    cmp = m[(m.prior_games >= min_prior_games) & (~m.rookie)]
    cmp = cmp[cmp.ppg_delta.notna()]
    cutoff = cmp.pos.map(RELEVANT_RANK).fillna(50)
    cmp = cmp[(cmp.pos_rank <= cutoff) & (cmp.prior_pos_rank <= cutoff * 2)]
    risers = cmp.nlargest(n_outliers, "ppg_delta")
    _table(con, f"Biggest projected RISERS vs {prev}", COLS,
           [_row(r, str(prev)) for _, r in risers.iterrows()],
           note="Ranked by change in points PER GAME, not season total: a season "
                "total mixes a change in role with a change in how many games the "
                "player is expected to be available for. These are the model's "
                "convictions, and equally where it is most exposed -- a projection "
                "that disagrees with a full season of evidence is an edge or an error.")

    fallers = cmp.nsmallest(n_outliers, "ppg_delta")
    _table(con, f"Biggest projected FALLERS vs {prev}", COLS,
           [_row(r, str(prev)) for _, r in fallers.iterrows()],
           note="Common causes, in rough order: a lost role on the depth chart, "
                "an age or durability adjustment, or last season's touchdown rate "
                "regressing toward the underlying usage.")

    # ---- rank movement, which is what changes a draft decision ---------
    ranked = cmp[cmp.pos_rank <= 60]
    up = ranked.nlargest(10, "rank_delta")
    down = ranked.nsmallest(10, "rank_delta")
    rows = []
    for label, sub in (("▲", up), ("▼", down)):
        for _, r in sub.iterrows():
            rows.append([
                label, r.player, r.pos, r.team,
                f"{r.pos}{int(r.prior_pos_rank)}", f"{r.pos}{int(r.pos_rank)}",
                f"{r.rank_delta:+.0f}", _fmt(r.points, 0),
            ])
    _table(con, "Largest moves in positional rank",
           [("", "center"), ("Player", "left"), ("Pos", "center"), ("Tm", "center"),
            (f"{prev}", "center"), (f"{bundle.season}", "center"),
            ("Move", "right"), ("Proj", "right")], rows,
           note="Rank movement, not point movement: this is the list that "
                "actually changes where you draft someone.")
