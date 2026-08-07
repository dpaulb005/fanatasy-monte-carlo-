"""Backtest the model against a season that has already been played.

Validating against league-average rates only proves the engine produces
NFL-shaped games. It says nothing about whether the model can tell *players*
apart, which is the only thing a fantasy projection is for. The honest test is
out-of-sample: build the model knowing nothing after the previous season,
project the year, and score the projection against what actually happened.

Care is taken that the model cannot see the answer. The play-by-play window is
truncated before the target season, every usage and strength fit is already
bounded by it, and the depth chart is capped at a preseason date -- a December
depth chart would already encode who turned out to be good.

Two caveats are stated rather than hidden. First, rosters are read at their
end-of-season state, so a player traded in October is credited to his final
team; this is mild and affects few players. Second, results are scored only for
players the model actually carried on a depth chart, so a player who came from
nowhere to matter is a miss the headline numbers do not show -- the coverage
line reports how much of the real fantasy production was in scope at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import analysis, build as build_mod, data, season as season_mod
from .config import FANTASY_POSITIONS, Scoring

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH = True
except ImportError:                                   # pragma: no cover
    _RICH = False


def actual_fantasy(season: int, scoring: Scoring) -> pd.DataFrame:
    """What each player really scored in `season`."""
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
        actual=("fp", "sum"), games=("week", "nunique"),
        pos=("position", "last"), name=("player_display_name", "last"),
    )
    return out.reset_index().rename(columns={"player_id": "gsis_id"})


def run_backtest(season: int, n_sims: int, scoring: Scoring, seed: int = 11,
                 pbp_start: int = 2016, verbose: bool = True) -> pd.DataFrame:
    """Build as of `season`'s preseason, simulate it, and score the result."""
    if verbose:
        print(f"building model for {season} using data through {season - 1} ...",
              flush=True)
    bundle = build_mod.build(
        season=season,
        pbp_seasons=range(pbp_start, season),
        as_of=f"{season}-09-01",
        verbose=verbose,
    )
    if verbose:
        print(f"simulating {n_sims:,} seasons of {season} ...", flush=True)
    result = season_mod.run_season(bundle, n_sims=n_sims, seed=seed, verbose=verbose)

    proj = analysis.summarise(result, bundle, scoring)
    # summarise() returns rows sorted by projected points while player_table is
    # in global-index order, so this must align on the index. Assigning
    # `.values` positionally silently pairs every player with someone else's
    # actual season -- which looks like a model with no predictive power at all
    # rather than like a bug.
    proj["gsis_id"] = bundle.player_table.gsis_id.reindex(proj.index)

    act = actual_fantasy(season, scoring)
    df = proj.merge(act[["gsis_id", "actual"]], on="gsis_id", how="left")
    df["actual"] = df.actual.fillna(0.0)
    df["error"] = df.points - df.actual

    total_actual = act.actual.clip(lower=0).sum()
    covered = act[act.gsis_id.isin(set(df.gsis_id))].actual.clip(lower=0).sum()
    df.attrs["coverage"] = float(covered / total_actual) if total_actual else float("nan")
    df.attrs["season"] = season
    df.attrs["n_sims"] = n_sims
    return df


