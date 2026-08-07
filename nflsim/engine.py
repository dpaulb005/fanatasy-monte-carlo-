"""The play-by-play Monte Carlo engine.

The simulation is vectorised *across replications* rather than across plays.
One game is advanced one play at a time, but every one of the N simulated
universes takes that step simultaneously as a single numpy operation. A season
is therefore ~160 sequential steps per game rather than 160 x N, which is what
makes ten thousand full seasons tractable.

Why play-by-play at all: fantasy scoring is a function of *usage*, and usage is
a function of game script. A team that falls behind throws more, and its
receivers eat; a team that leads runs the clock out, and its back eats. Those
correlations are not something you can bolt onto a box-score sampler after the
fact -- they have to emerge from the same state machine that produced the
score. Simulating the drive is what buys the correlation structure.

State is carried in parallel arrays of length N:

    secs   seconds remaining in the game      pos   which team has the ball
    yl     yards from the offence's end zone  down  current down
    togo   yards needed for a first down      score points, per team

Each iteration resolves one play for every live replication, attributes the
resulting yardage to a specific simulated player, and advances the clock.

Stat tensors are laid out (channel, replication, roster slot) so that a single
channel is a contiguous 2-D view. Because exactly one replication row appears
once per play, attribution is a flat fancy-index add into that view -- O(active
rows), no scratch allocation, and no need for the much slower np.add.at.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .priors import GRID_SHAPE, SD_BINS, TIME_BINS, TOGO_BINS, YL_BINS, LeaguePhysics, _binidx

STATS = (
    "pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
    "rush_att", "rush_yds", "rush_td",
    "targets", "rec", "rec_yds", "rec_td",
    "fum_lost", "sack_taken",
)
SIDX = {name: i for i, name in enumerate(STATS)}
NSTAT = len(STATS)

AY_EDGES = np.array([-99, -3, 0, 3, 6, 9, 12, 15, 19, 24, 30, 40, 99], dtype=float)


@dataclass
class TeamModel:
    """Everything the engine needs to run one team's offence."""

    team: str
    gidx: np.ndarray          # global player index for each roster slot
    pos_code: np.ndarray      # 0 QB, 1 RB, 2 WR, 3 TE

    target_share: np.ndarray  # base shares, before availability
    rz_target_share: np.ndarray   # inside the 20
    gl_target_share: np.ndarray   # inside the 5
    rush_share: np.ndarray
    gl_share: np.ndarray

    adot: np.ndarray
    yac_mean: np.ndarray
    catch_oe: np.ndarray
    ypc_oe: np.ndarray

    # Passing attributes, stored per roster slot so a quarterback's traits can
    # be looked up directly by the slot index the engine already carries.
    qb_slots: np.ndarray
    qb_cpoe: np.ndarray
    qb_adot: np.ndarray
    qb_sack_oe: np.ndarray
    qb_rush_share: np.ndarray

    redistribute: np.ndarray  # (n, n): column j spreads player j's vacated share

    proe: float
    pace_mult: float          # coach pace relative to league neutral pace
    go_oe: float
    rz_pass_oe: float

    off_pass_epa: float
    off_rush_epa: float
    off_comp_oe: float
    off_ypc_oe: float
    off_sack_oe: float

    def_pass_epa: float
    def_rush_epa: float
    def_comp_oe: float
    def_ypc_oe: float
    def_sack_oe: float

    @property
    def n(self) -> int:
        return len(self.gidx)


def _effective_shares(base: np.ndarray, avail: np.ndarray, redis: np.ndarray) -> np.ndarray:
    """Spread the usage of unavailable players onto the players who remain.

    `avail` is (S, n) of 0/1. A missing player's share is routed through the
    redistribution matrix -- which concentrates it on his positional backups
    rather than smearing it evenly over the offence -- and the result is
    renormalised so every replication still sums to one.
    """
    b = base if base.ndim == 2 else base[None, :]
    live = b * avail
    vacated = b * (1.0 - avail)
    absorbed = (vacated @ redis.T) * avail
    eff = live + absorbed
    total = eff.sum(axis=1, keepdims=True)
    out = np.zeros_like(eff)
    np.divide(eff, np.maximum(total, 1e-12), out=out, where=total > 1e-12)
    # A replication with nobody available falls back to an even split so the
    # sampler always has a valid distribution.
    dead = (total <= 1e-12).ravel()
    if dead.any():
        out[dead] = 1.0 / eff.shape[1]
    return out


