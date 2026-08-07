"""Statistics that require the joint distribution.

Everything here is computed across the *same* ten thousand simulated seasons,
which means every player's outcome is linked to every other's through the games
they actually shared. That is the whole point. A projection system that emits a
mean and a standard deviation per player has marginal distributions; the
questions below are not merely harder for it, they are undefined.

Five things fall out of keeping the joint distribution that are not otherwise
available:

  contingent value   what a backup is worth *in the seasons where the man
                     ahead of him got hurt* -- the only number that matters
                     when deciding whether to roster a handcuff, and one that
                     cannot be derived from two marginal distributions because
                     it is a conditional expectation over a shared event.

  championship       replacement level is not a constant, it is whatever the
  equity             last startable player happened to score *that season*. So
                     value over replacement is computed inside each simulated
                     season and then summarised, rather than computed once
                     against a mean. The difference is the probability of
                     finishing as the position's best player, which is what
                     actually wins a league.

  co-boom lift       whether two players boom *together* more often than their
                     individual rates imply. Stacking analysis exists in daily
                     fantasy and essentially nowhere in season-long, because
                     season-long projections have no joint distribution to ask.

  ceiling anatomy    a 90th-percentile season is not just "more of the same".
                     Comparing a player's best simulated seasons against his
                     median ones says whether his ceiling is bought with health,
                     volume, efficiency or touchdown luck -- and the last of
                     those is the one that will not repeat.

  schedule cost      strength of schedule measured in the currency that matters
                     -- simulated fantasy points against this slate versus a
                     league-average one -- instead of the opponent's rank.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .analysis import fantasy_points
from .config import League, Scoring
from .engine import SIDX


def _fp(result, scoring):
    return fantasy_points(result["totals"], scoring)


# --------------------------------------------------------------------------
# 1. Contingent value: what a backup is worth when the starter goes down
# --------------------------------------------------------------------------

def contingent_value(result, bundle, scoring: Scoring, min_missed: int = 4,
                     min_share: float = 0.03) -> pd.DataFrame:
    """Each player's value conditional on the man ahead of him missing time.

    Computed by conditioning on the *same* simulated seasons: take the subset of
    replications in which the starter played at most `17 - min_missed` games,
    and read the backup's points in exactly those seasons. Because injuries
    cascade through the depth chart inside the engine, the backup's elevated
    usage in those seasons is already there -- nothing is imputed.

    The gap between a handcuff's conditional and unconditional value is the
    number that should drive the roster decision, and it is invisible to any
    model that stores only a mean.
    """
    fp = _fp(result, scoring)
    gp = result["games_played"]
    pt = bundle.player_table
    rows = []

    for team, tm in bundle.teams.items():
        slots = pt.loc[tm.gidx]
        for pos in ("RB", "WR", "TE", "QB"):
            local = np.flatnonzero(slots.pos.values == pos)
            if len(local) < 2:
                continue
            # Rank by projected value, so "the starter" is who the model
            # actually expects to play, not who the chart lists first.
            order = sorted(local, key=lambda i: -fp[:, tm.gidx[i]].mean())
            starter = order[0]
            s_gi = tm.gidx[starter]
            hurt = gp[:, s_gi] <= (17 - min_missed)
            if hurt.sum() < 200:
                continue

            for i in order[1:]:
                gi = tm.gidx[i]
                base = float(fp[:, gi].mean())
                if base < 1.0:
                    continue
                cond = float(fp[hurt, gi].mean())
                healthy = float(fp[~hurt, gi].mean()) if (~hurt).any() else base
                rows.append({
                    "player": slots.name.values[i], "pos": pos, "team": team,
                    "depth": int(slots.depth_rank.values[i]),
                    "behind": slots.name.values[starter],
                    "p_starter_hurt": float(hurt.mean()),
                    "points": base,
                    "if_starter_hurt": cond,
                    "if_starter_healthy": healthy,
                    "contingent_gain": cond - healthy,
                    "leverage": (cond - healthy) / max(base, 1e-6),
                })
    df = pd.DataFrame(rows)
    return df.sort_values("contingent_gain", ascending=False) if len(df) else df


# --------------------------------------------------------------------------
# 2. Championship equity: rank within each simulated season
# --------------------------------------------------------------------------

def championship_equity(result, bundle, scoring: Scoring,
                        league: League | None = None) -> pd.DataFrame:
    """Finish probabilities and value over a *season-specific* replacement level.

    Standard value over replacement fixes replacement at the mean of the Nth
    ranked player. But in any given season the last startable player scores
    whatever he scores, and the gap above him is what a roster spot actually
    bought. Ranking inside each replication and differencing there gives a
    distribution of value rather than a single number -- and, more usefully, the
    probability of finishing first at the position, which no mean can express.
    """
    league = league or League()
    fp = _fp(result, scoring)
    pt = bundle.player_table
    repl_rank = league.replacement_ranks()
    out = []

    for pos, idx in pt.groupby("pos").groups.items():
        idx = np.asarray(idx)
        sub = fp[:, idx]                              # (S, n_pos)
        order = np.argsort(-sub, axis=1)
        ranks = np.empty_like(order)
        np.put_along_axis(ranks, order,
                          np.broadcast_to(np.arange(sub.shape[1]), sub.shape), axis=1)
        ranks = ranks + 1                             # 1-based positional finish

        k = min(repl_rank.get(pos, 24), sub.shape[1]) - 1
        repl = -np.sort(-sub, axis=1)[:, k][:, None]  # replacement score per season
        vor = sub - repl

        for j, gi in enumerate(idx):
            r = ranks[:, j]
            out.append({
                "player": pt.loc[gi, "name"], "pos": pos, "team": pt.loc[gi, "team"],
                "points": float(sub[:, j].mean()),
                "mean_finish": float(r.mean()),
                "p_pos1": float((r == 1).mean()),
                "p_top3": float((r <= 3).mean()),
                "p_top12": float((r <= 12).mean()),
                "p_starter": float((r <= repl_rank.get(pos, 24)).mean()),
                "vor_sim": float(vor[:, j].mean()),
                "vor_sim_p10": float(np.percentile(vor[:, j], 10)),
                "vor_sim_p90": float(np.percentile(vor[:, j], 90)),
                "p_beats_replacement": float((vor[:, j] > 0).mean()),
            })
    return pd.DataFrame(out).sort_values("vor_sim", ascending=False)


# --------------------------------------------------------------------------
# 3. Co-boom lift: do two players boom together more than chance?
# --------------------------------------------------------------------------

def coboom(result, bundle, scoring: Scoring, team: str | None = None,
           quantile: float = 0.75, min_points: float = 60.0) -> pd.DataFrame:
    """Joint boom rate against the independence baseline.

    Lift is P(both boom) / (P(a booms) * P(b booms)). Above one means the pair
    rises together beyond what their individual rates would predict; below one
    means they eat from the same plate. Correlation says the same thing about
    the middle of the distribution -- lift says it about the tail, which is
    where a season is won or lost.
    """
    fp = _fp(result, scoring)
    pt = bundle.player_table
    keep = pt.index[(fp.mean(axis=0) >= min_points)]
    if team:
        keep = [i for i in keep if pt.loc[i, "team"] == team]
    keep = list(keep)
    if len(keep) < 2:
        return pd.DataFrame()

    sub = fp[:, keep]
    thresh = np.quantile(sub, quantile, axis=0)
    boom = sub >= thresh                                # (S, n)
    p = boom.mean(axis=0)
    joint = (boom.astype(np.float32).T @ boom.astype(np.float32)) / boom.shape[0]
    corr = np.corrcoef(sub.T)

    rows = []
    for a in range(len(keep)):
        for b in range(a + 1, len(keep)):
            denom = p[a] * p[b]
            if denom <= 0:
                continue
            rows.append({
                "a": pt.loc[keep[a], "name"], "a_pos": pt.loc[keep[a], "pos"],
                "b": pt.loc[keep[b], "name"], "b_pos": pt.loc[keep[b], "pos"],
                "same_team": pt.loc[keep[a], "team"] == pt.loc[keep[b], "team"],
                "team_a": pt.loc[keep[a], "team"], "team_b": pt.loc[keep[b], "team"],
                "corr": float(corr[a, b]),
                "p_both_boom": float(joint[a, b]),
                "lift": float(joint[a, b] / denom),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 4. Ceiling anatomy: what a 90th-percentile season is actually made of
# --------------------------------------------------------------------------

CEILING_DRIVERS = [
    ("games", None), ("targets", "targets"), ("rush_att", "rush_att"),
    ("rec_yds", "rec_yds"), ("rush_yds", "rush_yds"),
    ("rec_td", "rec_td"), ("rush_td", "rush_td"), ("pass_td", "pass_td"),
    ("pass_yds", "pass_yds"),
]


def ceiling_anatomy(result, bundle, scoring: Scoring, min_points: float = 80.0,
                    top_q: float = 0.90, mid_lo: float = 0.45,
                    mid_hi: float = 0.55) -> pd.DataFrame:
    """Decompose the gap between a player's ceiling seasons and his median ones.

    Takes the replications in his top decile and those around his median, and
    reports how much of each underlying driver changed. The useful reading is
    the *ratio* between them: a ceiling built on volume is one a player can
    repeat, a ceiling built on touchdown rate is one that regresses. Only a
    simulation that stores whole coherent seasons can answer this, because it
    requires looking at the same season from several angles at once.
    """
    fp = _fp(result, scoring)
    tot = result["totals"]
    gp = result["games_played"]
    pt = bundle.player_table
    rows = []

    for gi in pt.index:
        v = fp[:, gi]
        if v.mean() < min_points:
            continue
        hi_cut = np.quantile(v, top_q)
        lo_cut, up_cut = np.quantile(v, mid_lo), np.quantile(v, mid_hi)
        hi = v >= hi_cut
        mid = (v >= lo_cut) & (v <= up_cut)
        if hi.sum() < 50 or mid.sum() < 50:
            continue

        rec = {"player": pt.loc[gi, "name"], "pos": pt.loc[gi, "pos"],
               "team": pt.loc[gi, "team"], "points": float(v.mean()),
               "ceiling": float(v[hi].mean()), "median": float(v[mid].mean())}
        rec["ceiling_gap"] = rec["ceiling"] - rec["median"]

        for label, key in CEILING_DRIVERS:
            a = gp[:, gi] if key is None else tot[SIDX[key]][:, gi]
            m = float(a[mid].mean())
            if m <= 1e-6:
                continue
            rec[f"{label}_ratio"] = float(a[hi].mean() / m)

        # Touchdown dependence: how much of the ceiling is scoring rate rather
        # than opportunity. High values mark a ceiling that will not repeat.
        vol = np.nanmean([rec.get("targets_ratio", np.nan),
                          rec.get("rush_att_ratio", np.nan)])
        td = np.nanmean([rec.get("rec_td_ratio", np.nan),
                         rec.get("rush_td_ratio", np.nan),
                         rec.get("pass_td_ratio", np.nan)])
        rec["volume_ratio"] = float(vol) if np.isfinite(vol) else np.nan
        rec["td_ratio"] = float(td) if np.isfinite(td) else np.nan
        rec["td_dependence"] = (float(td / vol) if np.isfinite(td) and np.isfinite(vol)
                                and vol > 0 else np.nan)
        rec["health_ratio"] = rec.get("games_ratio", np.nan)
        rows.append(rec)

    df = pd.DataFrame(rows)
    return df.sort_values("td_dependence", ascending=False) if len(df) else df


# --------------------------------------------------------------------------
# 5. Weekly startability, from the per-week capture
# --------------------------------------------------------------------------

def startability(result, bundle, scoring: Scoring,
                 playoff_weeks=(14, 15, 16)) -> pd.DataFrame:
    """Per-week reliability, and how the schedule treats a player in December.

    Season totals hide the shape of a season. Two players with the same
    projection are not the same asset if one of them arrives in weekly lumps.
    Requires the weekly capture from `run_season`.
    """
    if "weekly_fp" not in result:
        raise KeyError("result has no weekly capture - re-run `simulate`")
    wfp = result["weekly_fp"]           # (weeks, [mean, sd, p10, p25, p50, p75, p90], P)
    played = result["weekly_played"]
    pt = bundle.player_table

    mean_w = wfp[:, 0, :]
    p90_w = wfp[:, 6, :]
    p10_w = wfp[:, 2, :]
    active = played > 0.01

    rows = []
    pw = [w - 1 for w in playoff_weeks]
    for gi in pt.index:
        act = active[:, gi]
        if act.sum() == 0:
            continue
        m = mean_w[act, gi]
        rows.append({
            "player": pt.loc[gi, "name"], "pos": pt.loc[gi, "pos"],
            "team": pt.loc[gi, "team"],
            "weekly_mean": float(m.mean()),
            "weekly_best": float(m.max()),
            "weekly_worst": float(m.min()),
            "weekly_spread": float(m.max() - m.min()),
            "ceiling_week": float(p90_w[act, gi].mean()),
            "floor_week": float(p10_w[act, gi].mean()),
            # A schedule is only worth talking about if it moves the number.
            "playoff_weeks": float(np.mean([mean_w[w, gi] for w in pw
                                            if w < mean_w.shape[0] and active[w, gi]])
                                   ) if any(active[w, gi] for w in pw
                                            if w < mean_w.shape[0]) else np.nan,
        })
    df = pd.DataFrame(rows)
    if len(df):
        df["playoff_delta"] = df.playoff_weeks - df.weekly_mean
    return df.sort_values("weekly_mean", ascending=False)


# --------------------------------------------------------------------------
# 6. Pairwise head-to-head, for the actual draft decision
# --------------------------------------------------------------------------

def head_to_head(result, bundle, scoring: Scoring, names: list[str]) -> pd.DataFrame:
    """P(row outscores column) across the same simulated seasons.

    Not P(A) vs P(B) from two independent distributions -- the same season,
    which matters whenever the two share a defence, a game script, or an
    offence.
    """
    fp = _fp(result, scoring)
    pt = bundle.player_table
    idx = []
    for n in names:
        hit = pt.index[pt.name.str.lower() == n.lower()]
        if not len(hit):
            hit = pt.index[pt.name.str.lower().str.contains(n.lower(), regex=False)]
        if not len(hit):
            raise KeyError(f"no player matching {n!r}")
        idx.append(int(hit[0]))

    m = np.zeros((len(idx), len(idx)))
    for a in range(len(idx)):
        for b in range(len(idx)):
            m[a, b] = np.nan if a == b else (fp[:, idx[a]] > fp[:, idx[b]]).mean()
    labels = [pt.loc[i, "name"] for i in idx]
    return pd.DataFrame(m, index=labels, columns=labels)