def _spearman(a, b) -> float:
    """Rank correlation without pulling in scipy.

    pandas delegates method="spearman" to scipy, which is not a dependency
    here. Ranking with argsort and taking the Pearson correlation of the ranks
    is the same statistic; average ranks are used so ties do not bias it.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 3:
        return float("nan")

    def rank(x):
        order = np.argsort(x, kind="mergesort")
        r = np.empty(len(x), dtype=float)
        r[order] = np.arange(len(x), dtype=float)
        # Average the ranks within each group of tied values.
        sx = x[order]
        i = 0
        while i < len(sx):
            j = i
            while j + 1 < len(sx) and sx[j + 1] == sx[i]:
                j += 1
            if j > i:
                r[order[i:j + 1]] = np.arange(i, j + 1).mean()
            i = j + 1
        return r

    ra, rb = rank(a), rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


# The cohort Fantasy Football Analytics has used to compare projection sources
# since 2014 -- top 20 QB, top 20 TE, top 40 RB, top 40 WR, scored *within*
# position. Matching it is the only way our numbers mean anything next to
# theirs: R-squared is extremely sensitive to range restriction, so scoring a
# wider cohort inflates correlation and drags MAE in the other direction. Our
# own top-200 board is both wider and pooled across positions, which flatters
# the correlation and penalises the error.
FFA_COHORT = {"QB": 20, "TE": 20, "RB": 40, "WR": 40}


def score_matched(df: pd.DataFrame, scoring: Scoring) -> None:
    """Score on the public benchmark's cohort, for a like-for-like comparison."""
    con = Console() if _RICH else None
    season = df.attrs.get("season")

    rows = []
    for pos, n in FFA_COHORT.items():
        sub = df[df.pos == pos].nlargest(n, "points")
        if len(sub) < 5:
            continue
        r = np.corrcoef(sub.points, sub.actual)[0, 1]
        rows.append([
            pos, len(sub), f"{r:.3f}", f"{r*r*100:.1f}%",
            f"{_spearman(sub.points, sub.actual):.3f}",
            f"{(sub.points - sub.actual).abs().mean():.1f}",
            f"{(sub.points - sub.actual).mean():+.1f}",
        ])

    title = (f"Backtest {season} on the public-benchmark cohort  ·  "
             f"top 20 QB/TE, top 40 RB/WR, scored within position")
    cols = [("pos", "left"), ("n", "right"), ("corr", "right"), ("R²", "right"),
            ("rank corr", "right"), ("MAE", "right"), ("bias", "right")]
    if _RICH:
        t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
                  title_style="bold")
        for c, j in cols:
            t.add_column(c, justify=j)
        for rw in rows:
            t.add_row(*rw)
        con.print(t)
        con.print(
            "[grey58]Comparable published figures (Fantasy Football Analytics, "
            "best single source, season-long): QB R² 8.9%, RB 19.1%, WR 8.9%, "
            "TE 9.0%; season MAE QB 61.0, RB 52.2. Their R² is a single season's "
            "best source and their MAE an eleven-season average, so neither is a "
            "clean target -- but MAE is the honest weak spot and is reported here "
            "rather than buried under a wider cohort.[/]"
        )
    else:
        print(f"\n{title}")
        for rw in rows:
            print("  " + "  ".join(rw))


def score(df: pd.DataFrame, scoring: Scoring, top_n: int = 200) -> None:
    """Report accuracy overall, by position, and against a naive baseline."""
    con = Console() if _RICH else None

    def show(title, rows, cols, note: str | None = None):
        if _RICH:
            t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
                      title_style="bold")
            for c, j in cols:
                t.add_column(c, justify=j)
            for r in rows:
                t.add_row(*[str(x) for x in r])
            con.print(t)
            if note:
                con.print(f"[grey58]{note}[/]")
        else:
            print(f"\n{title}")
            for r in rows:
                print("  " + "  ".join(str(x) for x in r))
            if note:
                print(f"  {note}")

    season = df.attrs.get("season")
    # Score on players the model gave a real role; ranking noise among fringe
    # players is not what the projection is for.
    board = df.nlargest(top_n, "points")

    rows = []
    for label, sub in [("all positions", board)] + [
        (pos, board[board.pos == pos]) for pos in ("QB", "RB", "WR", "TE")
    ]:
        if len(sub) < 5:
            continue
        r = np.corrcoef(sub.points, sub.actual)[0, 1]
        rho = _spearman(sub.points, sub.actual)
        mae = (sub.points - sub.actual).abs().mean()
        bias = (sub.points - sub.actual).mean()
        rows.append([label, len(sub), f"{r:.3f}", f"{rho:.3f}", f"{mae:.1f}", f"{bias:+.1f}"])

    show(f"Backtest {season}  ·  top {top_n} projected  ·  {scoring.name}", rows,
         [("cohort", "left"), ("n", "right"), ("corr", "right"),
          ("rank corr", "right"), ("MAE", "right"), ("bias", "right")],
         note=f"coverage: {df.attrs.get('coverage', float('nan'))*100:.1f}% of actual "
              f"league-wide fantasy production was on a modelled depth chart")

    # Calibration: do the stated intervals actually contain the outcome?
    inside = ((board.actual >= board.p10) & (board.actual <= board.p90)).mean()
    inside50 = ((board.actual >= board.p25) & (board.actual <= board.p75)).mean()
    show("Interval calibration",
         [["p10-p90 (nominal 80%)", f"{inside*100:.1f}%"],
          ["p25-p75 (nominal 50%)", f"{inside50*100:.1f}%"]],
         [("interval", "left"), ("actual coverage", "right")],
         note="An interval that contains the outcome far less often than its "
              "nominal rate is overconfident; far more often, too wide.")

    # Biggest misses, in both directions -- the most informative rows to read.
    worst_over = board.nlargest(8, "error")[["player", "pos", "team", "points", "actual"]]
    worst_under = board.nsmallest(8, "error")[["player", "pos", "team", "points", "actual"]]
    for title, sub in (("Most over-projected", worst_over),
                       ("Most under-projected", worst_under)):
        show(title,
             [[r.player, r.pos, r.team, f"{r.points:.0f}", f"{r.actual:.0f}"]
              for _, r in sub.iterrows()],
             [("player", "left"), ("pos", "center"), ("team", "center"),
              ("projected", "right"), ("actual", "right")])
