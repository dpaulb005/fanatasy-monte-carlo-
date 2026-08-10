"""Draft priors: what this league's history says about the next draft.

Two priors, both computed from synced data only (no external projections):

1. **ADP calibration** — for every historical pick that matched a public ADP,
   the residual ``overall_pick − adp`` measures how this league deviates from
   market consensus. Its mean (bias) and spread (sigma) per position calibrate
   availability confidence intervals in the suggester: "WRs go ~3 picks early
   here, ±9".
2. **Value bands** — quantiles of points-over-replacement by position × round
   across all synced seasons: what a round-3 RB has actually returned in this
   league, as a distribution rather than a promise.

Stored as the ``draft_priors`` SeasonTrend blob; consumed by the suggester
endpoint at request time. See ADR-012: the suggester ranks by market order and
league-calibrated availability — it is not a player-skill projection.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from league.analytics.draft_patterns import _phase  # round -> early/mid/late
from league.analytics.drafts import DraftValueRow
from league.analytics.frames import LeagueFrames, normalize_position

# Below this many residuals a position falls back to the overall calibration.
MIN_CALIBRATION_N = 8
# ADP noise never really collapses; floor sigma so CIs stay honest even when a
# small sample happens to agree with the market.
MIN_SIGMA = 3.0

_QUANTILE_KEYS = ("p10", "p25", "p50", "p75", "p90")


def _quantiles(values: list[float]) -> dict[str, float]:
    if len(values) == 1:
        return {k: round(values[0], 1) for k in _QUANTILE_KEYS}
    qs = statistics.quantiles(values, n=20, method="inclusive")  # 5% steps
    return {
        "p10": round(qs[1], 1),
        "p25": round(qs[4], 1),
        "p50": round(qs[9], 1),
        "p75": round(qs[14], 1),
        "p90": round(qs[17], 1),
    }


def _calibration(residuals: list[float]) -> dict:
    bias = statistics.mean(residuals)
    sigma = statistics.stdev(residuals) if len(residuals) > 1 else MIN_SIGMA
    return {
        "bias": round(bias, 2),
        "sigma": round(max(sigma, MIN_SIGMA), 2),
        "n": len(residuals),
    }


# Projection scale columns, in preference order when detection ties.
_SCALE_COLUMNS = ("pts_ppr", "pts_half_ppr", "pts_std")
# A projection source beats "synthetic" when both cover a season.
_SOURCE_PRIORITY = {"synthetic": 0}


def _projection_error(frames: LeagueFrames, projections: list) -> dict | None:
    """Empirical projection-error distributions vs realized league points.

    residual = actual league season points − projected points, over players
    with both. The projection scale (PPR/half/standard) is auto-detected as
    the column minimizing the median absolute residual — the league's scoring
    settings blob doesn't record the format, but its own data does.
    """
    # Prefer the highest-priority source per (season, espn id).
    chosen: dict[tuple[int, int], Any] = {}
    for proj in projections:
        if proj.week != 0 or proj.espn_player_id is None:
            continue
        key = (proj.season, proj.espn_player_id)
        current = chosen.get(key)
        if current is None or _SOURCE_PRIORITY.get(proj.source, 1) > _SOURCE_PRIORITY.get(
            current.source, 1
        ):
            chosen[key] = proj

    # (actual, projection) pairs per scale column.
    pairs: list[tuple[float, Any]] = []
    for (season, espn_id), proj in chosen.items():
        actual = frames.player_season_points.get(season, {}).get(espn_id)
        if actual is None:
            continue
        pairs.append((actual, proj))
    if len(pairs) < MIN_CALIBRATION_N:
        return None

    def residuals(column: str) -> list[tuple[str, float]]:
        out = []
        for actual, proj in pairs:
            projected = getattr(proj, column)
            if projected is not None:
                out.append((normalize_position(proj.position), actual - projected))
        return out

    best_column, best_median = "", float("inf")
    for column in _SCALE_COLUMNS:
        res = residuals(column)
        if not res:
            continue
        median_abs = statistics.median(abs(r) for _, r in res)
        if median_abs < best_median:
            best_column, best_median = column, median_abs
    if not best_column:
        return None

    res = residuals(best_column)
    by_pos: dict[str, list[float]] = defaultdict(list)
    for pos, r in res:
        by_pos[pos].append(r)

    return {
        "scale": best_column,
        "matched": len(res),
        "overall": {**_quantiles([r for _, r in res]), "n": len(res)},
        "by_position": {
            pos: {**_quantiles(v), "n": len(v)}
            for pos, v in sorted(by_pos.items())
            if len(v) >= MIN_CALIBRATION_N
        },
    }


def compute_draft_priors(
    frames: LeagueFrames,
    draft_values: list[DraftValueRow],
    projections: list | None = None,
) -> dict:
    values_by_pick = {v.draft_pick_id: v for v in draft_values}

    residuals_all: list[float] = []
    residuals_by_pos: dict[str, list[float]] = defaultdict(list)
    por_by_pos_round: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for pick in frames.draft_picks:
        year = pick.season.year
        pid = pick.player.espn_player_id
        pos = frames.player_position_by_year.get(year, {}).get(
            pid, normalize_position(pick.player.position)
        )
        value = values_by_pick.get(pick.id)
        if value is None:
            continue
        if not pick.is_keeper:
            por_by_pos_round[pos][pick.round].append(value.points_over_replacement)
            if value.adp_delta is not None:
                residuals_all.append(value.adp_delta)
                residuals_by_pos[pos].append(value.adp_delta)

    overall = _calibration(residuals_all) if residuals_all else None
    by_position = {
        pos: _calibration(res)
        for pos, res in sorted(residuals_by_pos.items())
        if len(res) >= MIN_CALIBRATION_N
    }

    value_bands = {
        pos: {str(rnd): {**_quantiles(v), "n": len(v)} for rnd, v in sorted(by_round.items()) if v}
        for pos, by_round in sorted(por_by_pos_round.items())
    }

    # Phase-level fallback bands for (position, round) cells with no history.
    phase_bands = {
        pos: {
            phase: {**_quantiles(v), "n": len(v)}
            for phase, v in sorted(
                _group_by_phase(by_round).items(),
            )
            if v
        }
        for pos, by_round in sorted(por_by_pos_round.items())
    }

    years = sorted(frames.team_count_by_year)
    return {
        "seasons": years,
        "rounds": max((p.round for p in frames.draft_picks), default=0),
        "team_count_recent": frames.team_count_by_year.get(years[-1], 0) if years else 0,
        "adp_calibration": {"overall": overall, "by_position": by_position},
        "value_bands": value_bands,
        "phase_bands": phase_bands,
        "projection_error": _projection_error(frames, projections or []),
    }


def _group_by_phase(by_round: dict[int, list[float]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for rnd, values in by_round.items():
        grouped[_phase(rnd)].extend(values)
    return grouped
