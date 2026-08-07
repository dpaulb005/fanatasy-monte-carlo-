"""Player-level priors: who gets the ball, how well they do with it, and who
replaces them when they get hurt.

The engine needs four things per player:

  * a *usage* prior -- share of team targets, share of team carries, share of
    goal-line work, and route participation;
  * an *efficiency* prior -- average depth of target, yards after catch,
    catch rate above expectation, yards per carry above expectation;
  * an *availability* model -- weekly hazard of missing time, with a duration;
  * a place in the *depth chart*, so that when the player ahead goes down the
    vacated usage lands somewhere defensible.

Veterans get all of this from their own recent play, regressed toward their
positional mean by sample size. Rookies have no NFL play, so their prior is
built from draft capital -- empirically the strongest public signal available --
plus athletic testing, and calibrated against what every comparable draft slot
has actually produced since 1999.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import data
from .config import FANTASY_POSITIONS, TARGET_SEASON

# Positional baselines used as shrinkage targets when a player has thin history.
POS_DEFAULTS = {
    "QB": dict(adot=7.8, yac=5.2, ypc_oe=0.0, cr_oe=0.0),
    "RB": dict(adot=0.4, yac=8.2, ypc_oe=0.0, cr_oe=0.0),
    "WR": dict(adot=10.8, yac=4.6, ypc_oe=0.0, cr_oe=0.0),
    "TE": dict(adot=7.9, yac=5.1, ypc_oe=0.0, cr_oe=0.0),
}


@dataclass
class PlayerPrior:
    gsis_id: str
    name: str
    pos: str
    team: str
    age: float
    years_exp: int
    is_rookie: bool

    # Usage, expressed as shares of the team total. Normalised later.
    target_share: float
    rush_share: float
    goalline_share: float
    route_rate: float

    # Efficiency
    adot: float               # average depth of target
    yac_mean: float           # yards after catch
    catch_rate_oe: float      # catch rate above what aDOT implies
    ypc_oe: float             # yards per carry above league average

    # Passing (QBs only)
    pass_adot: float = 0.0
    cpoe: float = 0.0
    sack_rate_oe: float = 0.0
    qb_rush_share: float = 0.0

    # Availability
    injury_rate: float = 0.0      # weekly hazard of a new absence
    injury_duration: float = 2.5  # mean games missed per absence

    depth_rank: int = 9
    draft_pick: float = np.nan
    confidence: float = 0.5       # how much history backs this prior


# --------------------------------------------------------------------------
# Depth charts
# --------------------------------------------------------------------------

OFF_GROUP = "3WR 1TE"
SKILL_ABB = {"QB": "QB", "RB": "RB", "TE": "TE"}
WR_ABB = {"WR", "LWR", "RWR", "SWR"}


def current_depth(season: int) -> pd.DataFrame:
    """Latest published offensive depth chart, one row per player-position."""
    dc = data.depth_charts(season)
    dc = dc[dc.pos_grp == OFF_GROUP]
    latest = dc.dt.max()
    dc = dc[dc.dt == latest].copy()

    def norm(abb: str) -> str | None:
        if abb in WR_ABB:
            return "WR"
        return SKILL_ABB.get(abb)

    dc["pos"] = dc.pos_abb.map(norm)
    dc = dc[dc.pos.notna() & dc.gsis_id.notna()]
    # A player can appear at several WR alignments; keep his best rank.
    dc = (
        dc.sort_values("pos_rank")
        .groupby(["team", "pos", "gsis_id"], as_index=False)
        .first()[["team", "pos", "gsis_id", "player_name", "pos_rank"]]
    )
    # Re-rank within team/position so ranks are dense and ordered.
    dc["depth_rank"] = dc.groupby(["team", "pos"]).pos_rank.rank(method="first").astype(int)
    return dc


# --------------------------------------------------------------------------
# Veteran usage & efficiency priors
# --------------------------------------------------------------------------

def _recency_weights(seasons: pd.Series, target: int, halflife: float = 1.1) -> pd.Series:
    """Exponential decay by seasons elapsed; the season just played weighs 1.0."""
    return 0.5 ** ((target - 1 - seasons) / halflife)


def fit_usage(season: int, lookback: int = 4,
              halflife: float = 1.1) -> pd.DataFrame:
    """Per-player usage and efficiency as a recency-weighted sum over seasons.

    Four seasons rather than one. A single year of target share is a noisy
    estimate of a player's role -- injuries, a quarterback change, six weeks in
    a bad scheme -- and projecting off it alone over-reacts to whatever happened
    most recently. Weighting back through four seasons at a ~1.1 season
    half-life keeps last year dominant while letting an established track record
    stabilise the estimate, and gives players who missed most of a season a
    prior built from when they were actually playing.

    The returned `eff_games` is the recency-weighted game count, which is what
    downstream shrinkage should use: fourteen games two seasons ago is genuinely
    weaker evidence than fourteen games last year, and a raw count cannot say so.
    """
    yrs = list(range(season - lookback, season))
    pw = data.player_week(yrs)
    pw = pw[(pw.season_type == "REG") & pw.position.isin(FANTASY_POSITIONS)].copy()

    pw["w"] = _recency_weights(pw.season, season, halflife)

    # Team weekly totals, so shares are computed against the offence the player
    # actually played in rather than a league average.
    team_tot = pw.groupby(["season", "week", "team"]).agg(
        team_targets=("targets", "sum"),
        team_carries=("carries", "sum"),
        team_pass_yards=("passing_yards", "sum"),
        team_attempts=("attempts", "sum"),
    ).reset_index()
    pw = pw.merge(team_tot, on=["season", "week", "team"], how="left")

    g = pw.groupby("player_id")
    w = pw.w

    def wsum(col):
        return (pw[col].fillna(0) * w).groupby(pw.player_id).sum()

    wt = w.groupby(pw.player_id).sum()
    games = g.size()

    tgt = wsum("targets")
    rec = wsum("receptions")
    rec_yds = wsum("receiving_yards")
    air = wsum("receiving_air_yards")
    yac = wsum("receiving_yards_after_catch")
    car = wsum("carries")
    rush_yds = wsum("rushing_yards")
    att = wsum("attempts")
    cmp_ = wsum("completions")
    pass_yds = wsum("passing_yards")
    pass_air = wsum("passing_air_yards")
    sacks = wsum("sacks_suffered")

    team_tgt = wsum("team_targets")
    team_car = wsum("team_carries")

    info = g.agg(
        name=("player_display_name", "last"),
        pos=("position", "last"),
        last_team=("team", "last"),
        n_games=("week", "size"),
        seasons=("season", "nunique"),
    )

    out = pd.DataFrame({
        "gsis_id": info.index,
        "name": info.name.values,
        "pos": info.pos.values,
        "last_team": info.last_team.values,
        "n_games": info.n_games.values,
        "n_seasons": info.seasons.values,
        # Effective sample size: games discounted by how long ago they were.
        "eff_games": wt.reindex(info.index).values,
        "wt": wt.reindex(info.index).values,
        "targets": tgt.reindex(info.index).values,
        "receptions": rec.reindex(info.index).values,
        "rec_yards": rec_yds.reindex(info.index).values,
        "air_yards": air.reindex(info.index).values,
        "yac": yac.reindex(info.index).values,
        "carries": car.reindex(info.index).values,
        "rush_yards": rush_yds.reindex(info.index).values,
        "attempts": att.reindex(info.index).values,
        "completions": cmp_.reindex(info.index).values,
        "pass_yards": pass_yds.reindex(info.index).values,
        "pass_air_yards": pass_air.reindex(info.index).values,
        "sacks": sacks.reindex(info.index).values,
        "team_targets": team_tgt.reindex(info.index).values,
        "team_carries": team_car.reindex(info.index).values,
    }).set_index("gsis_id")

    out["raw_target_share"] = out.targets / out.team_targets.replace(0, np.nan)
    out["raw_rush_share"] = out.carries / out.team_carries.replace(0, np.nan)
    out["adot"] = out.air_yards / out.targets.replace(0, np.nan)
    out["yac_mean"] = out.yac / out.receptions.replace(0, np.nan)
    out["catch_rate"] = out.receptions / out.targets.replace(0, np.nan)
    out["ypc"] = out.rush_yards / out.carries.replace(0, np.nan)
    out["pass_adot"] = out.pass_air_yards / out.attempts.replace(0, np.nan)
    out["sack_rate"] = out.sacks / (out.attempts + out.sacks).replace(0, np.nan)
    return out.reset_index()


def goalline_shares(season: int, lookback: int = 3) -> pd.DataFrame:
    """Carry share inside the 5, which drives rushing touchdowns."""
    pbp = data.play_by_play(range(season - lookback, season),
                            columns=["season", "season_type", "posteam", "yardline_100",
                                     "rush_attempt", "rusher_player_id", "qb_kneel"])
    p = pbp[(pbp.season_type == "REG") & (pbp.rush_attempt == 1)
            & (pbp.qb_kneel != 1) & (pbp.yardline_100 <= 5)
            & pbp.rusher_player_id.notna()].copy()
    p["w"] = _recency_weights(p.season, season)
    by_player = p.groupby("rusher_player_id").w.sum()
    by_team = p.groupby("posteam").w.sum()
    last_team = p.groupby("rusher_player_id").posteam.last()
    df = pd.DataFrame({"gl_w": by_player, "team": last_team})
    df["team_gl_w"] = df.team.map(by_team)
    df["raw_gl_share"] = df.gl_w / df.team_gl_w
    return df.reset_index().rename(columns={"rusher_player_id": "gsis_id"})


# --------------------------------------------------------------------------
# Rookies: draft capital + athletic profile, calibrated on 1999-2025 outcomes
# --------------------------------------------------------------------------

def fit_rookie_curves(season: int, halflife: float = 5.0) -> dict[str, dict]:
    """What a given draft slot has historically produced in year one.

    For every drafted skill player since 2006 we look up his actual rookie-year
    usage share, then fit a smooth decay of expected share against draft pick.

    The draft classes are recency-weighted with a long half-life. Two decades of
    classes are needed for the curve to be stable at all -- there are only
    thirty-two first-round picks a year, spread over four positions -- but how
    quickly rookies are given real roles has changed a lot over that span, and
    an unweighted mean would project the usage of a 2010 rookie onto a 2026 one.
    A five-season half-life keeps the sample large while letting the modern era
    lead.
    """
    picks = data.draft_picks()
    picks = picks[picks.position.isin(FANTASY_POSITIONS) & (picks.season < season)]

    hist_years = sorted(picks.season.unique())
    hist_years = [y for y in hist_years if y >= 2006]  # weekly stats coverage
    pw = data.player_week(hist_years)
    pw = pw[(pw.season_type == "REG") & pw.position.isin(FANTASY_POSITIONS)]

    team_tot = pw.groupby(["season", "week", "team"]).agg(
        team_targets=("targets", "sum"), team_carries=("carries", "sum"),
    ).reset_index()
    pw = pw.merge(team_tot, on=["season", "week", "team"], how="left")

    agg = pw.groupby(["player_id", "season"]).agg(
        targets=("targets", "sum"), carries=("carries", "sum"),
        team_targets=("team_targets", "sum"), team_carries=("team_carries", "sum"),
        games=("week", "size"), pos=("position", "last"),
    ).reset_index()
    agg["target_share"] = agg.targets / agg.team_targets.replace(0, np.nan)
    agg["rush_share"] = agg.carries / agg.team_carries.replace(0, np.nan)

    rk = picks.merge(
        agg, left_on=["gsis_id", "season"], right_on=["player_id", "season"], how="left"
    )
    rk["target_share"] = rk.target_share.fillna(0.0)
    rk["rush_share"] = rk.rush_share.fillna(0.0)

    curves: dict[str, dict] = {}
    grid = np.arange(1, 300)
    for pos in FANTASY_POSITIONS:
        sub = rk[rk.position == pos]
        sub = sub[sub.pick.notna()]
        if len(sub) < 40:
            curves[pos] = {"target": np.zeros_like(grid, dtype=float),
                           "rush": np.zeros_like(grid, dtype=float)}
            continue
        pick = sub.pick.to_numpy(float)
        # Recency weight per draft class, applied inside the kernel smoother so
        # recent classes dominate the fitted curve without being alone in it.
        rw = _recency_weights(sub.season, season, halflife).to_numpy(float)
        out = {}
        for key, col in (("target", "target_share"), ("rush", "rush_share")):
            y = sub[col].to_numpy(float)
            # Kernel-smooth in log-pick space: draft value is multiplicative.
            lp = np.log(np.clip(pick, 1, None))
            lg = np.log(grid)
            bw = 0.45
            wmat = np.exp(-0.5 * ((lg[:, None] - lp[None, :]) / bw) ** 2) * rw[None, :]
            out[key] = (wmat @ y) / np.maximum(wmat.sum(axis=1), 1e-9)
        curves[pos] = out
    curves["_grid"] = grid
    return curves


def rookie_priors(season: int, curves: dict, depth: pd.DataFrame) -> pd.DataFrame:
    """Priors for the incoming rookie class."""
    picks = data.draft_picks()
    cls = picks[(picks.season == season) & picks.position.isin(FANTASY_POSITIONS)].copy()
    if cls.empty:
        return pd.DataFrame()

    grid = curves["_grid"]
    rows = []
    for _, r in cls.iterrows():
        pos = r.position
        c = curves.get(pos)
        if c is None:
            continue
        pick = float(r.pick) if pd.notna(r.pick) else 280.0
        i = int(np.clip(pick, 1, len(grid)) - 1)
        rows.append({
            "gsis_id": r.gsis_id,
            "name": r.pfr_player_name if isinstance(r.get("pfr_player_name"), str) else r.get("pfr_player_name"),
            "pos": pos,
            "team": r.team,
            "draft_pick": pick,
            "rk_target_share": float(c["target"][i]),
            "rk_rush_share": float(c["rush"][i]),
        })
    out = pd.DataFrame(rows)

    # Athletic testing nudges the prior modestly; draft capital already prices
    # most of it in, so this only separates players picked at the same slot.
    try:
        cmb = data.combine()
        cmb = cmb[cmb.season == season][["pfr_id", "forty", "vertical", "broad_jump", "ht", "wt"]]
        # Speed score for backs, and raw forty for receivers, as z-scores.
        cmb = cmb.dropna(subset=["forty"])
        z = (cmb.forty - cmb.forty.mean()) / cmb.forty.std()
        cmb["athletic_z"] = (-z).clip(-2.5, 2.5)
        picks_ath = picks[picks.season == season][["gsis_id", "pfr_player_id"]]
        cmb = cmb.merge(picks_ath, left_on="pfr_id", right_on="pfr_player_id", how="inner")
        out = out.merge(cmb[["gsis_id", "athletic_z"]], on="gsis_id", how="left")
    except Exception:
        out["athletic_z"] = np.nan
    out["athletic_z"] = out.athletic_z.fillna(0.0)
    out["rk_target_share"] *= (1.0 + 0.06 * out.athletic_z)
    out["rk_rush_share"] *= (1.0 + 0.06 * out.athletic_z)
    return out


# --------------------------------------------------------------------------
# Injury hazards
# --------------------------------------------------------------------------

def fit_injury_hazards(seasons, min_games: int = 3, min_snap_pct: float = 0.5) -> dict:
    """Weekly probability of a new absence, and how long absences last.

    Measured from actual snap participation rather than roster status. Roster
    status conflates injury with practice-squad churn and healthy scratches,
    which inflates both rate and duration badly -- fringe players spend long
    stretches listed as inactive without ever being hurt.

    Three things have to be right for the fit to mean anything:

      * bye weeks are excluded, or every player in the league picks up one fake
        injury a year and the fitted hazard pins to its ceiling;
      * the population is starter-caliber players, defined by snap share *in
        the games they played*, so the filter does not condition on the very
        availability being measured;
      * exposure begins at a player's debut, so a rookie who arrives in week 6
        is not charged five weeks of absence.

    The duration is taken straight from observed absence lengths, and the
    hazard is then set so the model's steady-state absence fraction reproduces
    the observed one. Calibrating the rate rather than counting transitions
    directly keeps the simulated games-played distribution anchored to reality
    instead of merely being in its neighbourhood.
    """
    sc = data.snap_counts(seasons)
    sc = sc[(sc.game_type == "REG") & sc.position.isin(FANTASY_POSITIONS)]
    sc = sc[sc.offense_snaps.fillna(0) > 0]

    weeks = list(range(1, 19))
    played = (
        sc.groupby(["season", "pfr_player_id", "week"]).size()
        .unstack("week").reindex(columns=weeks).notna()
    )
    # A team's bye week is a week with no snaps for anyone on it. Counting it as
    # an absence would hand every player in the league one fake injury a year
    # and drive the fitted hazard straight into its clip ceiling.
    team_weeks = (
        sc.groupby(["season", "team", "week"]).size()
        .unstack("week").reindex(columns=weeks).notna()
    )
    player_team = sc.groupby(["season", "pfr_player_id"]).team.agg(
        lambda s: s.value_counts().index[0]
    )
    pos = sc.groupby("pfr_player_id").position.last()
    # Snap share is averaged over appearances only, so the role filter is
    # independent of how many games the player was available for.
    snap_pct = sc.groupby(["season", "pfr_player_id"]).offense_pct.mean()

    arr = played.to_numpy()
    keys = played.index
    pos_arr = pd.Series(keys.get_level_values("pfr_player_id")).map(pos).fillna("WR").to_numpy()
    pct_arr = snap_pct.reindex(keys).fillna(0.0).to_numpy()

    teams_for_rows = player_team.reindex(keys)
    tw_lookup = {k: row for k, row in zip(team_weeks.index, team_weeks.to_numpy())}
    active_weeks = np.array([
        tw_lookup.get((s, t), np.ones(len(weeks), dtype=bool))
        for (s, _), t in zip(keys, teams_for_rows)
    ])

    hazards, durations = {}, {}
    for p in FANTASY_POSITIONS:
        sel = (pos_arr == p) & (arr.sum(axis=1) >= min_games) & (pct_arr >= min_snap_pct)
        rows, masks = arr[sel], active_weeks[sel]
        if rows.shape[0] == 0:
            hazards[p], durations[p] = 0.045, 2.6
            continue

        missed = exposure = 0
        runs: list[int] = []
        for row, mask in zip(rows, masks):
            span = row[mask]                     # drop the bye
            if span.size < 2:
                continue
            span = span[int(np.argmax(span)):]   # exposure starts at his debut
            if span.size < 2:
                continue
            missed += int((~span).sum())
            exposure += int(span.size)
            length = 0
            for v in span:
                if not v:
                    length += 1
                elif length:
                    runs.append(length)
                    length = 0
            if length:
                runs.append(length)

        dur = float(np.clip(np.mean(runs) if runs else 2.6, 1.0, 6.0))
        frac = float(np.clip(missed / max(exposure, 1), 0.005, 0.5))
        # Steady state of the absence process: f = r*d / (1 + r*d).
        hazards[p] = float(np.clip(frac / (dur * (1.0 - frac)), 0.005, 0.15))
        durations[p] = dur

    return {"hazard": hazards, "duration": durations}


def availability_history(seasons) -> pd.DataFrame:
    """Each player's own record of being on the field.

    The positional hazard is an average over a population that mixes entrenched
    starters with players who lose their jobs -- which is why the fitted
    quarterback rate is so high, since it absorbs benchings alongside injuries.
    A player with a long record of taking every snap should not be charged that
    average, and one with a long record of missing time should be charged more.
    """
    sc = data.snap_counts(seasons)
    sc = sc[(sc.game_type == "REG") & sc.position.isin(FANTASY_POSITIONS)]
    sc = sc[sc.offense_snaps.fillna(0) > 0]

    team_weeks = sc.groupby(["season", "team"]).week.nunique()
    played = sc.groupby(["season", "pfr_player_id"]).agg(
        weeks=("week", "nunique"), team=("team", lambda s: s.value_counts().index[0]),
        pct=("offense_pct", "mean"),
    ).reset_index()
    played["team_weeks"] = [
        team_weeks.get((s, t), 17) for s, t in zip(played.season, played.team)
    ]
    # Only seasons where the player held a real role say anything about his
    # availability; a rotational year is not evidence of durability either way.
    played = played[played.pct >= 0.4]
    agg = played.groupby("pfr_player_id").agg(
        played_weeks=("weeks", "sum"), possible=("team_weeks", "sum"), n=("season", "size")
    )
    agg["avail_rate"] = agg.played_weeks / agg.possible.clip(lower=1)
    return agg.reset_index()


def personal_injury_multiplier(avail_rate: float, n_seasons: float,
                               pos_rate: float) -> float:
    """Scale the positional hazard by a player's own durability record.

    Shrunk hard toward 1.0 -- availability is famously noisy year to year, so a
    single healthy season is close to no evidence, and even a long record moves
    the estimate only part of the way.
    """
    if not np.isfinite(avail_rate) or not np.isfinite(n_seasons) or n_seasons <= 0:
        return 1.0
    miss = np.clip(1.0 - avail_rate, 0.0, 0.6)
    ratio = miss / max(pos_rate, 1e-3)
    weight = float(np.clip(n_seasons / (n_seasons + 3.0), 0.0, 0.6))
    return float(np.clip(1.0 + weight * (ratio - 1.0), 0.45, 2.0))


def age_injury_multiplier(age: float, pos: str) -> float:
    """Older players get hurt more, and running backs age fastest."""
    if not np.isfinite(age):
        return 1.0
    pivot = 26.0 if pos == "RB" else 27.0
    slope = 0.055 if pos == "RB" else 0.035
    return float(np.clip(1.0 + slope * (age - pivot), 0.7, 2.2))
