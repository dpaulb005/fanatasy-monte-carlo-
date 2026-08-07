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


@dataclass
class LeaguePhysics:
    """How a play resolves, league-wide."""

    # Completion probability by air-yards bin.
    comp_by_ay: np.ndarray
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

    # League baseline pass rate on a (down, togo, score, time) grid.
    xpass_grid: np.ndarray
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

def fit_league_physics(pbp: pd.DataFrame) -> LeaguePhysics:
    p = pbp
    reg = p[(p.season_type == "REG")]

    # ---- Passing ---------------------------------------------------------
    passes = reg[(reg.pass_attempt == 1) & (reg.sack != 1) & reg.air_yards.notna()]
    ay_idx = _binidx(passes.air_yards, AY_BINS)
    comp = passes.complete_pass.fillna(0).to_numpy(float)
    ints = passes.interception.fillna(0).to_numpy(float)

    n_ay = len(AY_BINS) - 1
    den = np.bincount(ay_idx, minlength=n_ay).astype(float)
    comp_by_ay = _smooth_rate(np.bincount(ay_idx, weights=comp, minlength=n_ay), den, comp.mean(), 200.0)
    int_by_ay = _smooth_rate(np.bincount(ay_idx, weights=ints, minlength=n_ay), den, ints.mean(), 400.0)

    completions = passes[passes.complete_pass == 1]
    c_idx = _binidx(completions.air_yards, AY_BINS)
    yac = completions.yards_after_catch.fillna(0).clip(lower=0).to_numpy(float)
    c_den = np.bincount(c_idx, minlength=n_ay).astype(float)
    yac_mean_by_ay = _smooth_rate(
        np.bincount(c_idx, weights=yac, minlength=n_ay), c_den, yac.mean(), 100.0
    )
    # Gamma shape from the overall YAC distribution (method of moments).
    yac_shape = float(max(0.35, yac.mean() ** 2 / max(yac.var(), 1e-6)))

    # Residual spread of air yards around a passer's average intent.
    ay_sd = float(passes.groupby("passer_player_id").air_yards.std().median())

    # ---- Rushing ---------------------------------------------------------
    rushes = reg[(reg.rush_attempt == 1) & (reg.qb_kneel != 1) & reg.yards_gained.notna()]
    ry = rushes.yards_gained.to_numpy(float)
    shift = 5.0
    shifted = np.clip(ry + shift, 0.05, None)
    m, v = shifted.mean(), shifted.var()
    rush_shape = float(m * m / v)
    rush_scale = float(v / m)
    rush_stuff_rate = float((ry <= 0).mean())

    # Goal-line rushing converts at a very different rate than the gamma implies.
    gl = rushes[rushes.yardline_100 <= 10]
    gl_idx = _binidx(gl.yardline_100, np.arange(0, 12, 1.0))
    gl_td = gl.rush_touchdown.fillna(0).to_numpy(float)
    gl_den = np.bincount(gl_idx, minlength=11).astype(float)
    rush_td_boost = _smooth_rate(
        np.bincount(gl_idx, weights=gl_td, minlength=11), gl_den, gl_td.mean(), 50.0
    )

    dropbacks = reg[reg.qb_dropback == 1]
    sack_rate = float(dropbacks.sack.fillna(0).mean())
    sacks = reg[reg.sack == 1]
    sack_yards_mean = float(-sacks.yards_gained.mean()) if len(sacks) else 6.5
    sack_fumble_rate = float(sacks.fumble_lost.fillna(0).mean()) if len(sacks) else 0.03
    rush_fumble_rate = float(rushes.fumble_lost.fillna(0).mean())
    rec_fumble_rate = float(completions.fumble_lost.fillna(0).mean())

    # ---- Kicking ---------------------------------------------------------
    fgs = reg[(reg.field_goal_attempt == 1) & reg.kick_distance.notna()]
    dist = fgs.kick_distance.clip(15, 70).to_numpy(int)
    made = (fgs.field_goal_result == "made").to_numpy(float)
    fg_by_distance = np.zeros(75)
    d_den = np.bincount(dist, weights=None, minlength=75).astype(float)
    d_num = np.bincount(dist, weights=made, minlength=75).astype(float)
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
    xp_rate = float((xps.extra_point_result == "good").mean()) if len(xps) else 0.945
    twos = reg[reg.two_point_attempt == 1]
    two_pt_rate = float((twos.two_point_conv_result == "success").mean()) if len(twos) else 0.48

    punts = reg[reg.punt_attempt == 1]
    punt_net_mean = float(punts.kick_distance.mean()) if len(punts) else 45.0
    punt_net_sd = float(punts.kick_distance.std()) if len(punts) else 9.0
    touchback_rate = 0.12

    # ---- Clock -----------------------------------------------------------
    # Runoff must be measured against the *next play of any kind*. Filtering to
    # scrimmage plays first and then differencing would silently charge the
    # punt, the change of possession and the kickoff to the preceding snap.
    allp = reg.sort_values(["game_id", "play_id"]).copy()
    allp["elapsed"] = -allp.groupby("game_id").game_seconds_remaining.diff().shift(-1)
    scr = allp[allp.play_type.isin(["run", "pass"])]
    ok = scr[(scr.elapsed > 0) & (scr.elapsed < 60)]
    sec_run = float(ok[ok.play_type == "run"].elapsed.mean())
    sec_pass_complete = float(ok[(ok.play_type == "pass") & (ok.complete_pass == 1)].elapsed.mean())
    sec_pass_incomplete = float(ok[(ok.play_type == "pass") & (ok.complete_pass != 1)].elapsed.mean())
    # Two-minute-drill compression.
    hurry = ok[(ok.half_seconds_remaining < 120)]
    sec_hurry = float(hurry.elapsed.mean()) if len(hurry) else 22.0

    # ---- Situational pass rate grid --------------------------------------
    calls = reg[
        reg.play_type.isin(["run", "pass"])
        & (reg.qb_kneel != 1)
        & (reg.qb_spike != 1)
        & reg.down.notna()
    ]
    xpass_grid = _rate_grid(
        calls, (calls.play_type == "pass").to_numpy(float), prior=0.57, strength=60.0
    )

    # ---- Fourth down go rate --------------------------------------------
    fourth = reg[(reg.down == 4) & reg.play_type.notna()]
    went = fourth.play_type.isin(["run", "pass"]).to_numpy(float)
    yl_i = _binidx(fourth.yardline_100, YL_BINS)
    tg_i = _binidx(fourth.ydstogo, TOGO_BINS)
    shape = (len(YL_BINS) - 1, len(TOGO_BINS) - 1)
    flat = yl_i * shape[1] + tg_i
    den4 = np.bincount(flat, minlength=shape[0] * shape[1]).astype(float)
    num4 = np.bincount(flat, weights=went, minlength=shape[0] * shape[1]).astype(float)
    go_grid = _smooth_rate(num4, den4, float(went.mean()), 25.0).reshape(shape)

    off = reg[reg.epa.notna()]
    league_epa_pass = float(off[off.pass_attempt == 1].epa.mean())
    league_epa_rush = float(off[off.rush_attempt == 1].epa.mean())
    plays_per_team_game = (
        calls.groupby(["game_id", "posteam"]).size().mean()
    )

    return LeaguePhysics(
        comp_by_ay=comp_by_ay,
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
        xpass_grid=xpass_grid,
        go_grid=go_grid,
        league_epa_pass=league_epa_pass,
        league_epa_rush=league_epa_rush,
        league_plays_per_game=float(plays_per_team_game),
    )


