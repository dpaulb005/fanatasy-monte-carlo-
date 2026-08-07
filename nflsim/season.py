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


def draw_scoring_shocks(bundle: Bundle, n_sims: int, rng: np.random.Generator,
                        enabled: bool = True) -> np.ndarray:
    """(S, P) per-season multiplier on a player's goal-line role.

    Drawn independently of the overall role factor, because a player's red zone
    usage genuinely moves year to year beyond his general workload -- and
    because that is the mechanism through which the missing touchdown variance
    has to enter. Centred so the expectation is one, so scoring rates are
    unchanged on average and only the spread widens.
    """
    P = len(bundle.player_table)
    sigma = float(getattr(bundle, "td_sigma", 0.0) or 0.0)
    if not enabled or sigma <= 0:
        return np.ones((n_sims, P), dtype=np.float32)
    z = rng.standard_normal((n_sims, P))
    return np.exp(sigma * z - 0.5 * sigma ** 2).astype(np.float32)


def draw_team_shocks(bundle: Bundle, n_sims: int, rng: np.random.Generator,
                     enabled: bool = True) -> dict[str, dict]:
    """Per-season offensive efficiency shocks, one draw per team per season.

    Team strength is otherwise a point estimate, which asserts that how well an
    offence will play is knowable in August. It is not, and holding it fixed is
    the main reason the projected intervals come out too narrow -- especially
    for quarterbacks, whose scoring is almost entirely a function of how well
    their offence happens to play that year.
    """
    sig = bundle.team_shock
    out = {}
    for team in bundle.teams:
        if not enabled:
            out[team] = {}
            continue
        out[team] = {
            "comp": rng.normal(0.0, sig["comp"], n_sims),
            "ypc": rng.normal(0.0, sig["ypc"], n_sims),
        }
    return out


WEEK_QUANTILES = (10, 25, 50, 75, 90)