def _sample_player(cum: np.ndarray, rows: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw one roster slot per active replication from per-row weights."""
    sub = cum[rows]
    u = rng.random(len(rows)) * sub[:, -1]
    return (sub < u[:, None]).sum(axis=1).clip(0, sub.shape[1] - 1)


def _add(plane: np.ndarray, rows: np.ndarray, slots: np.ndarray, vals, n: int) -> None:
    """Scatter-add into a contiguous (S, n) stat plane.

    `rows` holds distinct replication indices -- one play resolves once per
    replication -- so the flat indices are unique and a plain fancy-index add
    is both correct and fast.
    """
    if rows.size == 0:
        return
    plane.reshape(-1)[rows * n + slots] += vals


class GameSimulator:
    """Simulates one matchup across all replications at once."""

    KNEEL_SECS = 40.0

    def __init__(self, physics: LeaguePhysics, rng: np.random.Generator, n_sims: int):
        self.ph = physics
        self.rng = rng
        self.S = n_sims
        self.xpass_flat = physics.xpass_grid.reshape(-1)

    def _xpass(self, down, togo, sd, secs) -> np.ndarray:
        d = np.clip(down.astype(int) - 1, 0, 3)
        t = _binidx(togo, TOGO_BINS)
        s = _binidx(sd, SD_BINS)
        c = _binidx(secs, TIME_BINS)
        flat = ((d * GRID_SHAPE[1] + t) * GRID_SHAPE[2] + s) * GRID_SHAPE[3] + c
        return self.xpass_flat[flat]

    @staticmethod
    def _logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    @staticmethod
    def _expit(x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))

    # ------------------------------------------------------------------
    def run(self, home: TeamModel, away: TeamModel,
            avail_home: np.ndarray, avail_away: np.ndarray,
            weather: dict, home_field: float,
            role_home: np.ndarray | None = None,
            role_away: np.ndarray | None = None) -> dict:
        S, ph, rng = self.S, self.ph, self.rng

        teams = (away, home)
        avails = (avail_away, avail_home)
        # Per-season role factors, drawn once for the whole season so a player
        # who wins a bigger role keeps it all year rather than re-rolling it
        # every Sunday.
        roles = (role_away, role_home)

        # Usage is fixed for the game once availability is known, so the injury
        # cascade is resolved once here rather than on every snap.
        cums, gl_cums, stats = [], [], []
        for tm, av, role in zip(teams, avails, roles):
            def base(v):
                return v if role is None else v[None, :] * role

            tsh = _effective_shares(base(tm.target_share), av, tm.redistribute)
            rzsh = _effective_shares(base(tm.rz_target_share), av, tm.redistribute)
            glsh = _effective_shares(base(tm.gl_target_share), av, tm.redistribute)
            rsh = _effective_shares(base(tm.rush_share), av, tm.redistribute)
            gsh = _effective_shares(base(tm.gl_share), av, tm.redistribute)
            cums.append((np.cumsum(tsh, axis=1), np.cumsum(rsh, axis=1),
                         np.cumsum(rzsh, axis=1), np.cumsum(glsh, axis=1)))
            gl_cums.append(np.cumsum(gsh, axis=1))
            stats.append(np.zeros((NSTAT, S, tm.n), dtype=np.float64))

        # Starting quarterback: the highest-ranked arm still standing.
        qbs = []
        for tm, av in zip(teams, avails):
            order = tm.qb_slots
            ok = av[:, order] > 0
            first = np.argmax(ok, axis=1)
            first[~ok.any(axis=1)] = 0
            qbs.append(order[first])

        secs = np.full(S, 3600.0)
        half = np.zeros(S, dtype=np.int8)
        pos = rng.integers(0, 2, size=S).astype(np.int8)
        second_half_ball = (1 - pos).astype(np.int8)
        yl = np.full(S, 70.0)
        down = np.ones(S, dtype=np.int8)
        togo = np.full(S, 10.0)
        score = np.zeros((S, 2), dtype=np.int32)
        done = np.zeros(S, dtype=bool)

        wind = weather.get("wind", 0.0)
        wind = float(wind) if wind is not None and np.isfinite(wind) else 0.0
        outdoors = bool(weather.get("outdoors", True))
        wind_pass = -0.010 * wind if outdoors else 0.0
        wind_fg = -0.006 * wind if outdoors else 0.0

        for _ in range(400):
            live = ~done
            if not live.any():
                break

            for side in (0, 1):
                rows = np.flatnonzero(live & (pos == side))
                if rows.size == 0:
                    continue

                off, dfn = teams[side], teams[1 - side]
                st = stats[side]
                tsh_cum, rsh_cum, rz_cum, gltgt_cum = cums[side]
                glc = gl_cums[side]
                qb = qbs[side]
                hf = home_field if side == 1 else -home_field

                k = rows.size
                d_ = down[rows].astype(float)
                tg = togo[rows]
                y = yl[rows]
                sd = (score[rows, side] - score[rows, 1 - side]).astype(float)
                sec = secs[rows]

                gain = np.zeros(k)
                clock = np.zeros(k)
                turnover = np.zeros(k, dtype=bool)
                change = np.zeros(k, dtype=bool)
                next_yl = np.zeros(k)
                points = np.zeros(k, dtype=np.int32)
                scored_td = np.zeros(k, dtype=bool)

                kneel = (sd > 0) & (sec < 120.0) & (d_ <= 3)

                # ---- fourth down ---------------------------------------
                fg_dist = y + 17.0
                go_base = ph.go_grid[_binidx(y, YL_BINS), _binidx(tg, TOGO_BINS)]
                go_p = np.clip(go_base + off.go_oe, 0.01, 0.985)
                fg_p = np.clip(
                    ph.fg_by_distance[np.clip(fg_dist.astype(int), 0, 74)] + wind_fg, 0.01, 0.995
                )
                must_go = (sd < -3) & (sec < 300)
                is4 = (d_ == 4) & ~kneel
                go = is4 & ((rng.random(k) < go_p) | must_go)
                try_fg = is4 & ~go & (fg_dist <= 63) & (fg_p > 0.25)
                punt = is4 & ~go & ~try_fg
                scrim = (~is4 | go) & ~kneel

                if kneel.any():
                    ki = np.flatnonzero(kneel)
                    clock[ki] = self.KNEEL_SECS
                    gain[ki] = -1.0

                if try_fg.any():
                    idx = np.flatnonzero(try_fg)
                    made = rng.random(idx.size) < fg_p[idx]
                    points[idx[made]] = 3
                    clock[idx] = 6.0
                    change[idx] = True
                    next_yl[idx[made]] = 70.0
                    miss = idx[~made]
                    next_yl[miss] = np.clip(100.0 - (y[miss] + 8.0), 20.0, 80.0)

                if punt.any():
                    idx = np.flatnonzero(punt)
                    net = rng.normal(ph.punt_net_mean, ph.punt_net_sd, idx.size)
                    landing = y[idx] - net
                    next_yl[idx] = np.where(landing <= 0, 80.0, np.clip(100.0 - landing, 1.0, 99.0))
                    clock[idx] = 10.0
                    change[idx] = True

                sc = np.flatnonzero(scrim)
                if sc.size:
                    self._scrimmage(
                        sc, rows, off, dfn, st, tsh_cum, rsh_cum, rz_cum, gltgt_cum,
                        glc, qb, d_, tg, y, sd, sec, wind_pass,
                        gain, turnover, clock, change, next_yl, scored_td,
                    )

                # ---- transitions ---------------------------------------
                end_spot = y - gain
                td = scored_td & ~turnover
                safety = (end_spot >= 100.0) & scrim

                if td.any():
                    ti = np.flatnonzero(td)
                    points[ti] += 6
                    go2 = rng.random(ti.size) < 0.09
                    xp_ok = rng.random(ti.size) < ph.xp_rate
                    two_ok = rng.random(ti.size) < ph.two_pt_rate
                    points[ti] += np.where(go2, np.where(two_ok, 2, 0), np.where(xp_ok, 1, 0))
                    change[ti] = True
                    next_yl[ti] = 70.0
                    clock[ti] = np.maximum(clock[ti], 6.0)

                if safety.any():
                    si = np.flatnonzero(safety)
                    score[rows[si], 1 - side] += 2
                    change[si] = True
                    next_yl[si] = 45.0

                first_down = (gain >= tg) & scrim & ~td & ~turnover & ~safety

                np.add.at(score, (rows, side), points)

                # Pace: physics sets the base runoff, the coach scales it, and a
                # trailing team late in a half compresses it further.
                clock = np.where(clock > 0, clock, ph.sec_run) * off.pace_mult
                two_min = (sec < 120) | ((sec > 1800) & (sec < 1920))
                clock = np.where(two_min & (sd < 0), np.minimum(clock, ph.sec_hurry), clock)
                secs[rows] = np.maximum(sec - clock, 0.0)

                flip = change | turnover
                new_pos = np.where(flip, 1 - side, side).astype(np.int8)
                ny = np.where(flip, next_yl, np.clip(end_spot, 1.0, 99.0))
                # A turnover with no explicit spot is returned to the defence at
                # the place the play ended.
                bare = turnover & ~change
                if bare.any():
                    bi = np.flatnonzero(bare)
                    ny[bi] = np.clip(100.0 - end_spot[bi], 1.0, 99.0)

                fresh = flip | first_down | td
                nd = np.where(fresh, 1, d_ + 1).astype(np.int8)
                ntg = np.where(fresh, np.minimum(10.0, ny), np.maximum(tg - gain, 1.0))

                on_downs = (nd > 4) & ~flip
                if on_downs.any():
                    oi = np.flatnonzero(on_downs)
                    new_pos[oi] = 1 - side
                    ny[oi] = np.clip(100.0 - ny[oi], 1.0, 99.0)
                    nd[oi] = 1
                    ntg[oi] = np.minimum(10.0, ny[oi])

                pos[rows] = new_pos
                yl[rows] = ny
                down[rows] = nd
                togo[rows] = ntg

            half_end = (~done) & (secs <= 1800.0) & (half == 0)
            if half_end.any():
                hi = np.flatnonzero(half_end)
                half[hi] = 1
                pos[hi] = second_half_ball[hi]
                yl[hi] = 70.0
                down[hi] = 1
                togo[hi] = 10.0

            done |= secs <= 0.0

        # Overtime is settled as a coin flip on the winning drive, which is
        # close enough for season-long fantasy purposes.
        tied = np.flatnonzero(score[:, 0] == score[:, 1])
        if tied.size:
            score[tied, rng.integers(0, 2, size=tied.size)] += 3

        return {
            "away_stats": stats[0], "home_stats": stats[1],
            "away_score": score[:, 0], "home_score": score[:, 1],
        }

    # ------------------------------------------------------------------
    def _scrimmage(self, sc, rows, off: TeamModel, dfn: TeamModel, st,
                   tsh_cum, rsh_cum, rz_cum, gltgt_cum, glc, qb,
                   d_, tg, y, sd, sec, wind_pass,
                   gain, turnover, clock, change, next_yl, scored_td) -> None:
        """Resolve run/pass plays for the subset `sc` of the active rows.

        Index discipline: `sc` indexes the k-length per-play buffers, `grows`
        holds the matching global replication indices, and every subsequent
        subset is taken from *both* in lockstep.
        """
        ph, rng, n = self.ph, self.rng, off.n
        grows = rows[sc]

        # Down, distance, score and clock set the baseline; distance to the end
        # zone corrects it, because goal-line play-calling is nothing like
        # midfield play-calling at the same down and distance.
        xp = self._xpass(d_[sc], tg[sc], sd[sc], sec[sc])
        xp = np.clip(xp + ph.xpass_oe_by_yardline[np.clip(y[sc], 0, 99).astype(int)],
                     0.02, 0.98)
        shift = off.proe * 4.0 + np.where(y[sc] <= 20, off.rz_pass_oe * 4.0, 0.0)
        is_pass = rng.random(sc.size) < self._expit(self._logit(xp) + shift)

        pass_i, prow = sc[is_pass], grows[is_pass]
        run_i, rrow = sc[~is_pass], grows[~is_pass]

        # ================= PASS =========================================
        if pass_i.size:
            qb_slot = qb[prow]
            sack_p = np.clip(
                ph.sack_rate + off.off_sack_oe + dfn.def_sack_oe + off.qb_sack_oe[qb_slot],
                0.005, 0.35,
            )
            sacked = rng.random(pass_i.size) < sack_p

            si, srow = pass_i[sacked], prow[sacked]
            if si.size:
                loss = np.maximum(rng.gamma(3.0, ph.sack_yards_mean / 3.0, si.size), 0.5)
                gain[si] = -loss
                clock[si] = ph.sec_run
                _add(st[SIDX["sack_taken"]], srow, qb[srow], 1.0, n)
                fum = rng.random(si.size) < ph.sack_fumble_rate
                turnover[si] = fum
                if fum.any():
                    _add(st[SIDX["fum_lost"]], srow[fum], qb[srow[fum]], 1.0, n)

            thrown, trow = pass_i[~sacked], prow[~sacked]
            if thrown.size:
                kt = thrown.size
                qb_j = qb[trow]
                # Who is targeted depends on where the ball is. Near the goal
                # line offences lean on tight ends and away from backs, so the
                # draw comes from a zone-specific share vector.
                yt = y[thrown]
                rec_open = _sample_player(tsh_cum, trow, rng)
                rec_rz = _sample_player(rz_cum, trow, rng)
                rec_gl = _sample_player(gltgt_cum, trow, rng)
                rec_j = np.where(yt <= 5, rec_gl, np.where(yt <= 20, rec_rz, rec_open))

                # Air yards blend the receiver's usual depth with the passer's
                # tendency; trailing late, offences push the ball downfield.
                base_adot = 0.65 * off.adot[rec_j] + 0.35 * off.qb_adot[qb_j]
                base_adot += np.where((sd[thrown] < -7) & (sec[thrown] < 600), 2.5, 0.0)
                ay = rng.normal(base_adot, ph.ay_sd * 0.75, kt)
                ay = np.minimum(ay, y[thrown] + 3.0)
                ay_i = _binidx(ay, AY_EDGES)

                # Depth of target sets the base rate; distance to the end zone
                # corrects it for the compressed field, which is a large effect
                # inside the twenty and the reason red zone passing produces far
                # fewer touchdowns than open-field completion rates imply.
                field_oe = ph.comp_oe_by_yardline[np.clip(y[thrown], 0, 99).astype(int)]
                cp = np.clip(
                    ph.comp_by_ay[ay_i] + field_oe + off.catch_oe[rec_j] + off.qb_cpoe[qb_j]
                    + off.off_comp_oe + dfn.def_comp_oe + wind_pass * (ay > 12),
                    0.02, 0.98,
                )
                complete = rng.random(kt) < cp

                # Interceptions are drawn from the incompletions, so the two
                # rates stay mutually consistent.
                p_int_given_inc = np.clip(ph.int_by_ay[ay_i] / np.maximum(1.0 - cp, 1e-3), 0.0, 1.0)
                picked = (~complete) & (rng.random(kt) < p_int_given_inc)

                yac = rng.gamma(ph.yac_shape,
                                np.maximum(ph.yac_mean_by_ay[ay_i], 0.2) / ph.yac_shape, kt)
                yac *= np.clip(off.yac_mean[rec_j] / np.maximum(ph.yac_mean_by_ay[ay_i], 0.5), 0.4, 2.5)

                total = np.where(complete, np.minimum(ay + yac, y[thrown]), 0.0)
                gain[thrown] = total
                clock[thrown] = np.where(complete, ph.sec_pass_complete, ph.sec_pass_incomplete)

                scored = complete & ((y[thrown] - total) <= 0)
                scored_td[thrown] |= scored
                fum = complete & ~scored & (rng.random(kt) < ph.rec_fumble_rate)
                turnover[thrown] |= picked | fum

                if picked.any():
                    pi = np.flatnonzero(picked)
                    next_yl[thrown[pi]] = np.clip(100.0 - (y[thrown[pi]] - ay[pi]), 1.0, 99.0)
                    change[thrown[pi]] = True

                _add(st[SIDX["pass_att"]], trow, qb_j, 1.0, n)
                _add(st[SIDX["targets"]], trow, rec_j, 1.0, n)
                ci = np.flatnonzero(complete)
                if ci.size:
                    _add(st[SIDX["pass_cmp"]], trow[ci], qb_j[ci], 1.0, n)
                    _add(st[SIDX["pass_yds"]], trow[ci], qb_j[ci], total[ci], n)
                    _add(st[SIDX["rec"]], trow[ci], rec_j[ci], 1.0, n)
                    _add(st[SIDX["rec_yds"]], trow[ci], rec_j[ci], total[ci], n)
                ti = np.flatnonzero(scored)
                if ti.size:
                    _add(st[SIDX["pass_td"]], trow[ti], qb_j[ti], 1.0, n)
                    _add(st[SIDX["rec_td"]], trow[ti], rec_j[ti], 1.0, n)
                pi = np.flatnonzero(picked)
                if pi.size:
                    _add(st[SIDX["pass_int"]], trow[pi], qb_j[pi], 1.0, n)
                fi = np.flatnonzero(fum)
                if fi.size:
                    _add(st[SIDX["fum_lost"]], trow[fi], rec_j[fi], 1.0, n)

        # ================= RUN ==========================================
        if run_i.size:
            kr = run_i.size
            goal_line = y[run_i] <= 5
            # Goal-line work is a different job than early-down volume, so it is
            # drawn from its own share vector.
            rush_j = np.where(goal_line,
                              _sample_player(glc, rrow, rng),
                              _sample_player(rsh_cum, rrow, rng))
            qb_keep = rng.random(kr) < off.qb_rush_share[qb[rrow]]
            rush_j = np.where(qb_keep, qb[rrow], rush_j)

            eff = off.ypc_oe[rush_j] + off.off_ypc_oe + dfn.def_ypc_oe
            raw = rng.gamma(ph.rush_shape, ph.rush_scale, kr) - ph.rush_shift + eff
            yards = np.minimum(raw, y[run_i])

            # Near the goal line the gamma misstates conversion, so the score is
            # drawn directly from the observed rate at that spot. That rate is
            # the *total* probability of scoring from there, so a non-scoring
            # goal-line run must be held short of the end zone -- otherwise the
            # gamma adds a second, independent path to six points and rushing
            # touchdowns come out well above the real rate.
            gl_hit = goal_line & (rng.random(kr) < ph.rush_td_boost[np.clip(y[run_i].astype(int), 0, 10)])
            yards = np.where(goal_line,
                             np.where(gl_hit, y[run_i], np.minimum(yards, y[run_i] - 1.0)),
                             yards)

            gain[run_i] = yards
            clock[run_i] = ph.sec_run
            scored = (y[run_i] - yards) <= 0
            scored_td[run_i] |= scored
            fum = ~scored & (rng.random(kr) < ph.rush_fumble_rate)
            turnover[run_i] |= fum

            _add(st[SIDX["rush_att"]], rrow, rush_j, 1.0, n)
            _add(st[SIDX["rush_yds"]], rrow, rush_j, yards, n)
            ti = np.flatnonzero(scored)
            if ti.size:
                _add(st[SIDX["rush_td"]], rrow[ti], rush_j[ti], 1.0, n)
            fi = np.flatnonzero(fum)
            if fi.size:
                _add(st[SIDX["fum_lost"]], rrow[fi], rush_j[fi], 1.0, n)
