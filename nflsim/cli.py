"""Command line interface.

    python -m nflsim build                     fit the model, cache the bundle
    python -m nflsim simulate --sims 10000     run seasons, cache the results
    python -m nflsim board --top 80            print the draft board
    python -m nflsim projections --pos WR      per-position projections
    python -m nflsim teams                     team wins, scoring, coaching
    python -m nflsim export --out projections  write CSVs
    python -m nflsim validate                  check the engine against reality
    python -m nflsim compare A B               head-to-head between two players
"""

from __future__ import annotations

import argparse
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
    return {
        "totals": z["totals"], "games_played": z["games_played"],
        "team_points": z["team_points"].item(), "team_wins": z["team_wins"].item(),
        "n_sims": int(z["n_sims"]),
    }


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
    np.savez(
        tmp, totals=res["totals"], games_played=res["games_played"],
        team_points=np.array(res["team_points"], dtype=object),
        team_wins=np.array(res["team_wins"], dtype=object),
        n_sims=res["n_sims"],
    )
    tmp.replace(RESULT)
    print(f"saved {args.sims:,} simulated seasons to {RESULT}")


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


def cmd_backtest(args):
    """Project a season that has already happened, and score the projection."""
    from .backtest import run_backtest, score
    sc = _scoring(args)
    df = run_backtest(args.season, n_sims=args.sims, scoring=sc, seed=args.seed)
    # Persist before scoring: the run costs minutes, and a formatting problem
    # in the report should not throw the results away.
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"wrote {args.out}")
    score(df, sc, top_n=args.top)


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

    v = common(sub.add_parser("validate", help="check the engine against reality"))
    v.set_defaults(func=cmd_validate)

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