GRID_SHAPE = (4, len(TOGO_BINS) - 1, len(SD_BINS) - 1, len(TIME_BINS) - 1)


def _grid_index(down, togo, score_diff, secs) -> np.ndarray:
    d = np.clip(np.asarray(down, dtype=int) - 1, 0, 3)
    t = _binidx(togo, TOGO_BINS)
    s = _binidx(score_diff, SD_BINS)
    c = _binidx(secs, TIME_BINS)
    return ((d * GRID_SHAPE[1] + t) * GRID_SHAPE[2] + s) * GRID_SHAPE[3] + c


def _rate_grid(df: pd.DataFrame, y: np.ndarray, prior: float, strength: float) -> np.ndarray:
    flat = _grid_index(
        df.down.to_numpy(), df.ydstogo.to_numpy(),
        df.score_differential.fillna(0).to_numpy(), df.game_seconds_remaining.fillna(1800).to_numpy(),
    )
    size = int(np.prod(GRID_SHAPE))
    den = np.bincount(flat, minlength=size).astype(float)
    num = np.bincount(flat, weights=y, minlength=size).astype(float)
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


def fit_coaches(pbp: pd.DataFrame, games: pd.DataFrame, physics: LeaguePhysics) -> dict[str, CoachProfile]:
    m = _attach_coaches(pbp, games)
    reg = m[(m.season_type == "REG") & m.off_coach.notna()]

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

    rz = calls[calls.yardline_100 <= 20]

    profiles: dict[str, CoachProfile] = {}
    league_pace = float(pace_ok.elapsed.mean())

    for coach, grp in calls.groupby("off_coach"):
        n = len(grp)
        if n < 200:
            continue
        # Shrink every tendency toward league average by sample size.
        k_proe = 1500.0
        proe = float(grp.pass_oe_own.sum() / (n + k_proe))

        pg = pace_ok[pace_ok.off_coach == coach]
        if len(pg) > 100:
            pace = float((pg.elapsed.sum() + league_pace * 800.0) / (len(pg) + 800.0))
        else:
            pace = league_pace

        fg = fourth[fourth.off_coach == coach]
        go_oe = float(fg.go_oe.sum() / (len(fg) + 120.0)) if len(fg) else 0.0

        rg = rz[rz.off_coach == coach]
        rz_oe = float(rg.pass_oe_own.sum() / (len(rg) + 400.0)) if len(rg) else 0.0

        profiles[coach] = CoachProfile(
            coach=coach,
            seasons=int(grp.season.nunique()),
            plays=int(n),
            proe=proe,
            sec_per_play=pace,
            go_rate_oe=go_oe,
            rz_pass_oe=rz_oe,
            pass_rush_split_rz=float(rg.is_pass.mean()) if len(rg) else 0.55,
            shotgun_rate=float(grp.shotgun.fillna(0).mean()),
            no_huddle_rate=float(grp.no_huddle.fillna(0).mean()),
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
    reg["w"] = 0.5 ** ((season - reg.season) / 1.15)

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
