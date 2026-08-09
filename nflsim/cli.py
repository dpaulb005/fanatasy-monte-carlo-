"""Command line interface.

    python -m nflsim build                     fit the model, cache the bundle
    python -m nflsim simulate --sims 10000     run seasons, cache the results
    python -m nflsim board --top 80            print the draft board
    python -m nflsim draft --interactive       mock draft against ADP bots
    python -m nflsim adp --save espn.csv       fetch and freeze the ADP board
    python -m nflsim projections --pos WR      per-position projections
    python -m nflsim teams                     team wins, scoring, coaching
    python -m nflsim export --out projections  write CSVs
    python -m nflsim validate                  check the engine against reality
    python -m nflsim compare A B               head-to-head between two players
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import analysis, board, build as build_mod, season as season_mod
from .config import (PBP_SEASONS, SCORING_PRESETS, TARGET_SEASON, League,
                     SimConfig)

ART = Path("artifacts")
BUNDLE = ART / "bundle.pkl"
RESULT = ART / "result.npz"


def _league(args) -> League:
    return League(teams=args.teams, qb=args.qb, rb=args.rb, wr=args.wr,
                  te=args.te, flex=args.flex, superflex=args.superflex)


def _scoring(args):
    return SCORING_PRESETS[args.scoring]


def _load_bundle() -> build_mod.Bundle:
    if not BUNDLE.exists():
        sys.exit("no model bundle found - run `python -m nflsim build` first")
    return build_mod.Bundle.load(BUNDLE)


def _load_result():
    if not RESULT.exists():
        sys.exit("no simulation found - run `python -m nflsim simulate` first")
    z = np.load(RESULT, allow_pickle=True)
    out = {
        "totals": z["totals"], "games_played": z["games_played"],
        "team_points": z["team_points"].item(), "team_wins": z["team_wins"].item(),
        "n_sims": int(z["n_sims"]),
    }
    # Weekly capture is optional; older result files will not have it.
    if "weekly_stats" in z.files:
        out.update({
            "weekly_stats": z["weekly_stats"], "weekly_fp": z["weekly_fp"],
            "weekly_played": z["weekly_played"],
            "week_opponent": z["week_opponent"].item(),
            "week_quantiles": list(z["week_quantiles"]),
        })
    # Weekly stat ranges are newer than the weekly means; a result file written
    # before they existed still loads.
    if "weekly_stat_q" in z.files:
        out.update({
            "weekly_stat_q": z["weekly_stat_q"],
            "weekly_fp_live": z["weekly_fp_live"],
            "week_stat_quantiles": list(z["week_stat_quantiles"]),
        })
    return out


def _frame(bundle, result, args) -> pd.DataFrame:
    sc = _scoring(args)
    df = analysis.summarise(result, bundle, sc)
    return analysis.add_value(df, result, bundle, sc, _league(args))


# --------------------------------------------------------------------------

def cmd_build(args):
    ART.mkdir(exist_ok=True)
    seasons = range(args.from_season, TARGET_SEASON)
    b = build_mod.build(season=TARGET_SEASON, pbp_seasons=seasons)
    b.save(BUNDLE)
    print(f"saved model to {BUNDLE}")


def cmd_simulate(args):
    ART.mkdir(exist_ok=True)
    b = _load_bundle()
    res = season_mod.run_season(b, n_sims=args.sims, seed=args.seed,
                                use_injuries=not args.no_injuries)
    # Write to a temporary path and rename into place. The result is hundreds
    # of megabytes and takes a noticeable time to land; without this, anything
    # reading the file mid-write gets a truncated archive rather than an
    # honest "not finished yet".
    # The suffix must stay .npz: np.savez appends it when the name lacks it,
    # which would write beside the path we then try to rename.
    tmp = RESULT.with_suffix(".part.npz")
    payload = dict(
        totals=res["totals"], games_played=res["games_played"],
        team_points=np.array(res["team_points"], dtype=object),
        team_wins=np.array(res["team_wins"], dtype=object),
        n_sims=res["n_sims"],
    )
    if "weekly_stats" in res:
        payload.update(
            weekly_stats=res["weekly_stats"], weekly_fp=res["weekly_fp"],
            weekly_played=res["weekly_played"],
            weekly_stat_q=res["weekly_stat_q"],
            weekly_fp_live=res["weekly_fp_live"],
            week_stat_quantiles=np.array(res["week_stat_quantiles"]),
            week_opponent=np.array(res["week_opponent"], dtype=object),
            week_quantiles=np.array(res["week_quantiles"]),
        )
    np.savez(tmp, **payload)
    tmp.replace(RESULT)
    print(f"saved {args.sims:,} simulated seasons to {RESULT}")


def _adp_pool(args, bundle, proj):
    """The board the room drafts from, aligned to the model's players."""
    from . import adp as adp_mod
    from . import draft_ui

    src = "csv" if args.adp else args.source
    table = adp_mod.load(source=args.source, season=TARGET_SEASON,
                         path=args.adp, scoring_name=_scoring(args).name)
    aligned, unmatched = adp_mod.attach(table, bundle.player_table)
    pool = adp_mod.fill_undrafted(aligned, proj.overall_rank)
    # `table["asof"]`, not `table.asof`: DataFrame.asof is a method, and
    # attribute access finds it before the column.
    asof = str(table["asof"].iloc[0]) if "asof" in table else None
    draft_ui.show_source_note(src, len(table), len(unmatched), asof)
    if len(unmatched):
        # Loud, because an unmatched name is a player the bots can never take
        # and you can never draft -- a silent hole in the board.
        top = unmatched.nsmallest(6, "adp")
        print("  unmatched on the board: " + ", ".join(
            f"{r.player} ({r.pos}, ADP {r.adp:.0f})" for _, r in top.iterrows())
            + (f" and {len(unmatched) - len(top)} more" if len(unmatched) > len(top) else ""),
            file=sys.stderr)
    return pool


