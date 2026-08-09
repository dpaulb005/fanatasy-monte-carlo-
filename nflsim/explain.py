"""Why is this player projected where he is?

Every projection is the end of a chain: recorded usage, recency weighting,
shrinkage toward a depth-rank baseline, a team-change discount, normalisation
inside the offence, then the engine. When a number looks wrong the useful
question is which link moved it, and the answer is usually visible the moment
the links are printed side by side.

This reconstructs the chain for one player and shows each step's output next to
what he actually did last season. It computes nothing the build does not; it
just makes the build legible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data
from .config import TARGET_SEASON
from .priors import HALFLIFE_USAGE

RZ_LINE = 20          # yards from the end zone that counts as the red zone


def usage_history(name: str, seasons=None) -> pd.DataFrame:
    """Season-by-season volume and share, as the model's sources record it."""
    seasons = list(seasons or range(TARGET_SEASON - 4, TARGET_SEASON))
    pw = data.player_week(seasons)
    pw = pw[(pw.season_type == "REG")]
    tt = pw.groupby(["season", "week", "team"]).agg(
        tg=("targets", "sum"), tc=("carries", "sum")).reset_index()
    pw = pw.merge(tt, on=["season", "week", "team"], how="left")
    p = pw[pw.player_display_name == name]
    if not len(p):
        return pd.DataFrame()
    g = p.groupby("season").agg(
        team=("team", "last"), games=("week", "size"),
        targets=("targets", "sum"), rec=("receptions", "sum"),
        rec_yds=("receiving_yards", "sum"), rec_td=("receiving_tds", "sum"),
        carries=("carries", "sum"), rush_yds=("rushing_yards", "sum"),
        rush_td=("rushing_tds", "sum"),
        team_tg=("tg", "sum"), team_tc=("tc", "sum"),
        ppr=("fantasy_points_ppr", "sum"))
    g["tgt_share"] = g.targets / g.team_tg.replace(0, np.nan)
    g["rush_share"] = g.carries / g.team_tc.replace(0, np.nan)
    g["ppg"] = g.ppr / g.games
    return g.drop(columns=["team_tg", "team_tc"])


def recency_blend(hist: pd.DataFrame, col: str,
                  target: int = TARGET_SEASON,
                  halflife: float = HALFLIFE_USAGE) -> tuple[float, np.ndarray]:
    """The weighted mean `fit_usage` forms, and the weights it uses.

    Worth printing because of what it does to a player in a straight line: a
    weighted mean of levels always sits *between* the observations, so somebody
    who has declined four years running is projected above his most recent
    season, and somebody climbing is projected below it. That is arithmetic,
    not a judgement about the player.
    """
    if not len(hist) or hist[col].isna().all():
        return float("nan"), np.array([])
    s = hist.dropna(subset=[col])
    w = 0.5 ** ((target - 1 - s.index.to_numpy(dtype=float)) / halflife)
    w = w / w.sum()
    return float((s[col].to_numpy() * w).sum()), w


def redzone_conversion(names: list[str], seasons=None,
                       min_targets: int = 25) -> pd.DataFrame:
    """Touchdowns per red-zone target, against the league.

    Included because it is the first thing anybody reaches for to explain a
    touchdown projection, and because the answer is that it does not persist --
    see `docs/PLAYER_DIAGNOSTICS.md`. The model holds conversion constant within
    a position on purpose. This table exists so that can be checked rather than
    assumed.
    """
    seasons = list(seasons or range(TARGET_SEASON - 4, TARGET_SEASON))
    cols = ["season", "play_type", "yardline_100", "receiver_player_name",
            "pass_touchdown"]
    p = data.play_by_play(seasons, cols)
    rz = p[(p.play_type == "pass") & (p.yardline_100 <= RZ_LINE)
           & p.receiver_player_name.notna()]
    league = float(rz.pass_touchdown.mean())
    g = rz.groupby("receiver_player_name").agg(
        rz_targets=("pass_touchdown", "size"), rz_td=("pass_touchdown", "sum"))
    g = g[g.rz_targets >= min_targets]
    g["rate"] = g.rz_td / g.rz_targets
    g["vs_league"] = g.rate / league - 1.0

    # Names in play-by-play are "Z.Flowers"; match on initial and surname.
    def key(n):
        parts = str(n).replace(".", " ").split()
        return (parts[0][0].upper(), parts[-1].lower()) if parts else ("", "")

    want = {key(n): n for n in names}
    g = g.reset_index()
    g["full"] = g.receiver_player_name.map(lambda n: want.get(key(n)))
    out = g[g.full.notna()].copy()
    out["league_rate"] = league
    return out[["full", "receiver_player_name", "rz_targets", "rz_td", "rate",
                "league_rate", "vs_league"]]


def chain(name: str, bundle, projections: pd.DataFrame,
          baselines: dict | None = None) -> dict:
    """Reconstruct the share chain for one player.

    Returns the four numbers that matter and the room around him: what he did,
    what the weighted history says, what shrinkage does to it, and what the
    engine was finally handed.
    """
    pt = bundle.player_table
    row = pt[pt.name == name]
    if not len(row):
        raise SystemExit(f"no player named {name!r} in the model")
    gi = int(row.index[0])
    team, pos = row.team.iloc[0], row.pos.iloc[0]
    tm = bundle.teams[team]
    slot = int(np.flatnonzero(tm.gidx == gi)[0])

    hist = usage_history(name)
    out = {
        "gindex": gi, "name": name, "pos": pos, "team": team,
        "age": float(row.age.iloc[0]), "depth": int(row.depth_rank.iloc[0]),
        "conf": float(row.conf.iloc[0]),
        "history": hist,
        "fitted": {
            "target_share": float(tm.target_share[slot]),
            "rush_share": float(tm.rush_share[slot]),
            "rz_target_share": float(tm.rz_target_share[slot]),
            "gl_target_share": float(tm.gl_target_share[slot]),
            "gl_rush_share": float(tm.gl_share[slot]),
            "adot": float(tm.adot[slot]), "yac": float(tm.yac_mean[slot]),
            "catch_oe": float(tm.catch_oe[slot]), "ypc_oe": float(tm.ypc_oe[slot]),
        },
        "injury_rate": float(bundle.injury_rate[gi]),
        "avail_mult": float(row.avail_mult.iloc[0]),
        "projection": projections.loc[gi],
    }
    for col, key in (("tgt_share", "target_share"), ("rush_share", "rush_share")):
        blend, w = recency_blend(hist, col)
        out.setdefault("weighted", {})[key] = blend
        out.setdefault("weights", {})[key] = w
        if len(hist) and col in hist:
            out.setdefault("last", {})[key] = float(hist[col].iloc[-1])
        if baselines:
            b = baselines.get((pos, min(out["depth"], 5)), {})
            bkey = "tshare" if col == "tgt_share" else "rshare"
            out.setdefault("baseline", {})[key] = float(b.get(bkey, np.nan))

    mates = pt[(pt.team == team) & (pt.pos == pos)].copy()
    idx = [int(np.flatnonzero(tm.gidx == g)[0]) for g in mates.index]
    mates["target_share"] = tm.target_share[idx]
    mates["rush_share"] = tm.rush_share[idx]
    mates["proj"] = projections.points.reindex(mates.index)
    out["room"] = mates[["name", "depth_rank", "age", "conf",
                         "target_share", "rush_share", "proj"]]
    return out
