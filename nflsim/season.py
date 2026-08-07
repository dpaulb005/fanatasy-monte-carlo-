"""Run whole seasons.

Availability is drawn first, for every player, week and replication, and then
the schedule is played out game by game. Doing it in that order matters: the
engine needs to know who is on the field *before* it allocates usage, and an
injury has to persist across the weeks that follow it rather than being
redrawn independently each Sunday.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from .build import Bundle
from .engine import NSTAT, STATS, GameSimulator


def coerce_wind(raw) -> float:
    """Resolve a schedule's wind field to a usable number.

    Wind is blank for indoor games and for any game whose conditions were never
    recorded. The obvious idiom `float(raw) or 0.0` is a trap: nan is truthy in
    Python, so it returns nan rather than the fallback, and a nan wind
    propagates through every completion probability in the game -- turning every
    pass incomplete without raising anything.
    """
    try:
        w = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return w if np.isfinite(w) else 0.0


def draw_availability(bundle: Bundle, n_sims: int, rng: np.random.Generator,
                      weeks: int = 18) -> np.ndarray:
    """(weeks, S, P) availability, with absences that persist.

    Each week a healthy player faces his own hazard of a new absence; when one
    starts, its length is drawn from a geometric distribution with his
    positional mean, and he is unavailable until it runs out.
    """
    P = len(bundle.player_table)
    rate = bundle.injury_rate[None, :]
    dur = np.maximum(bundle.injury_dur[None, :], 1.0)

    avail = np.ones((weeks, n_sims, P), dtype=np.float32)
    out_for = np.zeros((n_sims, P), dtype=np.int16)

    for w in range(weeks):
        healthy = out_for <= 0
        new_hit = healthy & (rng.random((n_sims, P)) < rate)
        if new_hit.any():
            # Geometric duration: mean `dur`, minimum one game.
            u = rng.random((n_sims, P))
            length = 1 + np.floor(np.log(np.maximum(u, 1e-12)) / np.log(
                np.clip(1.0 - 1.0 / dur, 1e-6, 1 - 1e-6)))
            out_for = np.where(new_hit, length.astype(np.int16), out_for)
        avail[w] = (out_for <= 0).astype(np.float32)
        out_for = np.maximum(out_for - 1, 0)
    return avail


def draw_role_factors(bundle: Bundle, n_sims: int, rng: np.random.Generator,
                      enabled: bool = True) -> np.ndarray:
    """(S, P) multipliers on each player's usage share, one draw per season.

    Drawn once per simulated season, not per game: a player who wins a larger
    role in camp keeps it for the year. Log-normal, centred so the expected
    multiplier is exactly one, which leaves projected means intact while
    opening up the tails that a fixed-share model cannot produce.
    """
    P = len(bundle.player_table)
    if not enabled:
        return np.ones((n_sims, P), dtype=np.float32)
    sigma = bundle.player_table.pos.map(bundle.role_sigma).fillna(0.0).to_numpy(float)
    z = rng.standard_normal((n_sims, P))
    # exp(sigma*z - sigma^2/2) has mean 1 for every sigma.
    return np.exp(sigma[None, :] * z - 0.5 * sigma[None, :] ** 2).astype(np.float32)


def run_season(bundle: Bundle, n_sims: int, seed: int, verbose: bool = True,
               use_injuries: bool = True, use_role_variance: bool = True) -> dict:
    """Simulate the full regular season `n_sims` times."""
    rng = np.random.default_rng(seed)
    P = len(bundle.player_table)
    sched = bundle.schedule
    weeks = int(sched.week.max())

    if use_injuries:
        avail = draw_availability(bundle, n_sims, rng, weeks)
    else:
        avail = np.ones((weeks, n_sims, P), dtype=np.float32)
    role = draw_role_factors(bundle, n_sims, rng, enabled=use_role_variance)

    totals = np.zeros((NSTAT, n_sims, P), dtype=np.float32)
    games_played = np.zeros((n_sims, P), dtype=np.float32)
    team_points = {t: np.zeros((n_sims,), dtype=np.float32) for t in bundle.teams}
    team_wins = {t: np.zeros((n_sims,), dtype=np.float32) for t in bundle.teams}

    sim = GameSimulator(bundle.physics, rng, n_sims)
    t0 = time.time()
    n_games = len(sched)

    for gi, row in enumerate(sched.itertuples(index=False)):
        home, away = row.home_team, row.away_team
        if home not in bundle.teams or away not in bundle.teams:
            continue
        hm, aw = bundle.teams[home], bundle.teams[away]
        w = int(row.week) - 1

        av_h = avail[w][:, hm.gidx]
        av_a = avail[w][:, aw.gidx]

        roof = getattr(row, "roof", "outdoors")
        weather = {
            "wind": coerce_wind(getattr(row, "wind", np.nan)),
            "outdoors": bool(pd.isna(roof) or str(roof) in ("outdoors", "open")),
        }

        res = sim.run(hm, aw, av_h, av_a, weather, home_field=1.6,
                      role_home=role[:, hm.gidx], role_away=role[:, aw.gidx])

        totals[:, :, hm.gidx] += res["home_stats"]
        totals[:, :, aw.gidx] += res["away_stats"]
        games_played[:, hm.gidx] += av_h
        games_played[:, aw.gidx] += av_a

        hs, as_ = res["home_score"], res["away_score"]
        team_points[home] += hs
        team_points[away] += as_
        team_wins[home] += (hs > as_).astype(np.float32)
        team_wins[away] += (as_ > hs).astype(np.float32)

        if verbose and (gi + 1) % 25 == 0:
            el = time.time() - t0
            eta = el / (gi + 1) * (n_games - gi - 1)
            print(f"  game {gi+1}/{n_games}  elapsed {el:5.1f}s  eta {eta:5.1f}s",
                  file=sys.stderr, flush=True)

    if verbose:
        print(f"  simulated {n_games} games x {n_sims} seasons in "
              f"{time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    return {
        "totals": totals,
        "games_played": games_played,
        "team_points": team_points,
        "team_wins": team_wins,
        "n_sims": n_sims,
    }
