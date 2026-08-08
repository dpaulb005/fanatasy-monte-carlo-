"""Was a player's usage earned, or vacated?

`fit_usage` pools every game a player appeared in and weights only by season
recency. That silently treats two very different things as the same evidence:
carries taken while the room was whole, and carries that existed only because
the man beside him was hurt. A back who saw twenty touches for six weeks because
the starter was out has those weeks folded into his baseline at full strength --
and the simulator then applies its *own* injury cascade on top, so the same
vacated work is counted once in the prior and again in the draw.

This module measures the size of that, per player. It does not correct it. The
correction has not passed the project's promotion gate (see `docs/ROOM.md` for
the walk-forward test and why it fell short), so what ships is a flag: here is
whose fitted share leans on somebody else's absence, and here is what he did
when the room was healthy.

Three views of the same room, because they answer different questions:

    ahead_ok   how much of the depth chart above him was on the field
    behind_ok  how much of it below him was
    room_ok    everything but himself

A backup is inflated by the starter's absence, which `ahead_ok` catches. A
*starter* is inflated when the committee behind him is out and he absorbs their
work -- invisible to an upward-only measure, and the case that matters for a
lead back with nobody ahead of him at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data
from .config import TARGET_SEASON

POSITIONS = ("RB", "WR", "TE")

# A player has to have been a real part of the room to count as missing from
# it. Two appearances and a 2% snap rate excludes the practice-squad churn that
# would otherwise register as an injury every week.
MIN_WEEKS = 2
MIN_SNAP_PCT = 0.02

# Below this, a team's week is garbage time or a weather game and the shares
# are not meaningful.
MIN_TEAM_PLAYS = 20


def _bridge(seasons) -> dict:
    """pfr_player_id -> gsis_id, which is the join snap counts need."""
    out = {}
    for s in seasons:
        r = data.rosters(s)
        r = r[r.pfr_id.notna() & r.gsis_id.notna()]
        out.update(dict(zip(r.pfr_id, r.gsis_id)))
    return out


def weekly(seasons) -> pd.DataFrame:
    """One row per player-week, with the health of the room around him.

    Availability comes from an explicit grid of room members crossed with the
    weeks their team actually played. Both halves of that matter. A player who
    does not dress has no snap-count row at all, so joining availability onto
    the games that *happened* marks every room fully healthy -- the first
    version of this measurement reported 98.9% intact and was meaningless. And
    the weeks have to come from the schedule rather than a 1..18 range, or every
    team's bye reads as its whole roster being hurt, which is the same mistake
    the injury hazards were once making.
    """
    seasons = sorted(set(int(s) for s in seasons))
    bridge = _bridge(seasons)

    sc = data.snap_counts(seasons)
    sc = sc[sc.game_type == "REG"].copy()
    sc["gsis_id"] = sc.pfr_player_id.map(bridge)
    sc = sc[sc.gsis_id.notna()]

    pw = data.player_week(seasons)
    pw = pw[(pw.season_type == "REG") & pw.position.isin(POSITIONS)].copy()

    tt = pw.groupby(["season", "week", "team"]).agg(
        team_targets=("targets", "sum"), team_carries=("carries", "sum")).reset_index()
    pw = pw.merge(tt, on=["season", "week", "team"], how="left")
    pw["team_opp"] = pw.team_targets + pw.team_carries
    pw["opp"] = pw.targets.fillna(0) + pw.carries.fillna(0)
    pw["share"] = pw.opp / pw.team_opp.replace(0, np.nan)

    played = tt[["season", "team", "week"]].drop_duplicates()

    # Depth order by snap *rate*, never by snap total. A starter who missed six
    # games has fewer season snaps than the backup who replaced him, so ranking
    # on the total calls the backup the starter -- precisely inverting the thing
    # being measured.
    rate = (sc.groupby(["season", "gsis_id", "team"])
              .agg(pct=("offense_pct", "mean"), wks=("week", "nunique")).reset_index())
    rate = rate[(rate.wks >= MIN_WEEKS) & (rate.pct > MIN_SNAP_PCT)]

    roster = (pw.groupby(["season", "team", "position", "player_id"])
                .agg(name=("player_display_name", "last")).reset_index())
    roster = roster.merge(rate, left_on=["season", "team", "player_id"],
                          right_on=["season", "team", "gsis_id"], how="inner")
    roster["depth"] = roster.groupby(["season", "team", "position"]).pct.rank(
        ascending=False, method="first")

    active = sc[sc.offense_snaps.fillna(0) > 0][["season", "week", "gsis_id"]].copy()
    grid = room_health(roster, played, active)

    key = ["season", "team", "position", "week"]
    cols = key + ["player_id", "depth", "pct", "active", "ahead_ok",
                  "behind_ok", "room_ok", "room_weight"]
    df = pw.merge(grid[cols], on=key[:3] + ["week", "player_id"], how="inner")
    return df[df.share.notna() & (df.team_opp > MIN_TEAM_PLAYS) & df.active].copy()


def room_health(roster: pd.DataFrame, played: pd.DataFrame,
                active: pd.DataFrame) -> pd.DataFrame:
    """Room availability per member per week, from frames rather than downloads.

    `roster` is one row per (season, team, position, player_id) with `pct` and
    `depth`; `played` is the weeks each team actually took the field; `active`
    is (season, week, gsis_id) for everyone who took an offensive snap.

    Split out so the arithmetic can be tested without the network, because the
    two ways it goes wrong are both invisible in the output rather than loud:
    a player who did not dress has no row in `active` and vanishes instead of
    counting as absent, and a bye week that is not masked reads as the entire
    roster being hurt.
    """
    grid = roster.merge(played, on=["season", "team"], how="left")
    act = active[["season", "week", "gsis_id"]].copy()
    act["active"] = True
    grid = grid.merge(act, left_on=["season", "week", "player_id"],
                      right_on=["season", "week", "gsis_id"], how="left",
                      suffixes=("", "_x"))
    grid["active"] = grid.active.fillna(False).astype(bool)
    grid = grid.sort_values(["season", "team", "position", "week", "depth"])

    key = ["season", "team", "position", "week"]
    gk = [grid[k] for k in key]
    # Weighted by normal snap rate, not headcount: losing a team's second back
    # is not the same event as losing its fifth, and a plain fraction says it is.
    w = grid.pct.astype(float)
    wa = w * grid.active.astype(float)
    w_cum, wa_cum = w.groupby(gk).cumsum(), wa.groupby(gk).cumsum()
    w_tot = w.groupby(gk).transform("sum")
    wa_tot = wa.groupby(gk).transform("sum")

    def frac(num, den):
        # An empty room ahead of the starter is healthy by definition, not zero.
        return np.where(den > 1e-9, num / np.maximum(den, 1e-9), 1.0)

    grid["ahead_ok"] = frac(wa_cum - wa, w_cum - w)
    grid["behind_ok"] = frac(wa_tot - wa_cum, w_tot - w_cum)
    grid["room_ok"] = frac(wa_tot - wa, w_tot - w)
    grid["room_weight"] = w_tot - w
    return grid


def recency_weights(seasons, target: int, halflife: float = 1.1) -> np.ndarray:
    """Same weighting `fit_usage` applies, so the pooled figure is comparable."""
    return 0.5 ** ((target - 1 - np.asarray(seasons, dtype=float)) / halflife)


def usage_split(seasons=None, target: int = TARGET_SEASON,
                halflife: float = 1.1, intact: float = 0.999) -> pd.DataFrame:
    """Per player: the share history pools, against the share a whole room saw.

    `pooled` reproduces what `fit_usage` would compute -- every game, weighted
    by season recency only -- so `inflation` is directly the amount the fitted
    baseline owes to somebody else's absence.
    """
    if seasons is None:
        seasons = range(target - 4, target)
    df = weekly(seasons)
    df["healthy"] = df.room_ok >= intact
    df["w"] = recency_weights(df.season, target, halflife)

    def wmean(sub):
        if not len(sub):
            return pd.Series(dtype=float)
        return sub.groupby("player_id").apply(
            lambda g: float(np.average(g.share, weights=g.w)), include_groups=False)

    g = df.groupby("player_id")
    out = pd.DataFrame({
        "name": g.player_display_name.last(),
        "pos": g.position.last(),
        "team": g.team.last(),
        "depth": g.depth.last(),
        "games": g.size(),
        "healthy_games": df[df.healthy].groupby("player_id").size(),
        "pooled": wmean(df),
        "healthy_share": wmean(df[df.healthy]),
        "depleted_share": wmean(df[~df.healthy]),
        "room_ok": g.room_ok.mean(),
    })
    out["healthy_games"] = out.healthy_games.fillna(0).astype(int)
    out["inflation"] = out.pooled - out.healthy_share
    # Relative is the number to read. Two points of share means something very
    # different to a lead back and to a third receiver.
    out["inflation_pct"] = out.inflation / out.pooled.replace(0, np.nan)
    return out.reset_index().rename(columns={"player_id": "gsis_id"})


def flags(split: pd.DataFrame, min_games: int = 8, min_healthy: int = 3,
          min_inflation: float = 0.02) -> pd.DataFrame:
    """The players whose fitted usage rests on a depleted room.

    Both game minimums are load-bearing. Without `min_healthy` a player who was
    never once seen with a whole room gets an `inflation` computed against
    nothing, and without `min_games` the list fills with people who played
    twice.
    """
    ok = split[(split.games >= min_games) &
               (split.healthy_games >= min_healthy) &
               split.inflation.notna()]
    return ok[ok.inflation >= min_inflation].sort_values("inflation", ascending=False)


def league_table(split: pd.DataFrame, min_games: int = 8,
                 min_healthy: int = 3) -> pd.DataFrame:
    """Position-level summary: how much of a share is vacated work, on average."""
    ok = split[(split.games >= min_games) &
               (split.healthy_games >= min_healthy) &
               split.inflation.notna() &
               (split.games - split.healthy_games >= 3)]
    rows = []
    for p in POSITIONS:
        s = ok[ok.pos == p]
        if not len(s):
            continue
        rows.append({
            "pos": p, "players": len(s),
            "healthy_share": s.healthy_share.mean(),
            "depleted_share": s.depleted_share.mean(),
            "pooled": s.pooled.mean(),
            "inflation": s.inflation.mean(),
            "inflation_pct": s.inflation.mean() / max(s.pooled.mean(), 1e-9),
        })
    return pd.DataFrame(rows)
