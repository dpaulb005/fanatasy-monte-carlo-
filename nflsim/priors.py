"""Fit the structural priors the play-by-play engine samples from.

Three layers are built here:

1. League physics -- how a play actually resolves. Completion probability as a
   function of air yards, the YAC distribution, rushing yardage, sack/interception/
   fumble rates, field goal accuracy by distance, punt distance, clock runoff.
   These are the shared laws every team plays under.

2. Coaching -- pass rate over expected, pace, fourth-down aggression and red zone
   tendency, attributed to the *coach* rather than the team, so that a staff that
   changed jobs carries its identity to the new building and a team that changed
   staffs inherits the new one.

3. Team strength -- offensive and defensive efficiency, split by pass and rush,
   regressed toward the league mean by sample size and adjusted for how much of
   the roster actually returned.

Everything is estimated from binned empirical frequencies rather than a fitted
parametric model. With ~350k plays of history the bins are dense enough to be
stable, and empirical bins cannot be wrong about a shape the way a misspecified
link function can.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import data
from .config import PBP_SEASONS, TARGET_SEASON

# --------------------------------------------------------------------------
# Binning helpers
# --------------------------------------------------------------------------

# Air yards bins for the completion-probability curve.
AY_BINS = np.array([-99, -3, 0, 3, 6, 9, 12, 15, 19, 24, 30, 40, 99], dtype=float)
# Yardline bins (distance to opponent end zone).
YL_BINS = np.array([0, 3, 6, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100], dtype=float)
# Distance-to-go bins.
TOGO_BINS = np.array([0, 1, 2, 3, 5, 7, 10, 13, 17, 25, 99], dtype=float)
# Score differential bins (offense perspective).
SD_BINS = np.array([-99, -17, -11, -8, -4, -1, 1, 4, 8, 11, 17, 99], dtype=float)
# Time remaining bins, in seconds.
TIME_BINS = np.array([0, 120, 300, 600, 900, 1800, 2700, 3600], dtype=float)


def _binidx(values, bins) -> np.ndarray:
    """Right-open bin index, clipped into range."""
    v = np.asarray(values, dtype=float)
    return np.clip(np.digitize(v, bins[1:-1], right=False), 0, len(bins) - 2)


def _smooth_rate(num: np.ndarray, den: np.ndarray, prior_rate: float, strength: float) -> np.ndarray:
    """Empirical-Bayes rate: shrink each cell toward `prior_rate`."""
    return (num + prior_rate * strength) / (den + strength)


# Recency half-lives, in seasons. Every estimate in the model is a weighted sum
# over several past seasons rather than a snapshot of the most recent one --
# single-season samples are far too noisy to project from, and pooling seasons
# with equal weight ignores real drift. The half-life is set by how fast the
# quantity actually moves:
#
#   physics  slow    rule changes and league-wide efficiency drift over years
#   coaching medium  a staff's philosophy evolves, but it is recognisably theirs
#   team     fast    rosters turn over hard; two-year-old form says little
#   usage    fast    roles change on a one-year timescale
#
HALFLIFE_PHYSICS = 4.0
HALFLIFE_COACH = 2.5
HALFLIFE_TEAM = 1.15
HALFLIFE_USAGE = 1.1
HALFLIFE_ROOKIE = 5.0
HALFLIFE_BASELINE = 3.0


def recency_weights(seasons, target: int, halflife: float) -> np.ndarray:
    """Exponential decay by seasons elapsed. Weight 1.0 for the season just
    played, halving every `halflife` seasons before it."""
    s = np.asarray(seasons, dtype=float)
    return 0.5 ** ((target - 1 - s) / halflife)


def _wmean(x, w) -> float:
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    ok = np.isfinite(x) & np.isfinite(w)
    if not ok.any() or w[ok].sum() <= 0:
        return float("nan")
    return float(np.average(x[ok], weights=w[ok]))


def _wvar(x, w) -> float:
    m = _wmean(x, w)
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    ok = np.isfinite(x) & np.isfinite(w)
    return float(np.average((x[ok] - m) ** 2, weights=w[ok]))


def _wcount(idx: np.ndarray, w: np.ndarray, minlength: int) -> np.ndarray:
    return np.bincount(idx, weights=w, minlength=minlength).astype(float)


@dataclass
class LeaguePhysics:
    """How a play resolves, league-wide."""

    # Completion probability by air-yards bin.
    comp_by_ay: np.ndarray
    # Completion probability above the air-yards curve, by yards from the end
    # zone. The compressed field is a real and large effect that depth of
    # target alone cannot express: a defence with no grass behind it covers
    # far more effectively, and completion rates inside the ten fall to the
    # high forties while the league curve would predict the low seventies.
    comp_oe_by_yardline: np.ndarray
    # Mean and shape of YAC by air-yards bin (gamma parameters).
    yac_mean_by_ay: np.ndarray
    yac_shape: float
    # Interception probability by air-yards bin.
    int_by_ay: np.ndarray
    # Air yards distribution shape (residual sd around a receiver's aDOT).
    ay_sd: float

    # Rushing: gamma parameters for (yards + shift), plus breakaway tail.
    rush_shift: float
    rush_shape: float
    rush_scale: float
    rush_stuff_rate: float          # probability of <= 0 yards
    rush_td_boost: np.ndarray       # goal-line conversion by yardline bin

    sack_rate: float
    sack_yards_mean: float
    sack_fumble_rate: float
    rush_fumble_rate: float
    rec_fumble_rate: float

    # Field goals: make probability by distance (index = distance in yards).
    fg_by_distance: np.ndarray
    xp_rate: float
    two_pt_rate: float

    punt_net_mean: float
    punt_net_sd: float
    touchback_rate: float

    # Clock runoff, seconds per play.
    sec_run: float
    sec_pass_complete: float
    sec_pass_incomplete: float
    sec_ob_bonus: float
    sec_hurry: float
    play_ob_rate: float

    # How a position's share of the targets changes near the goal line,
    # relative to its share over the whole field. Indexed by position code
    # (0 QB, 1 RB, 2 WR, 3 TE). Offences do not simply compress their normal
    # passing game as the field shortens -- they change who they throw to.
    rz_target_mult: np.ndarray      # inside the 20
    gl_target_mult: np.ndarray      # inside the 5

    # League baseline pass rate on a (down, togo, score, time) grid.
    xpass_grid: np.ndarray
    # Pass rate above that grid, by yards from the end zone. Field position is
    # deliberately kept out of the main grid -- adding a fifth axis would
    # quarter the plays per cell -- but goal-line play-calling is emphatically
    # not the same as midfield play-calling at the same down and distance, so
    # it is carried as a separate residual.
    xpass_oe_by_yardline: np.ndarray
    # League baseline fourth-down go-for-it rate on a (yl, togo) grid.
    go_grid: np.ndarray

    # Baselines used for team-relative adjustments.
    league_epa_pass: float
    league_epa_rush: float
    league_plays_per_game: float


@dataclass
class CoachProfile:
    """A coaching staff's identity, independent of the roster it inherited."""

    coach: str
    seasons: int
    plays: int
    proe: float             # pass rate over expected, in probability points
    sec_per_play: float     # neutral-situation pace
    go_rate_oe: float       # fourth-down aggression over expected
    rz_pass_oe: float       # red zone pass tendency over expected
    pass_rush_split_rz: float
    shotgun_rate: float
    no_huddle_rate: float