def cmd_adp(args):
    """Fetch a board and optionally freeze it to CSV."""
    from . import adp as adp_mod
    table = adp_mod.load(source=args.source, season=TARGET_SEASON,
                         path=args.adp, scoring_name=_scoring(args).name)
    if args.save:
        table.to_csv(args.save, index=False)
        print(f"wrote {len(table)} rows to {args.save}")
    cols = [c for c in ("adp", "player", "pos", "team", "adp_raw", "adp_sd")
            if c in table]
    print(table[cols].head(args.top).to_string(index=False))


def _draft_rooms(args, bundle, res, proj, cfg, pool, on_clock):
    """Repeat the draft in many rooms and report the spread.

    One draft is one sample from a very noisy process: the same strategy in the
    same seat gets a different board depending on how eleven other people's
    perceptions happened to fall. Reporting the title odds from a single room
    as if it measured a strategy is the mistake this exists to prevent, so the
    comparison is made across rooms and the run-to-run spread is printed
    alongside the mean.
    """
    from . import draft as draft_mod

    seat = cfg.seat - 1
    rows = []
    for i in range(args.rooms):
        c = replace(cfg, seed=cfg.seed + i)
        picks = draft_mod.run_draft(pool, c, on_clock=on_clock)
        table = draft_mod.grade(picks, res, bundle, _scoring(args), c)
        mine = table[table.team_idx == seat].iloc[0]
        rows.append({"room": i + 1, "p_title": mine.p_title,
                     "p_playoff": mine.p_playoff, "points": mine.points,
                     "finish": mine.mean_finish})
    df = pd.DataFrame(rows)
    strat = "interactive" if args.interactive else args.strategy
    print(f"\n{args.rooms} draft rooms  ·  seat {cfg.seat}  ·  strategy "
          f"{strat}  ·  {res['n_sims']:,} simulated seasons each")
    for col, label, pct in (("p_title", "title", True),
                            ("p_playoff", "playoff", True),
                            ("finish", "mean finish", False),
                            ("points", "starter points", False)):
        v = df[col].to_numpy()
        scale, suffix = (100.0, "%") if pct else (1.0, "")
        # Standard error over rooms, which is the quantity a single-room
        # readout hides entirely.
        se = v.std(ddof=1) / np.sqrt(len(v)) * scale
        print(f"  {label:>15}: {v.mean()*scale:7.2f}{suffix}"
              f"  ±{se:.2f}   (range {v.min()*scale:.2f}-{v.max()*scale:.2f})")
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"wrote {args.out}")