def run_season(bundle: Bundle, n_sims: int, seed: int, verbose: bool = True,
               use_injuries: bool = True, use_role_variance: bool = True,
               use_team_shocks: bool | None = None,
               scoring=None, weekly: bool = True) -> dict:
    """Simulate the full regular season `n_sims` times.

    When `weekly` is set, per-week summaries are captured alongside the season
    totals. Keeping the full weekly distribution would mean an array of shape
    (weeks, stats, sims, players) -- several gigabytes -- so instead the schedule
    is walked in week order, a single week's buffer is accumulated, and its
    summaries are taken and the buffer discarded before the next week starts.
    That costs one extra (stats, sims, players) array rather than eighteen.
    """
    from .analysis import fantasy_points
    from .config import PPR
    scoring = scoring or PPR
    P = len(bundle.player_table)
    sched = bundle.schedule
    weeks = int(sched.week.max())
    # Named streams stop a change in one latent model from shifting every
    # unrelated draw that follows it.  Each scheduled game also gets its own
    # stream, so a changed branch in week 1 cannot perturb week 18.  Branches
    # within one game can still consume different draws; these are controlled
    # same-seed sensitivities, not exact play-level common-random-number pairs.
    root = np.random.SeedSequence(seed)
    (availability_seed, role_seed, shock_seed,
     scoring_seed, games_seed) = root.spawn(5)
    availability_rng = np.random.default_rng(availability_seed)
    role_rng = np.random.default_rng(role_seed)
    shock_rng = np.random.default_rng(shock_seed)
    scoring_rng = np.random.default_rng(scoring_seed)
    game_seeds = games_seed.spawn(len(sched))

    # Always draw every latent source, even when a scenario disables one.  It
    # keeps the RNG at the same point before game simulation, so factor-off
    # experiments use common random numbers instead of mistaking Monte Carlo
    # noise for a model effect.  `None` preserves the historical API where
    # disabling role variance also disabled team shocks.
    if use_team_shocks is None:
        use_team_shocks = use_role_variance
    drawn_avail = draw_availability(bundle, n_sims, availability_rng, weeks)
    drawn_role = draw_role_factors(bundle, n_sims, role_rng, enabled=True)
    drawn_shocks = draw_team_shocks(bundle, n_sims, shock_rng, enabled=True)
    drawn_gl = draw_scoring_shocks(bundle, n_sims, scoring_rng, enabled=True)
    avail = (drawn_avail if use_injuries else
             np.ones((weeks, n_sims, P), dtype=np.float32))
    role = (drawn_role if use_role_variance else
            np.ones((n_sims, P), dtype=np.float32))
    shocks = drawn_shocks if use_team_shocks else {team: {} for team in bundle.teams}
    gl_role = (drawn_gl if use_role_variance else
               np.ones((n_sims, P), dtype=np.float32))

    totals = np.zeros((NSTAT, n_sims, P), dtype=np.float32)
    games_played = np.zeros((n_sims, P), dtype=np.float32)
    team_points = {t: np.zeros((n_sims,), dtype=np.float32) for t in bundle.teams}
    team_wins = {t: np.zeros((n_sims,), dtype=np.float32) for t in bundle.teams}

    # Per-week capture. One buffer, reused: flushed to summaries at each week
    # boundary so only the current week is ever held at full resolution.
    P_ = P
    week_buf = np.zeros((NSTAT, n_sims, P_), dtype=np.float32) if weekly else None
    weekly_stats = np.zeros((weeks, NSTAT, P_), dtype=np.float32) if weekly else None
    weekly_fp = np.zeros((weeks, len(WEEK_QUANTILES) + 2, P_), dtype=np.float32) if weekly else None
    weekly_played = np.zeros((weeks, P_), dtype=np.float32) if weekly else None
    week_opp: dict[int, dict[str, str]] = {}
    cur_week = None

    def flush(w):
        """Summarise the buffered week, then clear it."""
        if not weekly or w is None:
            return
        weekly_stats[w] = week_buf.mean(axis=1)
        fp = fantasy_points(week_buf, scoring)
        weekly_fp[w, 0] = fp.mean(axis=0)
        weekly_fp[w, 1] = fp.std(axis=0)
        for qi, q in enumerate(WEEK_QUANTILES):
            weekly_fp[w, 2 + qi] = np.percentile(fp, q, axis=0)
        week_buf[:] = 0.0

    t0 = time.time()
    n_games = len(sched)

    for gi, row in enumerate(sched.itertuples(index=False)):
        sim = GameSimulator(bundle.physics, np.random.default_rng(game_seeds[gi]), n_sims)
        home, away = row.home_team, row.away_team
        if home not in bundle.teams or away not in bundle.teams:
            continue
        hm, aw = bundle.teams[home], bundle.teams[away]
        w = int(row.week) - 1
        if weekly and w != cur_week:
            flush(cur_week)
            cur_week = w
        week_opp.setdefault(w, {})[home] = f"vs {away}"
        week_opp.setdefault(w, {})[away] = f"@ {home}"

        av_h = avail[w][:, hm.gidx]
        av_a = avail[w][:, aw.gidx]

        roof = getattr(row, "roof", "outdoors")
        weather = {
            "wind": coerce_wind(getattr(row, "wind", np.nan)),
            "outdoors": bool(pd.isna(roof) or str(roof) in ("outdoors", "open")),
        }

        res = sim.run(hm, aw, av_h, av_a, weather, home_field=1.6,
                      role_home=role[:, hm.gidx], role_away=role[:, aw.gidx],
                      shock_home=shocks.get(home), shock_away=shocks.get(away),
                      gl_home=gl_role[:, hm.gidx], gl_away=gl_role[:, aw.gidx])

        totals[:, :, hm.gidx] += res["home_stats"]
        totals[:, :, aw.gidx] += res["away_stats"]
        if weekly:
            week_buf[:, :, hm.gidx] += res["home_stats"]
            week_buf[:, :, aw.gidx] += res["away_stats"]
            weekly_played[w, hm.gidx] += av_h.mean(axis=0)
            weekly_played[w, aw.gidx] += av_a.mean(axis=0)
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

    flush(cur_week)

    if verbose:
        print(f"  simulated {n_games} games x {n_sims} seasons in "
              f"{time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    out = {
        "totals": totals,
        "games_played": games_played,
        "team_points": team_points,
        "team_wins": team_wins,
        "n_sims": n_sims,
    }
    if weekly:
        out.update({
            "weekly_stats": weekly_stats,       # (weeks, stat, player) means
            "weekly_fp": weekly_fp,             # (weeks, [mean, sd, *quantiles], player)
            "weekly_played": weekly_played,     # (weeks, player) availability
            "week_opponent": week_opp,          # week -> team -> opponent label
            "week_quantiles": list(WEEK_QUANTILES),
        })
    return out
