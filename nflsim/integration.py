"""Versioned export contract for downstream fantasy applications.

The raw simulation archive is intentionally not an application API: it is large,
pickle-adjacent, and coupled to NumPy's in-memory layout.  This module turns one
completed run into a compact JSON snapshot containing only reproducible analysis
products and enough provenance for a consumer to describe them honestly.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import advanced, analysis
from .config import League, Scoring

SCHEMA = "nflsim.application-snapshot"
SCHEMA_VERSION = 1


def _clean(value):
    """Convert pandas/NumPy values to strict, portable JSON values."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return _clean(frame.replace({np.nan: None}).to_dict(orient="records"))


def application_snapshot(bundle, result: dict, scoring: Scoring,
                         league: League, pair_horizon: int = 180) -> dict:
    """Build the stable payload consumed by ``fantasy_analysis_app``.

    Pair metrics are restricted to the draftable horizon to keep the artifact
    compact. They still come from the same simulated seasons, so correlations
    and tail lift retain their joint-distribution meaning.
    """
    summary = analysis.add_value(
        analysis.summarise(result, bundle, scoring), result, bundle, scoring, league,
    )
    equity = advanced.championship_equity(result, bundle, scoring, league)
    contingent = advanced.contingent_value(result, bundle, scoring)
    anatomy = advanced.ceiling_anatomy(result, bundle, scoring)
    weekly = advanced.startability(result, bundle, scoring) if "weekly_fp" in result else pd.DataFrame()

    def indexed(frame: pd.DataFrame) -> dict[str, dict]:
        if frame.empty:
            return {}
        return {str(row["player"]): row for row in _records(frame)}

    extras = [indexed(equity), indexed(contingent), indexed(anatomy), indexed(weekly)]
    players = []
    for row in _records(summary.rename(columns={"player": "player"})):
        merged = dict(row)
        for lookup in extras:
            merged.update({k: v for k, v in lookup.get(row["player"], {}).items()
                           if k not in {"player", "pos", "team", "points"}})
        players.append(merged)

    horizon = {p["player"] for p in players if p.get("overall_rank", 10**9) <= pair_horizon}
    pairs = advanced.coboom(result, bundle, scoring, min_points=0.0)
    if not pairs.empty:
        pairs = pairs[pairs["a"].isin(horizon) & pairs["b"].isin(horizon)]

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "model": {
            "season": int(bundle.season),
            "simulations": int(result["n_sims"]),
            "scoring": scoring.to_dict(),
            "league": asdict(league),
            "weekly_capture": "weekly_fp" in result,
            "pair_horizon": pair_horizon,
        },
        "players": players,
        "pairs": _records(pairs),
    }


def write_application_snapshot(bundle, result: dict, scoring: Scoring,
                               league: League, path: Path,
                               pair_horizon: int = 180) -> Path:
    payload = application_snapshot(bundle, result, scoring, league, pair_horizon)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, allow_nan=False, separators=(",", ":")))
    temporary.replace(path)
    return path