def cmd_draft(args):
    from . import draft as draft_mod
    from . import draft_ui

    b, res = _load_bundle(), _load_result()
    proj = _frame(b, res, args)
    lg = _league(args)
    cfg = draft_mod.DraftConfig(league=lg, rounds=args.rounds, seat=args.seat,
                                seed=args.seed)
    pool = _adp_pool(args, b, proj)

    engine = draft_mod.ValueEngine(res, b, _scoring(args), lg)

    def take(state, gindex):
        return int(np.flatnonzero(state.pool.index == gindex)[0])

    on_clock = None
    if args.interactive:
        on_clock = lambda state: draft_ui.prompt(state, proj, engine)  # noqa: E731
    elif args.strategy == "value":
        # Draft the seat that maximises expected starting lineup points, not
        # the one that maximises value over replacement. The difference is
        # roster construction: VOR will happily take a sixth running back
        # because he is the best player left, and marginal value will not,
        # because he cannot get into the lineup.
        on_clock = lambda state: take(state, engine.gains(state, proj).index[0])  # noqa: E731
    elif args.strategy == "vor":
        # The naive control: best player left by value over replacement,
        # ignoring what the roster already has.
        def on_clock(state):
            return take(state, proj.reindex(state.available().index).vor.idxmax())

    if args.rooms > 1:
        return _draft_rooms(args, b, res, proj, cfg, pool, on_clock)

    picks = draft_mod.run_draft(pool, cfg, on_clock=on_clock)
    picks = draft_mod.pick_value(picks, proj)
    table = draft_mod.grade(picks, res, b, _scoring(args), cfg)

    print()
    draft_ui.show_league(table, res["n_sims"])
    draft_ui.league_note(res["n_sims"],
                         None if args.interactive else args.strategy)
    you = cfg.seat - 1
    draft_ui.show_roster(picks, you, proj,
                         f"Your roster  ·  seat {cfg.seat} of {lg.teams}")
    if args.show_team is not None:
        draft_ui.show_roster(picks, args.show_team - 1, proj,
                             f"Team {args.show_team}")
    if args.out:
        picks.to_csv(args.out, index=False)
        table.to_csv(args.out.replace(".csv", "") + "_league.csv", index=False)
        print(f"wrote {args.out}")


