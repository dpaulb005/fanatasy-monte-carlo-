"""Paired Monte Carlo experiments that attribute player outcomes to context.

The simulator already models injuries, uncertain roles, teammate competition,
coaching tendencies and team quality.  This module turns those ingredients
into falsifiable comparisons: replay controlled scenarios from the same seeded
random streams with one source removed.  It is deliberately an attribution
tool, not a second projection model.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import advanced
from .analysis import fantasy_points
from .config import Scoring
from .season import run_season


@dataclass(frozen=True)
class Scenario:
    name: str
    injuries: bool = True
    role_variance: bool = True
    team_shocks: bool = True
    neutral_coach: bool = False
    neutral_strength: bool = False


SCENARIOS = (
    Scenario("baseline"),
    Scenario("healthy", injuries=False),
    Scenario("fixed_roles", role_variance=False),
    Scenario("fixed_team_efficiency", team_shocks=False),
    Scenario("neutral_scheme", neutral_coach=True),
    Scenario("neutral_team_context", neutral_coach=True, neutral_strength=True),
)


def scenario_bundle(bundle, scenario: Scenario):
    """Copy and neutralise only the structural terms named by a scenario."""
    if not scenario.neutral_coach and not scenario.neutral_strength:
        return bundle
    out = copy.deepcopy(bundle)
    for team in out.teams.values():
        if scenario.neutral_coach:
            team.proe = 0.0
            team.pace_mult = 1.0
            team.go_oe = 0.0
            team.rz_pass_oe = 0.0
        if scenario.neutral_strength:
            for field in (
                "off_pass_epa", "off_rush_epa", "off_comp_oe", "off_ypc_oe",
                "off_sack_oe", "def_pass_epa", "def_rush_epa", "def_comp_oe",
                "def_ypc_oe", "def_sack_oe",
            ):
                setattr(team, field, 0.0)
    return out


def _summary(result: dict, scoring: Scoring) -> dict[str, np.ndarray]:
    fp = fantasy_points(result["totals"], scoring)
    return {
        "mean": fp.mean(axis=0),
        "sd": fp.std(axis=0),
        "p10": np.percentile(fp, 10, axis=0),
        "p90": np.percentile(fp, 90, axis=0),
        "games": result["games_played"].mean(axis=0),
    }


def context_features(bundle) -> pd.DataFrame:
    """Observable role, teammate-pressure and scheme fields for every player."""
    coach = bundle.coach_table.set_index("team")
    rows = []
    for team_name, team in bundle.teams.items():
        target = np.asarray(team.target_share, dtype=float)
        rush = np.asarray(team.rush_share, dtype=float)
        target_hhi = float(np.square(target / max(target.sum(), 1e-9)).sum())
        rush_hhi = float(np.square(rush / max(rush.sum(), 1e-9)).sum())
        c = coach.loc[team_name] if team_name in coach.index else None
        for local, gi in enumerate(team.gidx):
            same_pos = np.flatnonzero(team.pos_code == team.pos_code[local])
            rivals = same_pos[same_pos != local]
            if team.pos_code[local] == 1:  # RB role is primarily carries
                role_share = rush[local]
                rival = float(rush[rivals].max()) if rivals.size else 0.0
            else:
                role_share = target[local]
                rival = float(target[rivals].max()) if rivals.size else 0.0
            rows.append({
                "gindex": int(gi),
                "target_share": float(target[local]),
                "rush_share": float(rush[local]),
                "goal_line_share": float(team.gl_share[local]),
                "role_margin": float(role_share - rival),
                "target_hhi": target_hhi,
                "rush_hhi": rush_hhi,
                "coach_proe": float(team.proe),
                "pace_multiplier": float(team.pace_mult),
                "new_coach": bool(c["new"]) if c is not None else False,
                "roster_continuity": float(c["continuity"]) if c is not None else np.nan,
            })
    return pd.DataFrame(rows).set_index("gindex")


def run_factor_experiment(bundle, scoring: Scoring, n_sims: int = 2000,
                          seed: int = 20260807, verbose: bool = True) -> tuple[pd.DataFrame, dict]:
    """Run controlled factor-off scenarios and return one attribution row per player."""
    results = {}
    summaries = {}
    for scenario in SCENARIOS:
        if verbose:
            print(f"\nscenario: {scenario.name}", flush=True)
        b = scenario_bundle(bundle, scenario)
        result = run_season(
            b, n_sims=n_sims, seed=seed, verbose=verbose, weekly=False,
            use_injuries=scenario.injuries,
            use_role_variance=scenario.role_variance,
            use_team_shocks=scenario.team_shocks,
            scoring=scoring,
        )
        results[scenario.name] = result
        summaries[scenario.name] = _summary(result, scoring)

    base = summaries["baseline"]
    pt = bundle.player_table.copy()
    df = pd.DataFrame({
        "player": pt.name, "pos": pt.pos, "team": pt.team,
        "points": base["mean"], "p10": base["p10"], "p90": base["p90"],
        "sd": base["sd"], "games": base["games"],
        # These are league-system counterfactuals: teammates and opponents are
        # changed too. A backup can therefore have a negative healthy delta.
        "health_environment_delta": summaries["healthy"]["mean"] - base["mean"],
        "health_floor_delta": summaries["healthy"]["p10"] - base["p10"],
        # Positive tail lift means league-wide role uncertainty creates upside.
        "role_system_ceiling_lift": base["p90"] - summaries["fixed_roles"]["p90"],
        "role_sd_lift": base["sd"] - summaries["fixed_roles"]["sd"],
        "team_uncertainty_lift": base["p90"] - summaries["fixed_team_efficiency"]["p90"],
        # Positive values mean the fitted environment helps versus neutral.
        "league_scheme_delta": base["mean"] - summaries["neutral_scheme"]["mean"],
        "neutral_context_delta": base["mean"] - summaries["neutral_team_context"]["mean"],
    }, index=pt.index)
    df = df.join(context_features(bundle))

    contingent = advanced.contingent_value(results["baseline"], bundle, scoring)
    if len(contingent):
        contingent = (contingent.sort_values("contingent_gain", ascending=False)
                      .drop_duplicates(["player", "pos", "team"])
                      .set_index(["player", "pos", "team"]))
        keys = pd.MultiIndex.from_frame(df[["player", "pos", "team"]])
        df["contingent_gain"] = contingent["contingent_gain"].reindex(keys).to_numpy()
        df["behind"] = contingent["behind"].reindex(keys).to_numpy()

    anatomy = advanced.ceiling_anatomy(results["baseline"], bundle, scoring)
    if len(anatomy):
        anatomy = (anatomy.drop_duplicates(["player", "pos", "team"])
                   .set_index(["player", "pos", "team"]))
        keys = pd.MultiIndex.from_frame(df[["player", "pos", "team"]])
        for col in ("volume_ratio", "td_dependence", "health_ratio"):
            df[col] = anatomy[col].reindex(keys).to_numpy()

    df = df.sort_values("points", ascending=False).reset_index(names="gindex")
    meta = {"sims": n_sims, "seed": seed, "scoring": scoring.name,
            "exploratory": n_sims < 5000,
            "scenarios": [s.name for s in SCENARIOS]}
    return df, meta


def generate_html(df: pd.DataFrame, meta: dict, out_path: Path) -> Path:
    """Write a compact, self-contained factor-attribution explorer."""
    cols = [
        "player", "pos", "team", "points", "health_environment_delta",
        "role_system_ceiling_lift", "team_uncertainty_lift", "league_scheme_delta",
        "neutral_context_delta",
        "target_share", "rush_share", "goal_line_share", "role_margin",
        "contingent_gain", "behind", "volume_ratio", "td_dependence",
    ]
    data = df[[c for c in cols if c in df]].replace({np.nan: None}).to_dict("records")
    payload = json.dumps({"meta": meta, "players": data}, separators=(",", ":"))
    html = _FACTOR_TEMPLATE.replace("__DATA__", payload)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


_FACTOR_TEMPLATE = r'''<!doctype html><meta charset="utf-8">
<title>NFLSim factor attribution</title>
<style>
:root{color-scheme:dark;--bg:#101317;--card:#181d23;--ink:#eef1f4;--muted:#929ba5;
--line:#2a3139;--up:#50c49b;--down:#e27b83;--accent:#e5a93d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
main{max-width:1480px;margin:auto;padding:42px 24px 90px}h1{font-size:27px;margin:0 0 6px}p{color:var(--muted);max-width:92ch}
.facts{display:flex;gap:28px;margin:22px 0}.facts b{font-size:20px}.facts span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);padding:12px 14px;border-radius:8px}
.controls{display:flex;gap:9px;align-items:center;position:sticky;top:0;background:var(--bg);padding:14px 0;z-index:2}
input,select{background:var(--card);border:1px solid var(--line);border-radius:7px;color:var(--ink);padding:8px 10px;font:inherit}
input{min-width:260px}.count{margin-left:auto;color:var(--muted)}.scroll{overflow:auto;max-height:70vh}
table{border-collapse:collapse;width:100%;min-width:1330px}th{position:sticky;top:0;background:var(--bg);z-index:1;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}
th,td{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}
td:first-child{font-weight:620}.pos{font-size:11px;color:var(--accent)}.up{color:var(--up)}.down{color:var(--down)}
.tip{border-bottom:1px dotted var(--muted);cursor:help}
</style><main><h1>What moves a player's projection?</h1>
<p>Controlled Monte Carlo factor attribution. Every scenario starts from the same seeded random streams with one source removed. Because changed plays alter later game states, treat small differences as sensitivity estimates, not exact causal effects.</p>
<div class="facts" id="facts"></div><p class="note"><b>Interpretation:</b> these are league-wide system sensitivities: teammates and opponents change too. A negative healthy-environment delta for a backup can be real because starter injuries create his opportunity. Positive role/team tail values show ceiling created by uncertainty; positive scheme/context values mean the fitted league environment helps versus neutral. They are not isolated player effects or causal estimates. Runs below 5,000 simulations are exploratory.</p>
<div class="controls"><input id="q" type="search" placeholder="Search player or team…"><select id="pos"><option value="">All positions</option><option>QB</option><option>RB</option><option>WR</option><option>TE</option></select><select id="sort"><option value="points">Projected points</option><option value="health_environment_delta">Healthy environment</option><option value="role_system_ceiling_lift">Role-system ceiling</option><option value="league_scheme_delta">League scheme</option><option value="neutral_context_delta">Neutral context</option><option value="contingent_gain">Contingent upside</option></select><span class="count" id="count"></span></div>
<div class="scroll"><table><thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Pts</th><th><span class="tip" title="All-healthy league mean minus baseline mean">Healthy env</span></th><th><span class="tip" title="Baseline p90 minus league-wide fixed-role p90">Role-system tail</span></th><th>Team σ tail</th><th>League scheme</th><th>Neutral context</th><th>Tgt share</th><th>Rush share</th><th>GL share</th><th>Role margin</th><th>Backup gain</th><th>Behind</th><th>Ceiling volume</th><th>TD dependence</th></tr></thead><tbody id="body"></tbody></table></div>
<script>const D=__DATA__,P=D.players;const f=(v,n=1)=>v==null||!isFinite(v)?"–":Number(v).toFixed(n),pc=v=>v==null?"–":f(v*100,1)+"%",e=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function cell(v,kind="num"){const c=v>0.5?"up":v<-.5?"down":"";return `<td class="${c}">${f(v)}</td>`}function render(){const q=document.querySelector('#q').value.toLowerCase(),pos=document.querySelector('#pos').value,key=document.querySelector('#sort').value;const rows=P.filter(p=>(!pos||p.pos===pos)&&(!q||p.player.toLowerCase().includes(q)||p.team.toLowerCase().includes(q))).sort((a,b)=>(b[key]??-1e9)-(a[key]??-1e9));document.querySelector('#count').textContent=`${rows.length} players`;document.querySelector('#body').innerHTML=rows.map(p=>`<tr><td>${e(p.player)}</td><td class="pos">${p.pos}</td><td>${p.team}</td><td>${f(p.points,0)}</td>${cell(p.health_environment_delta)}${cell(p.role_system_ceiling_lift)}${cell(p.team_uncertainty_lift)}${cell(p.league_scheme_delta)}${cell(p.neutral_context_delta)}<td>${pc(p.target_share)}</td><td>${pc(p.rush_share)}</td><td>${pc(p.goal_line_share)}</td>${cell(p.role_margin)}${cell(p.contingent_gain)}<td>${e(p.behind||'')}</td><td>${f(p.volume_ratio,2)}</td><td>${f(p.td_dependence,2)}</td></tr>`).join('')}
document.querySelector('#facts').innerHTML=[[D.meta.sims.toLocaleString(),'simulated seasons'],[D.meta.scoring,'scoring'],[D.meta.scenarios.length,'controlled scenarios'],[P.length,'players']].map(x=>`<div><b>${x[0]}</b><span>${x[1]}</span></div>`).join('');['q','pos','sort'].forEach(id=>document.querySelector('#'+id).addEventListener('input',render));render();</script></main>'''
