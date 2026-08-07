"""Assemble the simulation inputs.

This is where the separate estimates -- league physics, coaching identity, team
strength, individual usage, rookie draft capital, injury hazards -- are joined
into the per-team objects the engine consumes.

The load-bearing idea is that a player's *share* of his offence is not a
property he carries between buildings. A receiver who commanded a quarter of
the targets on a bad team does not command a quarter of them after signing
somewhere with two better receivers already on the roster. So history is first
converted into a role-independent *usage weight*, weights are combined with a
depth-chart baseline according to how much history actually backs them, and
only then are weights normalised into shares inside the player's 2026 offence.
That normalisation is what makes team changes, the draft, and injuries all
behave sensibly through a single mechanism.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, players as pl, priors
from .config import FANTASY_POSITIONS, PBP_SEASONS, TARGET_SEASON
from .engine import TeamModel

POS_CODE = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}

# How many roster slots per position each simulated offence carries. Deep enough
# that an injury cascade has somewhere to go, shallow enough to stay fast.
SLOTS = {"QB": 3, "RB": 5, "WR": 7, "TE": 4}


@dataclass
class Bundle:
    """Everything needed to run a season, and to interpret the output."""

    physics: priors.LeaguePhysics
    teams: dict[str, TeamModel]
    player_table: pd.DataFrame     # global index -> identity
    injury_rate: np.ndarray        # (P,) weekly hazard
    injury_dur: np.ndarray         # (P,) mean games missed
    schedule: pd.DataFrame
    role_sigma: dict[str, float]     # season-to-season role volatility, by position
    team_shock: dict[str, float]     # season-to-season team efficiency volatility
    coach_table: pd.DataFrame
    strength_table: pd.DataFrame
    season: int
    td_sigma: float = 0.0            # season-to-season scoring-rate dispersion

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self, fh, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load(path: Path) -> "Bundle":
        with open(path, "rb") as fh:
            return pickle.load(fh)


# --------------------------------------------------------------------------
# Empirical baselines by depth-chart rank
# --------------------------------------------------------------------------

def fit_rank_baselines(season: int, lookback: int = 6,
                       halflife: float = priors.HALFLIFE_BASELINE) -> dict[tuple[str, int], dict]:
    """Typical share of an offence commanded by the Nth man at a position.

    Derived by ranking each historical team's players by realised share and
    averaging across team-seasons, so it is free of depth-chart schema drift
    and reflects how touches are actually distributed rather than how a team
    listed its roster in August.

    Averaged over six past seasons with recency weighting rather than a single
    year: these baselines are what a player with little history falls back on,
    so they need to be stable, but how concentrated NFL offences are does drift
    (backfields have committee-ised, target trees have narrowed) and a flat
    six-year mean would lag that.
    """
    yrs = list(range(season - lookback, season))
    pw = data.player_week(yrs)
    pw = pw[(pw.season_type == "REG") & pw.position.isin(FANTASY_POSITIONS)]

    agg = pw.groupby(["season", "team", "player_id", "position"], as_index=False).agg(
        targets=("targets", "sum"), carries=("carries", "sum"),
    )
    team_tot = agg.groupby(["season", "team"], as_index=False).agg(
        tt=("targets", "sum"), tc=("carries", "sum")
    )
    agg = agg.merge(team_tot, on=["season", "team"])
    agg["tshare"] = agg.targets / agg.tt.replace(0, np.nan)
    agg["rshare"] = agg.carries / agg.tc.replace(0, np.nan)
    agg["w"] = priors.recency_weights(agg.season.to_numpy(), season, halflife)

    out: dict[tuple[str, int], dict] = {}
    for pos in FANTASY_POSITIONS:
        sub = agg[agg.position == pos].copy()
        key = "rshare" if pos == "RB" else "tshare"
        sub["rank"] = sub.groupby(["season", "team"])[key].rank(ascending=False, method="first")
        for r in range(1, SLOTS[pos] + 1):
            s = sub[sub["rank"] == r]
            out[(pos, r)] = {
                "tshare": priors._wmean(s.tshare, s.w) if len(s) else 0.01,
                "rshare": priors._wmean(s.rshare, s.w) if len(s) else 0.01,
            }
    return out


# --------------------------------------------------------------------------
# Roster assembly
# --------------------------------------------------------------------------

def _team_roster(depth: pd.DataFrame, roster: pd.DataFrame, team: str) -> pd.DataFrame:
    """The players who will actually take snaps, in depth order."""
    d = depth[depth.team == team]
    frames = []
    for pos, cap in SLOTS.items():
        sub = d[d.pos == pos].sort_values("depth_rank").head(cap).copy()
        if len(sub) < cap:
            # Backfill from the roster so the injury cascade never runs dry.
            have = set(sub.gsis_id)
            extra = roster[
                (roster.team == team) & (roster.position == pos) & (~roster.gsis_id.isin(have))
            ].head(cap - len(sub))
            if len(extra):
                sub = pd.concat([sub, pd.DataFrame({
                    "team": team, "pos": pos, "gsis_id": extra.gsis_id.values,
                    "player_name": extra.full_name.values,
                    "depth_rank": np.arange(len(sub) + 1, len(sub) + 1 + len(extra)),
                })], ignore_index=True)
        sub["pos"] = pos
        sub["depth_rank"] = np.arange(1, len(sub) + 1)
        frames.append(sub)
    return pd.concat(frames, ignore_index=True)


def _redistribution(pos_arr: np.ndarray, depth_arr: np.ndarray) -> np.ndarray:
    """Where an absent player's usage goes.

    Column j spreads player j's vacated share. Most of it lands on the players
    behind him at his own position -- that is what a depth chart is for -- and
    the remainder leaks to the rest of the offence in proportion to position,
    because coordinators do redistribute across positions when a starter is out.
    """
    n = len(pos_arr)
    R = np.zeros((n, n))
    for j in range(n):
        same = np.flatnonzero((pos_arr == pos_arr[j]) & (np.arange(n) != j))
        other = np.flatnonzero(pos_arr != pos_arr[j])
        w = np.zeros(n)
        if same.size:
            # Weight by proximity on the depth chart: the direct backup absorbs
            # most of the vacancy.
            prox = 1.0 / (1.0 + np.abs(depth_arr[same] - depth_arr[j]))
            w[same] = 0.78 * prox / prox.sum()
        if other.size:
            w[other] = 0.22 / other.size
        if w.sum() <= 0:
            w[:] = 1.0 / max(n - 1, 1)
            w[j] = 0.0
        R[:, j] = w / w.sum()
    return R


def build(season: int = TARGET_SEASON, pbp_seasons=PBP_SEASONS, verbose: bool = True,
          as_of: str | None = None) -> Bundle:
    """Fit the whole model for `season`.

    `as_of` caps the depth chart snapshot, which is the one input that can leak
    the future in a backtest. Every other fit is already bounded by `season`.
    """
    def log(msg):
        if verbose:
            print(msg, flush=True)

    log("loading play-by-play ...")
    pbp = data.play_by_play(pbp_seasons)
    # Nothing from the season being projected may inform the projection.
    pbp = pbp[pbp.season < season]
    games = data.games()

    log("fitting league physics ...")
    physics = priors.fit_league_physics(pbp, season)

    log("fitting coaching profiles ...")
    coach_profiles = priors.fit_coaches(pbp, games, physics, season)
    coach_map = priors.coaches_for_season(games, season)
    league_pace = coach_profiles["__LEAGUE__"].sec_per_play

    log("measuring roster continuity ...")
    continuity = priors.roster_continuity(season)

    log("fitting team strength ...")
    strength = priors.fit_team_strength(pbp, games, physics, season, continuity)

    log("fitting player usage ...")
    usage = pl.fit_usage(season)
    gl = pl.goalline_shares(season)
    usage = usage.merge(gl[["gsis_id", "raw_gl_share"]], on="gsis_id", how="left")
    usage = usage.set_index("gsis_id")

    team_frac = pl.team_weight_fractions(season)
    team_frac_map = {(r.gsis_id, r.team): r.frac for r in team_frac.itertuples()}
    move_penalty = pl.fit_team_change_penalty(season)

    log("fitting rookie draft-capital curves ...")
    curves = pl.fit_rookie_curves(season)

    log("loading depth charts and rosters ...")
    depth = pl.current_depth(season, as_of=as_of)
    roster = data.rosters(season)

    log("splitting rushing efficiency at the point of contact ...")
    # Must follow the roster load: PFR keys players by its own id, and the
    # roster is what bridges that back to gsis.
    contact = pl.fit_contact_splits(season)
    pfr_to_gsis = roster.dropna(subset=["pfr_id"]).set_index("pfr_id").gsis_id.to_dict()
    yac_by_gsis = {pfr_to_gsis[k]: v for k, v in contact["player_yac"].items()
                   if k in pfr_to_gsis}
    rookies = pl.rookie_priors(season, curves, depth)
    rookies = rookies.set_index("gsis_id") if not rookies.empty else pd.DataFrame()

    log("fitting injury hazards ...")
    haz = pl.fit_injury_hazards(range(season - 8, season))
    role_sigma = pl.fit_role_volatility(season)
    team_shock = priors.fit_team_shock_sigmas(pbp)
    td_sigma = pl.fit_td_dispersion(season)
    avail_hist = pl.availability_history(range(season - 4, season))
    # snap_counts identifies players by their PFR id, so bridge back to gsis.
    bridge = roster.dropna(subset=["pfr_id"]).set_index("pfr_id").gsis_id.to_dict()
    avail_hist["gsis_id"] = avail_hist.pfr_player_id.map(bridge)
    avail_map = avail_hist.dropna(subset=["gsis_id"]).set_index("gsis_id")[
        ["avail_rate", "n"]
    ].to_dict("index")

    baselines = fit_rank_baselines(season)

    # ---- QB rushing propensity -----------------------------------------
    qb_rush = _qb_rush_rates(season)

    # ---- assemble ------------------------------------------------------
    all_teams = sorted(depth.team.unique())
    rows, team_models = [], {}
    gindex = 0

    birth = roster.set_index("gsis_id").birth_date.to_dict() if "birth_date" in roster else {}
    exp = roster.set_index("gsis_id").years_exp.to_dict() if "years_exp" in roster else {}

    for team in all_teams:
        tr = _team_roster(depth, roster, team)
        if tr.empty:
            continue
        n = len(tr)
        pos_arr = tr.pos.to_numpy()
        depth_arr = tr.depth_rank.to_numpy()
        pos_code = np.array([POS_CODE[p] for p in pos_arr])

        tw = np.zeros(n)   # target weight
        rw = np.zeros(n)   # rush weight
        gw = np.zeros(n)   # goal-line weight
        adot = np.zeros(n)
        yac = np.zeros(n)
        catch_oe = np.zeros(n)
        ypc_oe = np.zeros(n)
        qb_cpoe = np.zeros(n)
        qb_adot = np.zeros(n)
        qb_sack = np.zeros(n)
        qb_rsh = np.zeros(n)
        conf_arr = np.zeros(n)
        inj_rate = np.zeros(n)
        inj_dur = np.zeros(n)
        gidx = np.zeros(n, dtype=int)

        for i, r in tr.reset_index(drop=True).iterrows():
            pid, pos = r.gsis_id, r.pos
            base = baselines.get((pos, int(min(r.depth_rank, SLOTS[pos]))),
                                 {"tshare": 0.02, "rshare": 0.02})
            d = pl.POS_DEFAULTS[pos]

            hist = usage.loc[pid] if pid in usage.index else None
            is_rookie = (not isinstance(hist, pd.Series)) and (
                len(rookies) and pid in rookies.index
            )

            # Confidence in a player's own history, using the *recency-weighted*
            # game count rather than the raw one: a player whose volume is all
            # from three seasons ago should not be trusted as though he played
            # it last year.
            #
            # The shrinkage constant was 14, which left an established starter
            # at only ~0.70 and visibly flattened the top of every position --
            # players with four years of evidence that they command a quarter
            # of an offence were dragged a third of the way back to the
            # positional average. Target share is a sticky trait; 8 puts a
            # four-year veteran near 0.80 while still shrinking a four-game
            # sample to 0.33, which is the behaviour that was wanted.
            ngames = float(hist.eff_games) if isinstance(hist, pd.Series) else 0.0
            conf = float(np.clip(ngames / (ngames + 8.0), 0.0, 0.92))

            # A usage share describes an opportunity structure, not a property
            # the player carries with him. History earned somewhere else is
            # weaker evidence about the role he is walking into, by a measured
            # amount -- a receiver's prior share retains only ~58% of its
            # information after a move, a back ~72%. Without this a back who
            # led another team's backfield imports that workload into a depth
            # chart where he is listed second, and the starter ahead of him
            # gets diluted at normalisation.
            if isinstance(hist, pd.Series):
                same = float(team_frac_map.get((pid, team), 0.0))
                ratio = move_penalty.get(pos, 0.7)
                conf *= ratio + (1.0 - ratio) * same

            if is_rookie:
                rk = rookies.loc[pid]
                t_own = float(rk.rk_target_share)
                r_own = float(rk.rk_rush_share)
                # Draft capital is a real signal but a noisy one, so it never
                # fully overrides where the staff has actually listed him.
                conf = 0.45
            elif isinstance(hist, pd.Series):
                t_own = float(hist.raw_target_share) if np.isfinite(hist.raw_target_share) else base["tshare"]
                r_own = float(hist.raw_rush_share) if np.isfinite(hist.raw_rush_share) else base["rshare"]
            else:
                t_own, r_own = base["tshare"], base["rshare"]

            # A rank-gap penalty used to sit here, dividing confidence when a
            # player's history implied a better job than his listed depth slot,
            # on the theory that the depth chart is current information and a
            # usage share is stale. It was removed because the data contradicts
            # it. Asking which predicts realised usage better, by position:
            #
            #                  depth rank   prior season
            #   RB  2024/25       .731/.750    .721/.827
            #   WR  2024/25       .451/.732    .718/.774
            #   TE  2024/25       .452/.778    .733/.775
            #
            # The prior season wins in four of six, decisively for receivers.
            # And restricting to exactly the case the penalty fired on -- chart
            # and history disagreeing by two or more ranks -- history still wins
            # for WR (.804 vs .700, n=24), while RB and TE have only four such
            # cases across two seasons to judge from. So it was a mechanism
            # built to fix two running backs, applied league-wide, and it cost
            # receiver accuracy: WR backtest correlation fell .581 to .464.
            #
            # The confidence-weighted normalisation below handles the same
            # problem without asserting anything about who is right, since a
            # stale share is a low-confidence estimate and absorbs the
            # reconciliation error on those grounds alone.
            tw[i] = conf * t_own + (1 - conf) * base["tshare"]
            rw[i] = conf * r_own + (1 - conf) * base["rshare"]

            gl_own = (
                float(hist.raw_gl_share)
                if isinstance(hist, pd.Series) and np.isfinite(getattr(hist, "raw_gl_share", np.nan))
                else np.nan
            )
            # Goal-line work correlates with early-down rushing but is more
            # concentrated, so the rushing weight is sharpened rather than copied.
            gw[i] = gl_own * conf + (1 - conf) * (rw[i] ** 1.4) if np.isfinite(gl_own) else rw[i] ** 1.4

            if isinstance(hist, pd.Series):
                adot[i] = _pick(hist.adot, d["adot"], conf)
                yac[i] = _pick(hist.yac_mean, d["yac"], conf)
                cr = hist.catch_rate
                # Catch rate above what the receiver's depth of target implies.
                if np.isfinite(cr) and np.isfinite(hist.adot):
                    ai = priors._binidx([hist.adot], priors.AY_BINS)[0]
                    catch_oe[i] = np.clip((cr - physics.comp_by_ay[ai]) * conf, -0.12, 0.12)
                # Only the after-contact half of rushing efficiency belongs to
                # the player; the before-contact half is his line and is
                # applied at team level instead. Falls back to the raw
                # yards-per-carry residual when PFR has no split for him.
                # yards/carry = before contact + after contact, exactly, so the
                # player's share of the residual is his after-contact delta with
                # no scaling. Quarterbacks are excluded: their carries are
                # scrambles and sneaks, which the handoff-oriented contact split
                # does not describe -- charging Hurts his -0.60 after-contact
                # figure would erase the scramble yardage that is most of his
                # rushing value.
                if pos != "QB" and pid in yac_by_gsis:
                    ypc_oe[i] = float(np.clip(yac_by_gsis[pid], -1.2, 1.2))
                elif np.isfinite(hist.ypc):
                    ypc_oe[i] = float(np.clip((float(hist.ypc) - 4.3) * conf * 0.5, -0.8, 0.8))
                if pos == "QB":
                    qb_adot[i] = _pick(hist.pass_adot, d["adot"], conf)
                    qb_sack[i] = np.clip((float(hist.sack_rate) - physics.sack_rate) * conf, -0.05, 0.09) \
                        if np.isfinite(hist.sack_rate) else 0.0
                    # Accuracy above the league curve at the same depth of
                    # target, which is what separates passers once aDOT is
                    # already accounted for.
                    if np.isfinite(hist.catch_rate) and np.isfinite(hist.pass_adot):
                        ai = priors._binidx([hist.pass_adot], priors.AY_BINS)[0]
                        obs = float(hist.completions) / max(float(hist.attempts), 1.0)
                        qb_cpoe[i] = np.clip((obs - physics.comp_by_ay[ai]) * conf, -0.10, 0.10)
            else:
                adot[i], yac[i] = d["adot"], d["yac"]
                if pos == "QB":
                    qb_adot[i] = d["adot"]

            if pos == "QB":
                # A quarterback with no history gets the league-typical keeper
                # rate. Quarterbacks are excluded from the target and carry
                # pools -- their rushing is drawn separately, off the top.
                qb_rsh[i] = float(qb_rush.get(pid, 0.06))
                adot[i] = 0.0
                tw[i] = rw[i] = gw[i] = 0.0

            conf_arr[i] = conf
            age = _age(birth.get(pid), season)
            base_h = haz["hazard"].get(pos, 0.05)
            inj_rate[i] = base_h * pl.age_injury_multiplier(age, pos)
            inj_dur[i] = haz["duration"].get(pos, 2.6)

            ah = avail_map.get(pid, {})
            pos_miss = base_h * haz["duration"].get(pos, 2.6)
            pos_miss = pos_miss / (1.0 + pos_miss)
            gidx[i] = gindex
            rows.append({
                "gindex": gindex, "gsis_id": pid, "name": r.player_name,
                "pos": pos, "team": team, "depth_rank": int(r.depth_rank),
                "age": age, "is_rookie": bool(is_rookie),
                "years_exp": exp.get(pid, np.nan),
                "conf": conf,
                "avail_mult": pl.personal_injury_multiplier(
                    ah.get("avail_rate", np.nan), ah.get("n", 0.0), pos_miss
                ),
            })
            gindex += 1

        # Normalise weights into shares inside this offence. The budget is what
        # is actually left after the quarterback's own carries, since the engine
        # takes those off the top before distributing the rest.
        qb1 = int(np.flatnonzero(pos_code == 0)[0]) if (pos_code == 0).any() else None
        rush_budget = float(np.clip(1.0 - (qb_rsh[qb1] if qb1 is not None else 0.08),
                                    0.55, 0.95))
        tw = _confidence_norm(tw, conf_arr, 1.0)
        rw = _confidence_norm(rw, conf_arr, rush_budget)
        gw = _confidence_norm(gw, conf_arr, rush_budget)
        # Zone-specific target shares: the same players, reweighted by how the
        # league actually redistributes targets as the field shortens, then
        # renormalised so each zone is its own distribution.
        rz_tw = _norm(tw * physics.rz_target_mult[pos_code])
        gl_tw = _norm(tw * physics.gl_target_mult[pos_code])

        qb_slots = np.flatnonzero(pos_code == 0)
        if qb_slots.size == 0:
            continue

        cp = coach_profiles.get(coach_map.get(team, "__LEAGUE__"), coach_profiles["__LEAGUE__"])
        stq = strength.get(team)

        team_models[team] = TeamModel(
            team=team, gidx=gidx, pos_code=pos_code,
            target_share=tw, rz_target_share=rz_tw, gl_target_share=gl_tw,
            rush_share=rw, gl_share=gw,
            adot=adot, yac_mean=yac, catch_oe=catch_oe, ypc_oe=ypc_oe,
            qb_slots=qb_slots, qb_cpoe=qb_cpoe, qb_adot=qb_adot,
            qb_sack_oe=qb_sack, qb_rush_share=qb_rsh,
            redistribute=_redistribution(pos_code, depth_arr),
            proe=cp.proe,
            pace_mult=float(np.clip(cp.sec_per_play / league_pace, 0.9, 1.1)),
            go_oe=cp.go_rate_oe,
            rz_pass_oe=cp.rz_pass_oe,
            off_pass_epa=stq.off_pass_epa if stq else 0.0,
            off_rush_epa=stq.off_rush_epa if stq else 0.0,
            off_comp_oe=stq.off_comp_oe if stq else 0.0,
            # Team rushing environment: the fitted EPA-based term plus the
            # blocking component measured at the point of contact.
            off_ypc_oe=(stq.off_ypc_oe if stq else 0.0)
                       + float(contact["team_ybc"].get(team, 0.0)),
            off_sack_oe=stq.off_sack_oe if stq else 0.0,
            def_pass_epa=stq.def_pass_epa if stq else 0.0,
            def_rush_epa=stq.def_rush_epa if stq else 0.0,
            def_comp_oe=stq.def_comp_oe if stq else 0.0,
            def_ypc_oe=stq.def_ypc_oe if stq else 0.0,
            def_sack_oe=stq.def_sack_oe if stq else 0.0,
        )

    _center_efficiency(team_models)

    ptab = pd.DataFrame(rows).set_index("gindex")
    rate, dur = _hazard_vectors(ptab, haz)

    sched = data.schedule(season)
    coach_tab = pd.DataFrame([
        {"team": t, "coach": coach_map.get(t, "?"),
         "new": strength[t].coach_is_new if t in strength else False,
         "proe": coach_profiles.get(coach_map.get(t, "__LEAGUE__"), coach_profiles["__LEAGUE__"]).proe,
         "pace": coach_profiles.get(coach_map.get(t, "__LEAGUE__"), coach_profiles["__LEAGUE__"]).sec_per_play,
         "go_oe": coach_profiles.get(coach_map.get(t, "__LEAGUE__"), coach_profiles["__LEAGUE__"]).go_rate_oe,
         "continuity": continuity.get(t, np.nan)}
        for t in all_teams
    ])
    stab = pd.DataFrame([vars(s) for s in strength.values()])

    log(f"built {len(team_models)} teams, {len(ptab)} players")
    return Bundle(
        physics=physics, teams=team_models, player_table=ptab,
        injury_rate=rate, injury_dur=dur, schedule=sched, role_sigma=role_sigma, team_shock=team_shock, td_sigma=td_sigma,
        coach_table=coach_tab, strength_table=stab, season=season,
    )


def _center_efficiency(team_models: dict) -> None:
    """Re-centre the per-player efficiency adjustments on zero.

    `catch_oe` is a player's catch rate minus the league completion curve
    evaluated at his *average* depth of target. That comparison is biased
    upward, and not by a little: the completion curve is convex, so a receiver
    throwing to a spread of depths centred on 11 yards completes more often
    than the curve's value *at* 11 yards. Every average receiver therefore
    scores positive, and the bias compounds into league-wide completion
    percentage running several points hot.

    Evaluating the curve's expectation over each player's own air-yards
    distribution would be the exact fix; centring achieves the same thing for
    the purpose these terms serve. The absolute level of completion is already
    set by the curve itself -- these terms only need to say who is better than
    average, and a quantity that is meant to be relative should have mean zero.
    The centring is target-weighted, because it is the target-weighted average
    that determines the league's completion percentage.
    """
    oes, weights, cpoes = [], [], []
    for tm in team_models.values():
        real = tm.target_share > 0.02
        oes.append(tm.catch_oe[real])
        weights.append(tm.target_share[real])
        starters = tm.qb_slots[:1]
        cpoes.append(tm.qb_cpoe[starters])
    if not oes:
        return
    oe_all = np.concatenate(oes)
    w_all = np.concatenate(weights)
    cp_all = np.concatenate(cpoes)
    oe_mean = float(np.average(oe_all, weights=w_all)) if w_all.sum() > 0 else 0.0
    cp_mean = float(cp_all.mean()) if cp_all.size else 0.0

    for tm in team_models.values():
        tm.catch_oe -= oe_mean
        tm.qb_cpoe -= cp_mean


def _hazard_vectors(ptab: pd.DataFrame, haz: dict) -> tuple[np.ndarray, np.ndarray]:
    P = len(ptab)
    rate = np.zeros(P)
    dur = np.zeros(P)
    for gi, r in ptab.iterrows():
        base = haz["hazard"].get(r.pos, 0.05)
        rate[gi] = np.clip(
            base * pl.age_injury_multiplier(r.age, r.pos) * float(r.get("avail_mult", 1.0)),
            0.004, 0.20,
        )
        dur[gi] = haz["duration"].get(r.pos, 2.6)
    return rate, dur


def _norm(w: np.ndarray) -> np.ndarray:
    w = np.clip(np.nan_to_num(w, nan=0.0), 0.0, None)
    s = w.sum()
    return w / s if s > 0 else np.full_like(w, 1.0 / len(w))


def _confidence_norm(w: np.ndarray, conf: np.ndarray, budget: float) -> np.ndarray:
    """Normalise usage weights, charging the error to the least certain estimates.

    Every weight is an estimate of a player's share of his team's work, but the
    estimates are made independently and do not have to cohere: a backfield
    holding two former lead backs will claim more carries than the team has to
    give. Something must absorb the difference.

    Plain proportional normalisation charges it to everyone equally, which is
    the wrong answer -- it makes a player with four consistent seasons of
    evidence pay the same penalty as a backup whose number came from a job he
    held somewhere else three years ago. Philadelphia is the clean example: the
    Eagles' backs over-subscribed their carry budget by a third, and Saquon
    Barkley, whose share of the backfield has been 77 / 75 / 76 / 77 percent
    across four seasons, was compressed to 53 to make room for it.

    So the excess is removed in proportion to w * (1 - conf)^2, which
    concentrates it on the estimates least able to defend themselves, and only
    then is the vector scaled to sum to one.
    """
    w = np.clip(np.nan_to_num(w, nan=0.0), 0.0, None)
    total = w.sum()
    if total <= 0:
        return np.full_like(w, 1.0 / len(w))

    excess = total - budget
    if excess > 0:
        slack = w * (1.0 - np.clip(conf, 0.0, 1.0)) ** 2
        if slack.sum() > 1e-9:
            w = np.clip(w - excess * slack / slack.sum(), 0.0, None)
    return _norm(w)


def _pick(value, default, conf) -> float:
    if value is None or not np.isfinite(value):
        return float(default)
    return float(conf * value + (1 - conf) * default)


def _age(birth, season: int = TARGET_SEASON) -> float:
    if birth is None or (isinstance(birth, float) and not np.isfinite(birth)):
        return np.nan
    try:
        b = pd.Timestamp(birth)
    except Exception:
        return np.nan
    if pd.isna(b):
        return np.nan
    return float((pd.Timestamp(f"{season}-09-01") - b).days / 365.25)


def _qb_rush_rates(season: int, lookback: int = 4,
                   halflife: float = priors.HALFLIFE_USAGE) -> dict[str, float]:
    """Share of a team's designed runs and scrambles that the quarterback keeps.

    Weighted across four past seasons. Quarterback rushing is one of the more
    stable traits a passer has, and it is worth a great deal in fantasy scoring,
    so it is better estimated from a multi-season weighted sum than from
    whatever last year's game scripts happened to produce.
    """
    pbp = data.play_by_play(
        range(season - lookback, season),
        columns=["season", "season_type", "posteam", "rush_attempt", "qb_kneel",
                 "rusher_player_id", "qb_scramble"],
    )
    p = pbp[(pbp.season_type == "REG") & (pbp.rush_attempt == 1) & (pbp.qb_kneel != 1)].copy()
    p["w"] = priors.recency_weights(p.season.to_numpy(), season, halflife)
    team_tot = p.groupby("posteam").w.sum()
    by_qb = p.groupby("rusher_player_id").w.sum()
    last_team = p.groupby("rusher_player_id").posteam.last()
    out = {}
    for pid, wsum in by_qb.items():
        t = last_team.get(pid)
        if t and team_tot.get(t, 0) > 0:
            out[pid] = float(np.clip(wsum / team_tot[t], 0.0, 0.45))
    return out