def cmd_why(args):
    """Print the chain that produced one player's projection."""
    from . import explain as ex
    b, res = _load_bundle(), _load_result()
    proj = _frame(b, res, args)
    bl = build_mod.fit_rank_baselines(TARGET_SEASON)
    c = ex.chain(args.player, b, proj, bl)
    p, f = c["projection"], c["fitted"]

    print(f"\n{c['name']}  ·  {c['pos']} {c['team']}  ·  age {c['age']:.1f}  ·  "
          f"depth {c['depth']}  ·  confidence {c['conf']:.2f}")
    print(f"  projected {p.points:.0f} pts  ({p.ppg:.1f}/gm over {p.games:.1f} games)"
          f"  ·  {p.pos}{int(p.pos_rank)}  ·  VOR {p.vor:.0f}")

    if len(c["history"]):
        print("\n  what he actually did")
        h = c["history"]
        cols = [x for x in ("team", "games", "targets", "tgt_share", "rec",
                            "rec_yds", "rec_td", "carries", "rush_share",
                            "rush_yds", "rush_td", "ppg") if x in h]
        print(h[cols].to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n  how the share was built")
    for key, label in (("target_share", "target share"), ("rush_share", "rush share")):
        last = c.get("last", {}).get(key)
        wt = c.get("weighted", {}).get(key)
        base = c.get("baseline", {}).get(key)
        if wt is None or not np.isfinite(wt):
            continue
        # `base` can legitimately be 0.0 -- a truthiness test would silently
        # drop the shrinkage line for a position with no share of that stat.
        has_base = base is not None and np.isfinite(base)
        print(f"    {label}")
        if last is not None and np.isfinite(last):
            print(f"      last season            {last:.4f}")
        print(f"      recency-weighted       {wt:.4f}"
              f"   (weights {np.round(c['weights'][key], 3)}, oldest first)")
        if has_base:
            print(f"      depth-{c['depth']} baseline        {base:.4f}")
            print(f"      shrinkage blend        "
                  f"{c['conf'] * wt + (1 - c['conf']) * base:.4f}")
        print(f"      handed to the engine   {f[key]:.4f}   <- after team normalisation")

    print(f"\n  red zone      rz target share {f['rz_target_share']:.4f}   "
          f"goal-line targets {f['gl_target_share']:.4f}   "
          f"goal-line carries {f['gl_rush_share']:.4f}")
    print(f"  efficiency    aDOT {f['adot']:.2f}   YAC {f['yac']:.2f}   "
          f"catch over exp {f['catch_oe']:+.3f}   YPC over exp {f['ypc_oe']:+.3f}")
    print(f"  availability  injury rate {c['injury_rate']:.4f}/wk   "
          f"personal durability multiplier {c['avail_mult']:.3f}")

    if not args.no_redzone:
        try:
            rz = ex.redzone_conversion([args.player])
            if len(rz):
                r = rz.iloc[0]
                print(f"\n  touchdown conversion (context only -- the model holds this\n"
                      f"  constant within a position, because it does not persist):\n"
                      f"    {int(r.rz_targets)} red-zone targets, {int(r.rz_td)} TD, "
                      f"rate {r.rate:.3f} vs league {r.league_rate:.3f} "
                      f"({r.vs_league*100:+.0f}%)")
        except Exception as exc:                       # noqa: BLE001
            print(f"  (red-zone split unavailable: {exc})")

    print("\n  the room")
    print(c["room"].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print()


def cmd_chart(args):
    """Render the top of the board to a PNG."""
    from . import chart as chart_mod
    b, res = _load_bundle(), _load_result()
    df = _frame(b, res, args)
    if args.pos:
        want = {p.strip().upper() for p in args.pos.split(",")}
        df = df[df.pos.isin(want)]
    lg = _league(args)
    out = chart_mod.top_players(
        df, args.out, n=args.top, scoring_name=_scoring(args).name,
        n_sims=res["n_sims"], league_desc=f"{lg.teams}-team", by=args.by)
    print(f"wrote {out}")


def cmd_room(args):
    """Whose fitted usage leans on somebody else being hurt."""
    from . import room as room_mod
    from .board import _RICH, _console

    seasons = range(TARGET_SEASON - args.lookback, TARGET_SEASON)
    split = room_mod.usage_split(seasons, target=TARGET_SEASON)
    if args.team:
        split = split[split.team == args.team.upper()]
    if args.pos:
        want = {p.strip().upper() for p in args.pos.split(",")}
        split = split[split.pos.isin(want)]

    lt = room_mod.league_table(split)
    if len(lt) and not args.team and not args.pos:
        print(f"\nOpportunity share when the room is whole vs depleted, "
              f"{seasons.start}-{seasons.stop - 1}:")
        for _, r in lt.iterrows():
            print(f"  {r.pos}: healthy {r.healthy_share*100:5.2f}%   "
                  f"depleted {r.depleted_share*100:5.2f}%   "
                  f"fitted {r.pooled*100:5.2f}%   "
                  f"of which vacated {r.inflation*100:+.2f}pp "
                  f"({r.inflation_pct*100:.0f}% of the baseline)   n={int(r.players)}")

    f = room_mod.flags(split, min_inflation=args.min_inflation).head(args.top)
    if not len(f):
        print("\nnothing above the threshold")
        return

    title = ("Usage that rests on a depleted room  ·  "
             f"{seasons.start}-{seasons.stop - 1}  ·  "
             "fitted share vs the share he saw with the room whole")
    if not _RICH:
        print("\n" + title)
        print(f[["name", "pos", "team", "depth", "games", "healthy_games",
                 "healthy_share", "depleted_share", "pooled",
                 "inflation"]].to_string(index=False))
    else:
        from rich import box
        from rich.table import Table
        from .board import POS_STYLE, _fmt
        t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
                  title_style="bold", pad_edge=False)
        for name, just, width in (("#", "right", 3), ("Player", "left", 21),
                                  ("Pos", "center", 4), ("Tm", "center", 3),
                                  ("Dep", "right", 3), ("G", "right", 3),
                                  ("Gh", "right", 3), ("Healthy", "right", 8),
                                  ("Depleted", "right", 9), ("Fitted", "right", 7),
                                  ("Vacated", "right", 8)):
            t.add_column(name, justify=just, width=width if name != "Player" else None,
                         min_width=width if name == "Player" else None, no_wrap=True)
        for i, (_, r) in enumerate(f.iterrows(), start=1):
            t.add_row(str(i), str(r["name"]),
                      f"[{POS_STYLE.get(r.pos, 'white')}]{r.pos}[/]", str(r.team),
                      _fmt(r.depth, 0), str(int(r.games)), str(int(r.healthy_games)),
                      f"{r.healthy_share*100:.2f}%", f"{r.depleted_share*100:.2f}%",
                      f"{r.pooled*100:.2f}%",
                      f"[bold]{r.inflation*100:+.2f}pp[/]")
        _console().print(t)

    note = ("Diagnostic only — the projections do not correct for this. "
            "The walk-forward test is in docs/ROOM.md and it did not reach "
            "significance, so nothing here is subtracted from anyone.")
    if _RICH:
        _console().print(f"  [grey58]{note}[/]")
    else:
        print("  " + note)
    if args.out:
        split.to_csv(args.out, index=False)
        print(f"wrote {args.out}")


def cmd_board(args):
    b, res = _load_bundle(), _load_result()
    df = _frame(b, res, args)
    if getattr(args, "team", None):
        df = df[df.team == args.team.upper()]
    lg = _league(args)
    board.draft_board(df, n=args.top, scoring_name=_scoring(args).name,
                      league_desc=f"{lg.teams}-team")
    board.summary_note(df, res["n_sims"], _scoring(args).name)


def cmd_projections(args):
    b, res = _load_bundle(), _load_result()
    df = _frame(b, res, args)
    if getattr(args, "team", None):
        df = df[df.team == args.team.upper()]
    for pos in (args.pos.split(",") if args.pos else ["QB", "RB", "WR", "TE"]):
        board.positional(df, pos.strip().upper(), n=args.top,
                         scoring_name=_scoring(args).name)


def cmd_html(args):
    """Write a self-contained HTML report of players and their weeks."""
    from .report_html import generate
    b, res = _load_bundle(), _load_result()
    if "weekly_fp" not in res:
        print("note: this result file has no weekly capture - re-run `simulate` "
              "to get game-by-game detail", file=sys.stderr)
    path = generate(b, res, _frame(b, res, args), _scoring(args), Path(args.out),
                    league=_league(args))
    print(f"wrote {path}  ({path.stat().st_size/1e6:.1f} MB)")


def cmd_factors(args):
    """Replay controlled scenarios to attribute player outcomes to context."""
    from .experiments import generate_html, run_factor_experiment
    b = _load_bundle()
    frame, meta = run_factor_experiment(
        b, _scoring(args), n_sims=args.sims, seed=args.seed,
    )
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False)
    html_path = generate_html(frame, meta, Path(args.out))
    print(f"wrote {csv_path} and {html_path}")


