"""Turn simulated stat lines into fantasy conclusions.

The output of a run is a distribution, not a number, and the whole point of
simulating is to keep that distribution intact. A projection of 240 points
means something very different when the tenth percentile is 210 than when it is
95, and draft decisions turn on exactly that difference. So everything here is
computed per replication first and summarised second.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import League, Scoring
from .engine import SIDX


def fantasy_points(totals: np.ndarray, scoring: Scoring) -> np.ndarray:
    """(S, P) season fantasy points under `scoring`."""
    s = scoring
    fp = (
        totals[SIDX["pass_yds"]] * s.pass_yards
        + totals[SIDX["pass_td"]] * s.pass_td
        + totals[SIDX["pass_int"]] * s.interception
        + totals[SIDX["rush_yds"]] * s.rush_yards
        + totals[SIDX["rush_td"]] * s.rush_td
        + totals[SIDX["rec"]] * s.reception
        + totals[SIDX["rec_yds"]] * s.rec_yards
        + totals[SIDX["rec_td"]] * s.rec_td
        + totals[SIDX["fum_lost"]] * s.fumble_lost
    )
    return fp


def summarise(result: dict, bundle, scoring: Scoring) -> pd.DataFrame:
    """Per-player projection with the full shape of the distribution."""
    totals = result["totals"]
    gp = result["games_played"]
    fp = fantasy_points(totals, scoring)

    ptab = bundle.player_table.copy()
    q = lambda a, p: np.percentile(a, p, axis=0)

    with np.errstate(invalid="ignore", divide="ignore"):
        ppg = np.divide(fp, np.maximum(gp, 1e-6), out=np.zeros_like(fp), where=gp > 0)

    df = pd.DataFrame({
        "player": ptab.name.values,
        "pos": ptab.pos.values,
        "team": ptab.team.values,
        "age": ptab.age.values,
        "depth": ptab.depth_rank.values,
        "rookie": ptab.is_rookie.values,
        "games": gp.mean(axis=0),
        "points": fp.mean(axis=0),
        "median": np.median(fp, axis=0),
        "p10": q(fp, 10), "p25": q(fp, 25), "p75": q(fp, 75), "p90": q(fp, 90),
        "sd": fp.std(axis=0),
        "ppg": ppg.mean(axis=0),
        # Underlying stat lines, which are the reason to simulate at all.
        "pass_yds": totals[SIDX["pass_yds"]].mean(axis=0),
        "pass_td": totals[SIDX["pass_td"]].mean(axis=0),
        "ints": totals[SIDX["pass_int"]].mean(axis=0),
        "carries": totals[SIDX["rush_att"]].mean(axis=0),
        "rush_yds": totals[SIDX["rush_yds"]].mean(axis=0),
        "rush_td": totals[SIDX["rush_td"]].mean(axis=0),
        "targets": totals[SIDX["targets"]].mean(axis=0),
        "rec": totals[SIDX["rec"]].mean(axis=0),
        "rec_yds": totals[SIDX["rec_yds"]].mean(axis=0),
        "rec_td": totals[SIDX["rec_td"]].mean(axis=0),
    }, index=ptab.index)

    # Boom and bust, defined against positional starter baselines rather than
    # an absolute number, so the rates mean the same thing at every position.
    for pos in df.pos.unique():
        m = df.pos == pos
        starters = df.loc[m].nlargest(max(int(m.sum() * 0.15), 5), "points")
        hi = starters.points.quantile(0.75)
        lo = starters.points.quantile(0.25)
        idx = np.flatnonzero(m.values)
        df.loc[m, "boom"] = (fp[:, idx] > hi).mean(axis=0)
        df.loc[m, "bust"] = (fp[:, idx] < lo).mean(axis=0)

    df["pos_rank"] = df.groupby("pos").points.rank(ascending=False, method="min").astype(int)
    return df.sort_values("points", ascending=False)


def add_value(df: pd.DataFrame, result: dict, bundle, scoring: Scoring,
              league: League) -> pd.DataFrame:
    """Value over replacement, and tiers.

    Replacement level is the point where a position stops being scarce: the
    projected points of the last player at that position who would realistically
    start in this league. Raw totals compare a quarterback to a tight end and
    conclude the quarterback is better; value over replacement asks the question
    that actually matters, which is how much the pick gains you over what you
    could have had for nothing.
    """
    df = df.copy()
    repl_ranks = league.replacement_ranks()

    repl_points = {}
    for pos, rank in repl_ranks.items():
        sub = df[df.pos == pos].sort_values("points", ascending=False)
        if sub.empty:
            repl_points[pos] = 0.0
            continue
        i = min(max(rank - 1, 0), len(sub) - 1)
        repl_points[pos] = float(sub.points.iloc[i])

    df["replacement"] = df.pos.map(repl_points)
    df["vor"] = df.points - df.replacement
    # The floor and ceiling versions answer different draft questions: who is
    # safe, and who can win you the week.
    df["vor_floor"] = df.p10 - df.replacement
    df["vor_ceiling"] = df.p90 - df.replacement

    df = df.sort_values("vor", ascending=False)
    df["overall_rank"] = np.arange(1, len(df) + 1)
    df["tier"] = _tiers(df)
    return df


def _tiers(df: pd.DataFrame, max_tiers: int = 12, horizon: int = 200) -> np.ndarray:
    """Group players into tiers of genuinely comparable value.

    Implemented as one-dimensional k-means over value above replacement, which
    is what a tier actually is: a set of players close enough together that
    which one you get does not much matter, separated from the next set by a
    drop that does. A local-gap rule was tried first and collapsed the entire
    top of the board into a single tier, because once past the elite handful
    the gaps become uniform and no threshold fires.

    Only the draftable horizon is clustered; everything past it is swept into a
    final tier, since precision there is not worth anything.
    """
    n = len(df)
    tiers = np.ones(n, dtype=int)
    vor = df.vor.to_numpy(dtype=float)
    if n < 3:
        return tiers

    head = min(horizon, n)
    x = vor[:head]
    k = min(max_tiers, max(2, head // 8))

    # Initialise on quantiles of the data and run Lloyd's algorithm. Sorted
    # input keeps the assignment contiguous, so clusters are true tiers.
    centres = np.quantile(x, np.linspace(0, 1, k))
    for _ in range(60):
        assign = np.abs(x[:, None] - centres[None, :]).argmin(axis=1)
        moved = False
        for j in range(k):
            m = assign == j
            if m.any():
                c = x[m].mean()
                if not np.isclose(c, centres[j]):
                    centres[j] = c
                    moved = True
        if not moved:
            break

    assign = np.abs(x[:, None] - centres[None, :]).argmin(axis=1)
    # Relabel so tier 1 is the most valuable, and enforce monotonicity down the
    # board (a cluster boundary can otherwise flicker on near-ties).
    order = np.argsort(-centres)
    rank_of = {c: i + 1 for i, c in enumerate(order)}
    lab = np.array([rank_of[a] for a in assign])
    tiers[:head] = np.maximum.accumulate(lab)
    tiers[head:] = tiers[head - 1] + 1 if head < n else 1
    return tiers


def team_summary(result: dict, bundle) -> pd.DataFrame:
    """Projected team scoring and win totals, for the market sanity check."""
    rows = []
    for t, pts in result["team_points"].items():
        wins = result["team_wins"][t]
        rows.append({
            "team": t,
            "points": float(pts.mean()),
            "points_pg": float(pts.mean() / 17.0),
            "wins": float(wins.mean()),
            "wins_p10": float(np.percentile(wins, 10)),
            "wins_p90": float(np.percentile(wins, 90)),
        })
    return pd.DataFrame(rows).sort_values("wins", ascending=False)


def correlation(result: dict, bundle, scoring: Scoring, a: str, b: str) -> float:
    """Correlation in weekly-equivalent outcomes between two players.

    Useful for stacking decisions: a quarterback and his top receiver should
    come out positively correlated, and two backs in the same committee
    negatively, purely as a consequence of how the games were simulated.
    """
    fp = fantasy_points(result["totals"], scoring)
    ptab = bundle.player_table
    ia = ptab.index[ptab.name == a]
    ib = ptab.index[ptab.name == b]
    if not len(ia) or not len(ib):
        raise KeyError(f"unknown player: {a if not len(ia) else b}")
    return float(np.corrcoef(fp[:, ia[0]], fp[:, ib[0]])[0, 1])
