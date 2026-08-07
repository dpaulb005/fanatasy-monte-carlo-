"""Check the simulation against things that are already true.

A simulation that produces beautiful distributions from broken physics is worse
than useless, because it is confidently wrong. Three checks are run:

1. **League rates.** Does a simulated game look like an NFL game -- plays,
   points, completion percentage, yards per carry, touchdowns, interceptions?
   This is the check that catches engine bugs, and it is the one that matters
   most, because every projection downstream is built on it.

2. **Positional fantasy output.** Do the top twelve quarterbacks, twenty-four
   backs and thirty-six receivers score what those cohorts actually scored?
   A model can get league rates right and still distribute them wrongly.

3. **The market.** Where betting lines exist for 2026, do the simulated totals
   agree? This is deliberately last and deliberately advisory. The model is
   built from first principles on purpose, so a disagreement here is
   information, not necessarily an error -- but a *large* disagreement usually
   means the model, not the market, is wrong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data
from .analysis import fantasy_points
from .config import FANTASY_POSITIONS
from .engine import SIDX

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH = True
except ImportError:                                   # pragma: no cover
    _RICH = False


def _weighted_actual_rates(seasons, target: int, halflife: float) -> dict:
    """Recency-weighted average of per-season league rates.

    The engine is fit to a weighted span of seasons, not to last season, so
    this is the reference it should be judged against. Scoring it purely
    against the most recent year would penalise it for correctly declining to
    chase a single season's noise. Last season is reported alongside, since
    that is the year the projected one will most resemble.
    """
    from .priors import recency_weights

    per_season = {yr: _actual_league_rates(yr) for yr in seasons}
    w = recency_weights(np.array(list(per_season)), target, halflife)
    w = w / w.sum()
    keys = next(iter(per_season.values())).keys()
    return {k: float(sum(per_season[yr][k] * wi
                         for yr, wi in zip(per_season, w))) for k in keys}


def _actual_league_rates(season: int) -> dict:
    """Per-team-game rates from a real season."""
    pbp = data.play_by_play([season])
    reg = pbp[pbp.season_type == "REG"]
    n_tg = reg.groupby(["game_id", "posteam"]).ngroups

    scrim = reg[reg.play_type.isin(["run", "pass"]) & (reg.qb_kneel != 1)]
    dropbacks = reg[reg.qb_dropback == 1]
    att = reg[(reg.pass_attempt == 1) & (reg.sack != 1)]
    rush = reg[(reg.rush_attempt == 1) & (reg.qb_kneel != 1)]

    games = data.games()
    g = games[(games.season == season) & (games.game_type == "REG")]
    pts = pd.concat([g.home_score, g.away_score]).mean()

    return {
        "plays/team-game": len(scrim) / n_tg,
        "points/team-game": float(pts),
        "pass att/team-game": len(att) / n_tg,
        "completion %": float(att.complete_pass.mean() * 100),
        "pass yds/team-game": float(att.yards_gained.sum() / n_tg),
        "yards/carry": float(rush.yards_gained.mean()),
        "rush yds/team-game": float(rush.yards_gained.sum() / n_tg),
        "sack rate %": float(dropbacks.sack.mean() * 100),
        "pass TD/team-game": float(reg.pass_touchdown.sum() / n_tg),
        "rush TD/team-game": float(reg.rush_touchdown.sum() / n_tg),
        "INT/team-game": float(reg.interception.sum() / n_tg),
    }


def _sim_league_rates(result: dict, bundle) -> dict:
    t = result["totals"]
    n_team_games = 17.0 * len(bundle.teams)

    def per(stat):
        return float(t[SIDX[stat]].sum(axis=1).mean() / n_team_games)

    att = per("pass_att")
    cmp_ = per("pass_cmp")
    rush_att = per("rush_att")
    rush_yds = per("rush_yds")
    pts = float(np.mean([v.mean() for v in result["team_points"].values()]) / 17.0)

    return {
        "plays/team-game": att + rush_att + per("sack_taken"),
        "points/team-game": pts,
        "pass att/team-game": att,
        "completion %": 100.0 * cmp_ / max(att, 1e-9),
        "pass yds/team-game": per("pass_yds"),
        "yards/carry": rush_yds / max(rush_att, 1e-9),
        "rush yds/team-game": rush_yds,
        "sack rate %": 100.0 * per("sack_taken") / max(att + per("sack_taken"), 1e-9),
        "pass TD/team-game": per("pass_td"),
        "rush TD/team-game": per("rush_td"),
        "INT/team-game": per("pass_int"),
    }


def _actual_positional(season: int, scoring) -> dict:
    """Realised fantasy totals by positional cohort in a real season."""
    pw = data.player_week([season])
    pw = pw[(pw.season_type == "REG") & pw.position.isin(FANTASY_POSITIONS)]
    s = scoring
    pw = pw.assign(fp=(
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
    ))
    tot = pw.groupby(["player_id", "position"]).fp.sum().reset_index()
    out = {}
    for pos, k in (("QB", 12), ("RB", 24), ("WR", 36), ("TE", 12)):
        v = tot[tot.position == pos].fp.nlargest(k)
        out[pos] = {"top": float(v.iloc[0]), f"top{k} mean": float(v.mean()),
                    f"#{k}": float(v.iloc[-1])}
    return out


def _sim_positional(result, bundle, scoring) -> dict:
    """Expected score of the Nth-best finisher at each position.

    This must rank *within each simulated season* and then average, not average
    each player and rank the averages. The two are very different quantities.
    A real season's leading tight end is the best of thirty-two draws from
    thirty-two different distributions -- the maximum of a sample -- and the
    maximum of a sample is systematically larger than the largest mean.
    Comparing a realised leader against the highest projected mean therefore
    makes any honest model look badly pessimistic at the top of every position,
    which is exactly the artefact this avoids.
    """
    fp = fantasy_points(result["totals"], scoring)
    pt = bundle.player_table
    out = {}
    for pos, k in (("QB", 12), ("RB", 24), ("WR", 36), ("TE", 12)):
        idx = pt.index[pt.pos == pos].to_numpy()
        sub = fp[:, idx]
        # Sort descending within every replication, then average each rank.
        ranked = -np.sort(-sub, axis=1)[:, :k]
        out[pos] = {"top": float(ranked[:, 0].mean()),
                    f"top{k} mean": float(ranked.mean()),
                    f"#{k}": float(ranked[:, -1].mean())}
    return out


def _market_check(result, bundle) -> pd.DataFrame | None:
    """Where 2026 lines exist, compare simulated scoring to the posted total."""
    games = data.games()
    g = games[(games.season == bundle.season) & (games.game_type == "REG")
              & games.total_line.notna()]
    if g.empty:
        return None
    ppg = {t: float(v.mean() / 17.0) for t, v in result["team_points"].items()}
    rows = []
    for _, r in g.iterrows():
        if r.home_team not in ppg or r.away_team not in ppg:
            continue
        sim_total = ppg[r.home_team] + ppg[r.away_team]
        rows.append({"game": f"{r.away_team}@{r.home_team}", "week": int(r.week),
                     "sim_total": sim_total, "market_total": float(r.total_line),
                     "diff": sim_total - float(r.total_line)})
    return pd.DataFrame(rows) if rows else None


def run_validation(bundle, result, scoring, ref_season: int | None = None) -> None:
    ref = ref_season or (bundle.season - 1)
    con = Console() if _RICH else None

    def show(title, rows, cols):
        if _RICH:
            t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
                      title_style="bold")
            for c, j in cols:
                t.add_column(c, justify=j)
            for r in rows:
                t.add_row(*r)
            con.print(t)
        else:
            print(f"\n{title}")
            for r in rows:
                print("  " + "  ".join(str(x) for x in r))

    # ---- 1. league rates ------------------------------------------------
    from .priors import HALFLIFE_PHYSICS
    era_seasons = list(range(ref - 4, ref + 1))
    era = _weighted_actual_rates(era_seasons, bundle.season, HALFLIFE_PHYSICS)
    last = _actual_league_rates(ref)
    sim = _sim_league_rates(result, bundle)
    rows = []
    for k in era:
        e, a, s = era[k], last[k], sim[k]
        err = (s - e) / e * 100 if e else 0.0
        colour = "green" if abs(err) < 5 else ("yellow" if abs(err) < 12 else "red")
        rows.append([k, f"{s:,.2f}", f"{e:,.2f}", f"{a:,.2f}",
                     f"[{colour}]{err:+.1f}%[/]" if _RICH else f"{err:+.1f}%"])
    show(f"Engine vs reality  ·  simulated {bundle.season}", rows,
         [("metric", "left"), ("simulated", "right"),
          (f"{era_seasons[0]}-{ref} weighted", "right"), (f"{ref} only", "right"),
          ("error vs era", "right")])

    # ---- 2. positional cohorts -----------------------------------------
    pa, ps = _actual_positional(ref, scoring), _sim_positional(result, bundle, scoring)
    rows = []
    for pos in ("QB", "RB", "WR", "TE"):
        for key in pa[pos]:
            a, s = pa[pos][key], ps[pos][key]
            err = (s - a) / a * 100 if a else 0.0
            colour = "green" if abs(err) < 8 else ("yellow" if abs(err) < 18 else "red")
            rows.append([f"{pos} {key}", f"{s:,.0f}", f"{a:,.0f}",
                         f"[{colour}]{err:+.1f}%[/]" if _RICH else f"{err:+.1f}%"])
    show(f"Fantasy output by cohort  ·  {scoring.name}", rows,
         [("cohort", "left"), ("simulated", "right"), (f"{ref} actual", "right"),
          ("error", "right")])

    # ---- 3. market ------------------------------------------------------
    mk = _market_check(result, bundle)
    if mk is None or mk.empty:
        msg = "no 2026 betting lines published yet - market check skipped"
        con.print(f"\n[grey58]{msg}[/]") if _RICH else print(f"\n{msg}")
        return
    rows = [["games with lines", f"{len(mk)}"],
            ["mean simulated total", f"{mk.sim_total.mean():.1f}"],
            ["mean market total", f"{mk.market_total.mean():.1f}"],
            ["mean difference", f"{mk['diff'].mean():+.1f}"],
            ["mean absolute difference", f"{mk['diff'].abs().mean():.1f}"]]
    show("Market sanity check  ·  advisory only", rows,
         [("metric", "left"), ("value", "right")])
    if _RICH:
        con.print(
            "[grey58]The model never sees betting lines. This compares its own "
            "team scoring rates against the posted totals for the games that "
            "have them; a gap is where the model disagrees with the market, "
            "which is the point, but a large one is worth investigating.[/]"
        )