def cmd_outliers(args):
    """Top projected seasons, and where the model departs from last year."""
    from .outliers import report
    b, res = _load_bundle(), _load_result()
    report(_frame(b, res, args), b, _scoring(args), top=args.top,
           n_outliers=args.outliers)


def cmd_team(args):
    """Full deep dive on one team."""
    from .team_report import report
    b, res = _load_bundle(), _load_result()
    report(b, res, _scoring(args), args.team.upper(), _frame(b, res, args))


def cmd_teams(args):
    b, res = _load_bundle(), _load_result()
    board.teams(analysis.team_summary(res, b), b.coach_table)


def cmd_export(args):
    b, res = _load_bundle(), _load_result()
    df = _frame(b, res, args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "projections.csv", index=False)
    analysis.team_summary(res, b).to_csv(out / "teams.csv", index=False)
    b.coach_table.to_csv(out / "coaching.csv", index=False)
    b.strength_table.to_csv(out / "team_strength.csv", index=False)
    df.to_parquet(out / "projections.parquet", index=False)
    print(f"wrote projections.csv, teams.csv, coaching.csv, team_strength.csv "
          f"and projections.parquet to {out}/")


def cmd_compare(args):
    b, res = _load_bundle(), _load_result()
    sc = _scoring(args)
    fp = analysis.fantasy_points(res["totals"], sc)
    pt = b.player_table
    picks = []
    for name in (args.a, args.b):
        hit = pt.index[pt.name.str.lower() == name.lower()]
        if not len(hit):
            hit = pt.index[pt.name.str.lower().str.contains(name.lower(), regex=False)]
        if not len(hit):
            sys.exit(f"no player matching {name!r}")
        picks.append(int(hit[0]))
    ia, ib = picks
    a, bb = fp[:, ia], fp[:, ib]
    na, nb = pt.loc[ia, "name"], pt.loc[ib, "name"]
    print(f"\n{na} vs {nb}   ({res['n_sims']:,} simulated seasons, {sc.name})\n")
    for label, v in ((na, a), (nb, bb)):
        print(f"  {label:<24} mean {v.mean():7.1f}   p10 {np.percentile(v,10):7.1f}"
              f"   p90 {np.percentile(v,90):7.1f}")
    print(f"\n  {na} outscores {nb} in {100*(a>bb).mean():.1f}% of seasons")
    print(f"  correlation between them: {np.corrcoef(a, bb)[0,1]:+.3f}")