@dataclass
class TeamStrength:
    team: str
    off_pass_epa: float
    off_rush_epa: float
    def_pass_epa: float
    def_rush_epa: float
    off_comp_oe: float       # completion % over expected the offense generates
    off_ypc_oe: float        # yards per carry above expected
    def_comp_oe: float
    def_ypc_oe: float
    off_sack_oe: float
    def_sack_oe: float
    pace_sec_play: float
    proe: float
    go_rate_oe: float
    continuity: float        # share of prior-year snaps returning
    coach: str
    coach_is_new: bool


# --------------------------------------------------------------------------
# Layer 1: league physics
# --------------------------------------------------------------------------

def fit_league_physics(pbp: pd.DataFrame, season: int | None = None,
                       halflife: float = HALFLIFE_PHYSICS) -> LeaguePhysics:
    """Fit the shared laws of a play as a recency-weighted sum over seasons.

    Every rate here is estimated from several past seasons at once, weighted
    toward the recent ones. Pooling a decade with equal weight would bake in a
    league that no longer exists -- completion percentage, pass rate and field
    goal range have all drifted materially -- while using one season alone
    would be far too noisy to sample from. A four-season half-life keeps roughly
    a decade of signal while letting the recent game dominate.
    """
    p = pbp
    reg = p[(p.season_type == "REG")]
    target = int(season if season is not None else reg.season.max() + 1)

    def W(df: pd.DataFrame) -> np.ndarray:
        return recency_weights(df.season.to_numpy(), target, halflife)

    # ---- Passing ---------------------------------------------------------
    passes = reg[(reg.pass_attempt == 1) & (reg.sack != 1) & reg.air_yards.notna()]
    wp = W(passes)
    ay_idx = _binidx(passes.air_yards, AY_BINS)
    comp = passes.complete_pass.fillna(0).to_numpy(float)
    ints = passes.interception.fillna(0).to_numpy(float)

    n_ay = len(AY_BINS) - 1
    den = _wcount(ay_idx, wp, n_ay)
    comp_by_ay = _smooth_rate(_wcount(ay_idx, comp * wp, n_ay), den, _wmean(comp, wp), 200.0)
    int_by_ay = _smooth_rate(_wcount(ay_idx, ints * wp, n_ay), den, _wmean(ints, wp), 400.0)

    completions = passes[passes.complete_pass == 1]
    wc = W(completions)
    c_idx = _binidx(completions.air_yards, AY_BINS)
    yac = completions.yards_after_catch.fillna(0).clip(lower=0).to_numpy(float)
    c_den = _wcount(c_idx, wc, n_ay)
    yac_mean_by_ay = _smooth_rate(
        _wcount(c_idx, yac * wc, n_ay), c_den, _wmean(yac, wc), 100.0
    )
    # Gamma shape from the overall YAC distribution (method of moments).
    yac_mu, yac_var = _wmean(yac, wc), _wvar(yac, wc)
    yac_shape = float(max(0.35, yac_mu ** 2 / max(yac_var, 1e-6)))

    # Residual spread of air yards around a passer's average intent.
    ay_sd = float(passes.groupby("passer_player_id").air_yards.std().median())

    # Compressed-field effect: how far actual completion rates sit above or
    # below what the air-yards curve alone predicts, as a function of distance
    # to the end zone. Fit as a residual so it composes additively with the
    # depth-of-target curve instead of double-counting it.
    resid = comp - comp_by_ay[ay_idx]
    yl_i = np.clip(passes.yardline_100.to_numpy(float), 0, 99).astype(int)
    r_num = _wcount(yl_i, resid * wp, 100)
    r_den = _wcount(yl_i, wp, 100)
    # Smooth across neighbouring yard lines before shrinking toward no effect.
    kern = np.array([0.05, 0.1, 0.2, 0.3, 0.2, 0.1, 0.05])
    comp_oe_by_yardline = _smooth_rate(
        np.convolve(r_num, kern, mode="same"),
        np.convolve(r_den, kern, mode="same"),
        0.0, 400.0,
    )

    # ---- Rushing ---------------------------------------------------------
    rushes = reg[(reg.rush_attempt == 1) & (reg.qb_kneel != 1) & reg.yards_gained.notna()]
    wr = W(rushes)
    ry = rushes.yards_gained.to_numpy(float)
    shift = 5.0
    shifted = np.clip(ry + shift, 0.05, None)
    m, v = _wmean(shifted, wr), _wvar(shifted, wr)
    rush_shape = float(m * m / v)
    rush_scale = float(v / m)
    rush_stuff_rate = _wmean((ry <= 0).astype(float), wr)

    # Goal-line rushing converts at a very different rate than the gamma implies.
    gl = rushes[rushes.yardline_100 <= 10]
    wgl = W(gl)
    gl_idx = _binidx(gl.yardline_100, np.arange(0, 12, 1.0))
    gl_td = gl.rush_touchdown.fillna(0).to_numpy(float)
    gl_den = _wcount(gl_idx, wgl, 11)
    rush_td_boost = _smooth_rate(
        _wcount(gl_idx, gl_td * wgl, 11), gl_den, _wmean(gl_td, wgl), 50.0
    )

    dropbacks = reg[reg.qb_dropback == 1]
    sack_rate = _wmean(dropbacks.sack.fillna(0), W(dropbacks))
    sacks = reg[reg.sack == 1]
    ws = W(sacks)
    sack_yards_mean = float(-_wmean(sacks.yards_gained, ws)) if len(sacks) else 6.5
    sack_fumble_rate = _wmean(sacks.fumble_lost.fillna(0), ws) if len(sacks) else 0.03
    rush_fumble_rate = _wmean(rushes.fumble_lost.fillna(0), wr)
    rec_fumble_rate = _wmean(completions.fumble_lost.fillna(0), wc)

    # ---- Kicking ---------------------------------------------------------
    fgs = reg[(reg.field_goal_attempt == 1) & reg.kick_distance.notna()]
    wf = W(fgs)
    dist = fgs.kick_distance.clip(15, 70).to_numpy(int)
    made = (fgs.field_goal_result == "made").to_numpy(float)
    fg_by_distance = np.zeros(75)
    d_den = _wcount(dist, wf, 75)
    d_num = _wcount(dist, made * wf, 75)
    # Smooth across neighbouring distances, then enforce monotone decline.
    kern = np.array([0.05, 0.1, 0.2, 0.3, 0.2, 0.1, 0.05])
    d_den_s = np.convolve(d_den, kern, mode="same")
    d_num_s = np.convolve(d_num, kern, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(d_den_s > 1, d_num_s / np.maximum(d_den_s, 1e-9), np.nan)
    idx = np.arange(75)
    known = ~np.isnan(raw)
    fg_by_distance = np.interp(idx, idx[known], raw[known]).clip(0.01, 0.999)
    # Accuracy must not increase with distance. Running minimum forward in
    # distance enforces that without flattening the curve onto its tail value.
    fg_by_distance = np.minimum.accumulate(fg_by_distance)

    xps = reg[reg.extra_point_attempt == 1]
    xp_rate = _wmean((xps.extra_point_result == "good").astype(float), W(xps)) if len(xps) else 0.945
    twos = reg[reg.two_point_attempt == 1]
    two_pt_rate = _wmean((twos.two_point_conv_result == "success").astype(float),
                         W(twos)) if len(twos) else 0.48

    punts = reg[reg.punt_attempt == 1]
    wpu = W(punts)
    punt_net_mean = _wmean(punts.kick_distance, wpu) if len(punts) else 45.0
    punt_net_sd = float(np.sqrt(_wvar(punts.kick_distance, wpu))) if len(punts) else 9.0
    touchback_rate = 0.12

    # ---- Clock -----------------------------------------------------------
    # Runoff must be measured against the *next play of any kind*. Filtering to
    # scrimmage plays first and then differencing would silently charge the
    # punt, the change of possession and the kickoff to the preceding snap.
    allp = reg.sort_values(["game_id", "play_id"]).copy()
    allp["elapsed"] = -allp.groupby("game_id").game_seconds_remaining.diff().shift(-1)
    scr = allp[allp.play_type.isin(["run", "pass"])]
    ok = scr[(scr.elapsed > 0) & (scr.elapsed < 60)]
    wk = W(ok)
    is_run = (ok.play_type == "run").to_numpy()
    is_cmp = ((ok.play_type == "pass") & (ok.complete_pass == 1)).to_numpy()
    is_inc = ((ok.play_type == "pass") & (ok.complete_pass != 1)).to_numpy()
    el = ok.elapsed.to_numpy(float)
    sec_run = _wmean(el[is_run], wk[is_run])
    sec_pass_complete = _wmean(el[is_cmp], wk[is_cmp])
    sec_pass_incomplete = _wmean(el[is_inc], wk[is_inc])
    # Two-minute-drill compression.
    hm = (ok.half_seconds_remaining < 120).to_numpy()
    sec_hurry = _wmean(el[hm], wk[hm]) if hm.any() else 22.0

    # ---- Situational pass rate grid --------------------------------------
    calls = reg[
        reg.play_type.isin(["run", "pass"])
        & (reg.qb_kneel != 1)
        & (reg.qb_spike != 1)
        & reg.down.notna()
    ]
    wcall = W(calls)
    is_pass_call = (calls.play_type == "pass").to_numpy(float)
    xpass_grid = _rate_grid(
        calls, is_pass_call, prior=0.57, strength=60.0, weights=wcall,
    )

    # How far real play-calling sits above the grid as a function of distance
    # to the end zone. Inside the two, teams pass barely a third of the time
    # where down and distance alone predict nearly half -- and that is exactly
    # where touchdowns are scored, so ignoring it inflates passing scores and
    # starves the running game of goal-line work.
    call_flat = _grid_index(
        calls.down.to_numpy(), calls.ydstogo.to_numpy(),
        calls.score_differential.fillna(0).to_numpy(),
        calls.game_seconds_remaining.fillna(1800).to_numpy(),
    )
    call_resid = is_pass_call - xpass_grid.reshape(-1)[call_flat]
    call_yl = np.clip(calls.yardline_100.to_numpy(float), 0, 99).astype(int)
    kern_c = np.array([0.1, 0.2, 0.4, 0.2, 0.1])
    xpass_oe_by_yardline = _smooth_rate(
        np.convolve(_wcount(call_yl, call_resid * wcall, 100), kern_c, mode="same"),
        np.convolve(_wcount(call_yl, wcall, 100), kern_c, mode="same"),
        0.0, 400.0,
    )

    # ---- Fourth down go rate --------------------------------------------
    fourth = reg[(reg.down == 4) & reg.play_type.notna()]
    w4 = W(fourth)
    went = fourth.play_type.isin(["run", "pass"]).to_numpy(float)
    yl_i = _binidx(fourth.yardline_100, YL_BINS)
    tg_i = _binidx(fourth.ydstogo, TOGO_BINS)
    shape = (len(YL_BINS) - 1, len(TOGO_BINS) - 1)
    flat = yl_i * shape[1] + tg_i
    den4 = _wcount(flat, w4, shape[0] * shape[1])
    num4 = _wcount(flat, went * w4, shape[0] * shape[1])
    go_grid = _smooth_rate(num4, den4, _wmean(went, w4), 25.0).reshape(shape)

    # ---- Who gets thrown to near the goal line --------------------------
    rz_target_mult, gl_target_mult = _target_zone_multipliers(passes, wp)

    off = reg[reg.epa.notna()]
    op = off[off.pass_attempt == 1]
    orr = off[off.rush_attempt == 1]
    league_epa_pass = _wmean(op.epa, W(op))
    league_epa_rush = _wmean(orr.epa, W(orr))
    # Plays per team-game, weighted the same way, so pace drift is reflected.
    ppg = calls.groupby(["game_id", "posteam"]).agg(n=("play_id", "size"),
                                                    season=("season", "first"))
    plays_per_team_game = _wmean(ppg.n, recency_weights(ppg.season, target, halflife))

    return LeaguePhysics(
        comp_by_ay=comp_by_ay,
        comp_oe_by_yardline=comp_oe_by_yardline,
        yac_mean_by_ay=yac_mean_by_ay,
        yac_shape=yac_shape,
        int_by_ay=int_by_ay,
        ay_sd=float(ay_sd),
        rush_shift=shift,
        rush_shape=rush_shape,
        rush_scale=rush_scale,
        rush_stuff_rate=rush_stuff_rate,
        rush_td_boost=rush_td_boost,
        sack_rate=sack_rate,
        sack_yards_mean=sack_yards_mean,
        sack_fumble_rate=sack_fumble_rate,
        rush_fumble_rate=rush_fumble_rate,
        rec_fumble_rate=rec_fumble_rate,
        fg_by_distance=fg_by_distance,
        xp_rate=xp_rate,
        two_pt_rate=two_pt_rate,
        punt_net_mean=punt_net_mean,
        punt_net_sd=punt_net_sd,
        touchback_rate=touchback_rate,
        sec_run=sec_run,
        sec_pass_complete=sec_pass_complete,
        sec_pass_incomplete=sec_pass_incomplete,
        sec_ob_bonus=0.0,
        sec_hurry=sec_hurry,
        play_ob_rate=0.16,
        rz_target_mult=rz_target_mult,
        gl_target_mult=gl_target_mult,
        xpass_grid=xpass_grid,
        xpass_oe_by_yardline=xpass_oe_by_yardline,
        go_grid=go_grid,
        league_epa_pass=league_epa_pass,
        league_epa_rush=league_epa_rush,
        league_plays_per_game=float(plays_per_team_game),
    )


def _target_zone_multipliers(passes: pd.DataFrame, weights: np.ndarray,
                             ) -> tuple[np.ndarray, np.ndarray]:
    """How each position's share of targets shifts as the field shortens.

    Offences do not merely compress their normal passing game near the goal
    line, they change who they throw to: tight ends take about 29% of targets
    inside the five against 21% over the whole field, while running backs fall
    from 19% to 12%. Modelling one target share for the entire field therefore
    starves tight ends of exactly the throws that score and hands running backs
    receiving touchdowns they do not get.

    Returned as multipliers on the base share, indexed by position code, so
    they compose with a player's own usage rather than replacing it.
    """
    from .config import FANTASY_POSITIONS

    pos_map = data.players().dropna(subset=["gsis_id"]).set_index("gsis_id").position
    pos = passes.receiver_player_id.map(pos_map)
    ok = pos.isin(FANTASY_POSITIONS).to_numpy()
    if ok.sum() < 5000:
        return np.ones(4), np.ones(4)

    codes = pos[ok].map({p: i for i, p in enumerate(("QB", "RB", "WR", "TE"))}).to_numpy(int)
    w = np.asarray(weights)[ok]
    yl = passes.yardline_100.to_numpy(float)[ok]

    def share(mask):
        c = np.bincount(codes[mask], weights=w[mask], minlength=4)
        return c / max(c.sum(), 1e-9)

    overall = share(np.ones(len(codes), dtype=bool))
    rz = share(yl <= 20)
    gl = share(yl <= 5)
    with np.errstate(divide="ignore", invalid="ignore"):
        rz_mult = np.where(overall > 1e-6, rz / overall, 1.0)
        gl_mult = np.where(overall > 1e-6, gl / overall, 1.0)
    # Quarterbacks are not in the target pool; keep their entry neutral.
    rz_mult[0] = gl_mult[0] = 1.0
    return np.clip(rz_mult, 0.4, 2.0), np.clip(gl_mult, 0.4, 2.0)


GRID_SHAPE = (4, len(TOGO_BINS) - 1, len(SD_BINS) - 1, len(TIME_BINS) - 1)


def _grid_index(down, togo, score_diff, secs) -> np.ndarray:
    d = np.clip(np.asarray(down, dtype=int) - 1, 0, 3)
    t = _binidx(togo, TOGO_BINS)
    s = _binidx(score_diff, SD_BINS)
    c = _binidx(secs, TIME_BINS)
    return ((d * GRID_SHAPE[1] + t) * GRID_SHAPE[2] + s) * GRID_SHAPE[3] + c


def _rate_grid(df: pd.DataFrame, y: np.ndarray, prior: float, strength: float,
               weights: np.ndarray | None = None) -> np.ndarray:
    flat = _grid_index(
        df.down.to_numpy(), df.ydstogo.to_numpy(),
        df.score_differential.fillna(0).to_numpy(), df.game_seconds_remaining.fillna(1800).to_numpy(),
    )
    size = int(np.prod(GRID_SHAPE))
    w = np.ones(len(df)) if weights is None else np.asarray(weights, dtype=float)
    den = np.bincount(flat, weights=w, minlength=size).astype(float)
    num = np.bincount(flat, weights=y * w, minlength=size).astype(float)
    return _smooth_rate(num, den, prior, strength).reshape(GRID_SHAPE)


# --------------------------------------------------------------------------
# Layer 2: coaching
# --------------------------------------------------------------------------

def _attach_coaches(pbp: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Label every play with the coach of the team that has the ball."""
    g = games[["game_id", "home_team", "away_team", "home_coach", "away_coach"]]
    m = pbp.merge(g, on="game_id", how="left", suffixes=("", "_g"))
    home_t = m["home_team_g"].fillna(m["home_team"])
    m["off_coach"] = np.where(m.posteam == home_t, m.home_coach, m.away_coach)
    m["def_coach"] = np.where(m.posteam == home_t, m.away_coach, m.home_coach)
    return m


def fit_coaches(pbp: pd.DataFrame, games: pd.DataFrame, physics: LeaguePhysics,
                season: int | None = None,
                halflife: float = HALFLIFE_COACH) -> dict[str, CoachProfile]:
    """Estimate each staff's tendencies as a recency-weighted sum over its seasons.

    A coach's identity is real and persistent -- which is why it is worth
    modelling separately from the team -- but it is not fixed. Play-callers
    adapt to personnel and to the league, so a season from six years ago is
    weak evidence about this year's tendencies while still being evidence.
    Weighting rather than truncating keeps long-tenured coaches well estimated
    without letting their early years dominate.
    """
    m = _attach_coaches(pbp, games)
    reg = m[(m.season_type == "REG") & m.off_coach.notna()]
    target = int(season if season is not None else reg.season.max() + 1)

    calls = reg[
        reg.play_type.isin(["run", "pass"])
        & (reg.qb_kneel != 1)
        & (reg.qb_spike != 1)
        & reg.down.notna()
    ].copy()

    # Pass rate over expected, using our own situational baseline so the
    # measure is consistent with what the engine will actually simulate.
    flat = _grid_index(
        calls.down.to_numpy(), calls.ydstogo.to_numpy(),
        calls.score_differential.fillna(0).to_numpy(),
        calls.game_seconds_remaining.fillna(1800).to_numpy(),
    )
    xp = physics.xpass_grid.reshape(-1)[flat]
    calls["is_pass"] = (calls.play_type == "pass").astype(float)
    calls["pass_oe_own"] = calls.is_pass - xp
    calls["w"] = recency_weights(calls.season.to_numpy(), target, halflife)

    # Neutral-script pace: exclude two-minute and blowout situations, where
    # pace is dictated by the scoreboard rather than by preference.
    neutral = calls[
        (calls.score_differential.abs() <= 10)
        & (calls.half_seconds_remaining > 120)
        & (calls.game_seconds_remaining > 300)
    ].copy()
    allp = reg.sort_values(["game_id", "play_id"]).copy()
    allp["elapsed"] = -allp.groupby("game_id").game_seconds_remaining.diff().shift(-1)
    neutral = neutral.merge(
        allp[["game_id", "play_id", "elapsed"]], on=["game_id", "play_id"], how="left"
    )
    pace_ok = neutral[(neutral.elapsed > 0) & (neutral.elapsed < 60)]

    fourth = reg[(reg.down == 4) & reg.play_type.notna()].copy()
    fourth["went"] = fourth.play_type.isin(["run", "pass"]).astype(float)
    yl_i = _binidx(fourth.yardline_100, YL_BINS)
    tg_i = _binidx(fourth.ydstogo, TOGO_BINS)
    fourth["go_x"] = physics.go_grid[yl_i, tg_i]
    fourth["go_oe"] = fourth.went - fourth.go_x
    fourth["w"] = recency_weights(fourth.season.to_numpy(), target, halflife)

    rz = calls[calls.yardline_100 <= 20]

    profiles: dict[str, CoachProfile] = {}
    league_pace = _wmean(pace_ok.elapsed, pace_ok.w)

    for coach, grp in calls.groupby("off_coach"):
        n = len(grp)
        if n < 200:
            continue
        # Shrink every tendency toward league average by *effective* sample
        # size -- the sum of recency weights, not the raw play count, so a
        # coach whose volume is mostly old is estimated less confidently.
        wsum = float(grp.w.sum())
        k_proe = 1500.0
        proe = float((grp.pass_oe_own * grp.w).sum() / (wsum + k_proe))

        pg = pace_ok[pace_ok.off_coach == coach]
        pw = float(pg.w.sum()) if len(pg) else 0.0
        if pw > 100:
            pace = float(((pg.elapsed * pg.w).sum() + league_pace * 800.0) / (pw + 800.0))
        else:
            pace = league_pace

        fg = fourth[fourth.off_coach == coach]
        fw = float(fg.w.sum()) if len(fg) else 0.0
        go_oe = float((fg.go_oe * fg.w).sum() / (fw + 120.0)) if fw else 0.0

        rg = rz[rz.off_coach == coach]
        rw = float(rg.w.sum()) if len(rg) else 0.0
        rz_oe = float((rg.pass_oe_own * rg.w).sum() / (rw + 400.0)) if rw else 0.0

        profiles[coach] = CoachProfile(
            coach=coach,
            seasons=int(grp.season.nunique()),
            plays=int(n),
            proe=proe,
            sec_per_play=pace,
            go_rate_oe=go_oe,
            rz_pass_oe=rz_oe,
            pass_rush_split_rz=_wmean(rg.is_pass, rg.w) if rw else 0.55,
            shotgun_rate=_wmean(grp.shotgun.fillna(0), grp.w),
            no_huddle_rate=_wmean(grp.no_huddle.fillna(0), grp.w),
        )

    # A neutral profile for coaches with no NFL play-calling history.
    profiles["__LEAGUE__"] = CoachProfile(
        coach="__LEAGUE__", seasons=0, plays=0, proe=0.0,
        sec_per_play=league_pace, go_rate_oe=0.0, rz_pass_oe=0.0,
        pass_rush_split_rz=0.55, shotgun_rate=0.65, no_huddle_rate=0.08,
    )
    return profiles


def coaches_for_season(games: pd.DataFrame, season: int) -> dict[str, str]:
    """Head coach per team for `season`, falling back to the most recent known."""
    s = games[(games.season == season)]
    out: dict[str, str] = {}
    for _, r in s.iterrows():
        if isinstance(r.get("home_coach"), str):
            out.setdefault(r.home_team, r.home_coach)
        if isinstance(r.get("away_coach"), str):
            out.setdefault(r.away_team, r.away_coach)
    if len(out) < 32:
        prev = games[games.season == season - 1]
        for _, r in prev.iterrows():
            if isinstance(r.get("home_coach"), str):
                out.setdefault(r.home_team, r.home_coach)
            if isinstance(r.get("away_coach"), str):
                out.setdefault(r.away_team, r.away_coach)
    return out


# --------------------------------------------------------------------------
# Layer 3: team strength
# --------------------------------------------------------------------------

def _weighted_recent(df: pd.DataFrame, value: str, season_col: str, target: int,
                     halflife: float = 1.0) -> pd.Series:
    """Exponentially weight seasons by recency."""
    w = 0.5 ** ((target - df[season_col]) / halflife)
    return (df[value] * w).groupby(df.index).sum()


def fit_team_strength(
    pbp: pd.DataFrame,
    games: pd.DataFrame,
    physics: LeaguePhysics,
    season: int,
    continuity: dict[str, float],
    lookback: int = 3,
) -> dict[str, TeamStrength]:
    reg = pbp[(pbp.season_type == "REG") & (pbp.season >= season - lookback)].copy()
    reg["w"] = recency_weights(reg.season.to_numpy(), season, HALFLIFE_TEAM)

    coach_map = coaches_for_season(games, season)
    prev_coach = coaches_for_season(games, season - 1)

    def _agg(mask: pd.Series, group: str, col: str, prior: float, k: float) -> pd.Series:
        sub = reg[mask & reg[col].notna()]
        num = (sub[col] * sub.w).groupby(sub[group]).sum()
        den = sub.w.groupby(sub[group]).sum()
        return (num + prior * k) / (den + k)

    is_pass = reg.pass_attempt == 1
    is_rush = (reg.rush_attempt == 1) & (reg.qb_kneel != 1)

    off_pass = _agg(is_pass, "posteam", "epa", physics.league_epa_pass, 700.0)
    off_rush = _agg(is_rush, "posteam", "epa", physics.league_epa_rush, 700.0)
    def_pass = _agg(is_pass, "defteam", "epa", physics.league_epa_pass, 700.0)
    def_rush = _agg(is_rush, "defteam", "epa", physics.league_epa_rush, 700.0)

    # Completion percentage over expected, offense and defense.
    cpoe_mask = is_pass & reg.cpoe.notna()
    off_cpoe = _agg(cpoe_mask, "posteam", "cpoe", 0.0, 800.0) / 100.0
    def_cpoe = _agg(cpoe_mask, "defteam", "cpoe", 0.0, 800.0) / 100.0

    lg_ypc = float(reg.loc[is_rush, "yards_gained"].mean())
    off_ypc = _agg(is_rush, "posteam", "yards_gained", lg_ypc, 900.0) - lg_ypc
    def_ypc = _agg(is_rush, "defteam", "yards_gained", lg_ypc, 900.0) - lg_ypc

    drops = reg[reg.qb_dropback == 1]
    off_sack = (
        (drops.sack.fillna(0) * drops.w).groupby(drops.posteam).sum()
        / drops.w.groupby(drops.posteam).sum()
    ) - physics.sack_rate
    def_sack = (
        (drops.sack.fillna(0) * drops.w).groupby(drops.defteam).sum()
        / drops.w.groupby(drops.defteam).sum()
    ) - physics.sack_rate

    out: dict[str, TeamStrength] = {}
    teams = sorted(set(coach_map) | set(off_pass.index.dropna()))
    for t in teams:
        if not isinstance(t, str) or len(t) > 3:
            continue
        coach = coach_map.get(t, "__LEAGUE__")
        is_new = prev_coach.get(t) != coach
        cont = continuity.get(t, 0.7)

        # A new staff or heavy roster turnover means last year's efficiency is a
        # weaker guide; pull those teams further toward the league mean.
        shrink = 1.0
        if is_new:
            shrink *= 0.72
        shrink *= 0.75 + 0.25 * min(cont / 0.7, 1.4)

        out[t] = TeamStrength(
            team=t,
            off_pass_epa=float(off_pass.get(t, physics.league_epa_pass) - physics.league_epa_pass) * shrink,
            off_rush_epa=float(off_rush.get(t, physics.league_epa_rush) - physics.league_epa_rush) * shrink,
            def_pass_epa=float(def_pass.get(t, physics.league_epa_pass) - physics.league_epa_pass) * shrink,
            def_rush_epa=float(def_rush.get(t, physics.league_epa_rush) - physics.league_epa_rush) * shrink,
            off_comp_oe=float(off_cpoe.get(t, 0.0)) * shrink,
            off_ypc_oe=float(off_ypc.get(t, 0.0)) * shrink,
            def_comp_oe=float(def_cpoe.get(t, 0.0)) * shrink,
            def_ypc_oe=float(def_ypc.get(t, 0.0)) * shrink,
            off_sack_oe=float(off_sack.get(t, 0.0)) * shrink,
            def_sack_oe=float(def_sack.get(t, 0.0)) * shrink,
            pace_sec_play=0.0,
            proe=0.0,
            go_rate_oe=0.0,
            continuity=cont,
            coach=coach,
            coach_is_new=bool(is_new),
        )
    return out


def roster_continuity(season: int) -> dict[str, float]:
    """Share of each team's prior-season snap volume that is still on the roster.

    Free agency and the draft reshape teams every spring; a team returning 45%
    of its snaps should not inherit last year's efficiency as confidently as one
    returning 85%.
    """
    try:
        snaps = data.snap_counts([season - 1])
    except Exception:
        return {}
    cur = data.rosters(season)
    have = set(cur.gsis_id.dropna())

    snaps = snaps.copy()
    # snap_counts identifies players by pfr_player_id; bridge via the roster file.
    prev = data.rosters(season - 1)[["gsis_id", "pfr_id", "team"]].dropna(subset=["pfr_id"])
    bridge = dict(zip(prev.pfr_id, prev.gsis_id))
    snaps["gsis_id"] = snaps.pfr_player_id.map(bridge)

    tot = snaps.groupby("team").offense_snaps.sum()
    kept = snaps[snaps.gsis_id.isin(have)].groupby("team").offense_snaps.sum()
    out = (kept / tot).dropna()
    return {str(k): float(v) for k, v in out.items()}