def cmd_validate(args):
    """Compare simulated rates against the real league, and against the market."""
    from .validate import run_validation
    run_validation(_load_bundle(), _load_result(), _scoring(args))


def cmd_calibrate(args):
    """Fit conformal interval widening on one season, test it on another."""
    from .backtest import run_backtest
    from . import calibrate as cal_mod
    sc = _scoring(args)

    def frame(season, tag):
        cache = ART / f"backtest_{season}.csv"
        if cache.exists() and not args.refresh:
            print(f"reusing cached {tag} backtest for {season}")
            return pd.read_csv(cache)
        df = run_backtest(season, n_sims=args.sims, scoring=sc, seed=args.seed)
        ART.mkdir(exist_ok=True)
        df.to_csv(cache, index=False)
        return df

    fit_df = frame(args.fit_season, "calibration")
    cal = cal_mod.fit(fit_df, args.fit_season, cohort=args.cohort)
    out = ART / "conformal.json"
    cal.save(out)

    test_df = frame(args.test_season, "evaluation")
    cov = cal_mod.coverage(test_df, cal, cohort=args.cohort)
    bypos = cal_mod.coverage_by_position(test_df, cal, cohort=args.cohort)

    print(f"\nfitted on {args.fit_season}, evaluated on {args.test_season} "
          f"(top {args.cohort} by projection)\n")
    print("interval coverage")
    for _, r in cov.iterrows():
        print(f"  {r['band']:>4} band (nominal {r['nominal']*100:.0f}%): "
              f"raw {r['raw']*100:5.1f}%  ->  calibrated {r['calibrated']*100:5.1f}%"
              f"   mean width {r['raw_width']:.0f} -> {r['cal_width']:.0f}")
    print("\n80% band by position")
    for _, r in bypos.iterrows():
        print(f"  {r['pos']:<3} n={int(r['n']):<4} raw {r['raw']*100:5.1f}%  ->  "
              f"calibrated {r['calibrated']*100:5.1f}%   widening x{r['factor']:.2f}")
    print(f"\nsaved {out}")


def cmd_backtest(args):
    """Project a season that has already happened, and score the projection."""
    from .backtest import (run_backtest, score, score_error_decomposition,
                           score_matched)
    sc = _scoring(args)
    df = run_backtest(args.season, n_sims=args.sims, scoring=sc, seed=args.seed)
    # Persist before scoring: the run costs minutes, and a formatting problem
    # in the report should not throw the results away.
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"wrote {args.out}")
    score(df, sc, top_n=args.top)
    score_matched(df, sc)
    score_error_decomposition(df, top_n=args.top)


# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(prog="nflsim",
                                description="Monte Carlo NFL season simulation "
                                            "for fantasy projection")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--scoring", default="ppr", choices=sorted(SCORING_PRESETS))
        sp.add_argument("--teams", type=int, default=12)
        sp.add_argument("--qb", type=int, default=1)
        sp.add_argument("--rb", type=int, default=2)
        sp.add_argument("--wr", type=int, default=3)
        sp.add_argument("--te", type=int, default=1)
        sp.add_argument("--flex", type=int, default=1)
        sp.add_argument("--superflex", type=int, default=0)
        return sp

    b = sub.add_parser("build", help="fit the model from source data")
    b.add_argument("--from-season", type=int, default=PBP_SEASONS[0],
                   help="first play-by-play season to fit on")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("simulate", help="run simulated seasons")
    s.add_argument("--sims", type=int, default=SimConfig.n_sims)
    s.add_argument("--seed", type=int, default=SimConfig.seed)
    s.add_argument("--no-injuries", action="store_true",
                   help="assume every player is available all season")
    s.set_defaults(func=cmd_simulate)

    d = common(sub.add_parser("board", help="print the draft board"))
    d.add_argument("--top", type=int, default=60)
    d.add_argument("--team", default=None, help="restrict to one team, e.g. PHI")
    d.set_defaults(func=cmd_board)

    pr = common(sub.add_parser("projections", help="per-position projections"))
    pr.add_argument("--pos", default=None, help="e.g. WR or QB,TE")
    pr.add_argument("--top", type=int, default=24)
    pr.add_argument("--team", default=None, help="restrict to one team, e.g. PHI")
    pr.set_defaults(func=cmd_projections)

    t = common(sub.add_parser("teams", help="team wins, scoring and coaching"))
    t.set_defaults(func=cmd_teams)

    h = common(sub.add_parser(
        "html", help="self-contained HTML report: players and week-by-week detail"))
    h.add_argument("--out", default="report.html")
    h.set_defaults(func=cmd_html)

    fx = common(sub.add_parser(
        "factors", help="controlled simulations: injury, role, scheme and team context"))
    fx.add_argument("--sims", type=int, default=2000)
    fx.add_argument("--seed", type=int, default=SimConfig.seed)
    fx.add_argument("--out", default="factor-comparison.html")
    fx.add_argument("--csv", default="factor-comparison.csv")
    fx.set_defaults(func=cmd_factors)

    o = common(sub.add_parser(
        "outliers", help="top projected seasons and biggest movers vs last year"))
    o.add_argument("--top", type=int, default=25)
    o.add_argument("--outliers", type=int, default=15)
    o.set_defaults(func=cmd_outliers)

    tr = common(sub.add_parser(
        "team", help="full deep dive on one team: identity, usage, stats, correlations"))
    tr.add_argument("--team", required=True, help="team abbreviation, e.g. PHI")
    tr.set_defaults(func=cmd_team)

    e = common(sub.add_parser("export", help="write CSV / parquet output"))
    e.add_argument("--out", default="projections")
    e.set_defaults(func=cmd_export)

    c = common(sub.add_parser("compare", help="head-to-head between two players"))
    c.add_argument("a")
    c.add_argument("b")
    c.set_defaults(func=cmd_compare)

    def with_adp(sp):
        sp.add_argument("--source", default="espn",
                        choices=("espn", "fantasypros"),
                        help="where the market board comes from")
        sp.add_argument("--adp", default=None,
                        help="use this CSV instead of fetching (overrides --source)")
        return sp

    dr = with_adp(common(sub.add_parser(
        "draft", help="snake draft against bots that follow ADP")))
    dr.add_argument("--rounds", type=int, default=15)
    dr.add_argument("--seat", type=int, default=1, help="your draft slot")
    dr.add_argument("--seed", type=int, default=SimConfig.seed)
    dr.add_argument("--interactive", action="store_true",
                    help="draft your own seat from the terminal")
    dr.add_argument("--strategy", default="value",
                    choices=("value", "vor", "adp"),
                    help="how your seat picks when not interactive: marginal "
                         "lineup value, raw VOR, or the market board")
    dr.add_argument("--rooms", type=int, default=1,
                    help="repeat the draft in N rooms and report the spread "
                         "instead of one room's board")
    dr.add_argument("--show-team", type=int, default=None,
                    help="also print this team's roster, 1-based")
    dr.add_argument("--out", default=None, help="write the picks to CSV")
    dr.set_defaults(func=cmd_draft)

    ad = with_adp(common(sub.add_parser(
        "adp", help="show the market board the draft bots use")))
    ad.add_argument("--top", type=int, default=40)
    ad.add_argument("--save", default=None,
                    help="freeze the fetched board to this CSV")
    ad.set_defaults(func=cmd_adp)

    wy = common(sub.add_parser(
        "why", help="show the chain behind one player's projection"))
    wy.add_argument("player")
    wy.add_argument("--no-redzone", action="store_true",
                    help="skip the play-by-play red-zone split (much faster)")
    wy.set_defaults(func=cmd_why)

    ch = common(sub.add_parser("chart", help="render the board to a PNG"))
    ch.add_argument("--top", type=int, default=30)
    ch.add_argument("--pos", default=None, help="e.g. RB or RB,WR")
    ch.add_argument("--by", default="vor", choices=("vor", "points"),
                    help="what to rank by")
    ch.add_argument("--out", default="top-players.png")
    ch.set_defaults(func=cmd_chart)

    rm = common(sub.add_parser(
        "room", help="whose fitted usage rests on injuries around him"))
    rm.add_argument("--top", type=int, default=25)
    rm.add_argument("--pos", default=None, help="e.g. RB or RB,WR")
    rm.add_argument("--team", default=None, help="e.g. NYG")
    rm.add_argument("--lookback", type=int, default=4,
                    help="seasons of history, matching fit_usage")
    rm.add_argument("--min-inflation", type=float, default=0.02,
                    help="minimum share points of vacated work to list")
    rm.add_argument("--out", default=None, help="write the full split to CSV")
    rm.set_defaults(func=cmd_room)

    v = common(sub.add_parser("validate", help="check the engine against reality"))
    v.set_defaults(func=cmd_validate)

    cb = common(sub.add_parser(
        "calibrate",
        help="fit conformal interval widening on one season, test on another"))
    cb.add_argument("--fit-season", type=int, default=TARGET_SEASON - 2)
    cb.add_argument("--test-season", type=int, default=TARGET_SEASON - 1)
    cb.add_argument("--sims", type=int, default=3000)
    cb.add_argument("--seed", type=int, default=11)
    cb.add_argument("--cohort", type=int, default=200)
    cb.add_argument("--refresh", action="store_true",
                    help="re-run backtests even if cached")
    cb.set_defaults(func=cmd_calibrate)

    bt = common(sub.add_parser(
        "backtest", help="project a past season out-of-sample and score it"))
    bt.add_argument("--season", type=int, default=TARGET_SEASON - 1)
    bt.add_argument("--sims", type=int, default=2000)
    bt.add_argument("--seed", type=int, default=11)
    bt.add_argument("--top", type=int, default=200)
    bt.add_argument("--out", default=None, help="write the scored table to CSV")
    bt.set_defaults(func=cmd_backtest)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
