"""Conformal calibration of the projected intervals.

The backtest showed the stated p10-p90 band containing the actual outcome about
68% of the time against a nominal 80%. Two rounds of added variance -- role
volatility and team efficiency shocks, both fit from data -- fixed the point
projections but barely moved the coverage, and an independently built
play-by-play engine reports the same shortfall, which suggests the
under-dispersion is a property of the method rather than a mis-fit parameter.

The wrong fix is to keep inflating a variance parameter until the number reads
80%, because the only thing available to tune against is a single backtest
season, and fitting a distribution parameter to one season is exactly the
overfitting this project refuses elsewhere.

Conformalized quantile regression is the right fix. It asks a different
question: given the intervals the model already produces, how much would they
have to be widened to have covered the truth at the stated rate on data the
model never saw? That widening is then applied to future intervals. It needs no
distributional assumption, it tunes nothing inside the simulation, and under
exchangeability it carries a finite-sample coverage guarantee.

The scaled variant is used here (Romano, Patterson & Candes, 2019). The
conformity score is normalised by each player's own predicted width, so the
correction is multiplicative rather than a flat number of points -- a projection
of 320 and a projection of 40 should not be widened by the same twelve points.

Calibration and evaluation must be different seasons. Fitting the widening on
2025 and then reporting 2025 coverage would be circular and would report a
guarantee that does not exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

BANDS = {"80": ("p10", "p90"), "50": ("p25", "p75")}


@dataclass
class Calibration:
    """Per-position, per-band multiplicative widening factors."""

    factors: dict          # band -> position -> Q
    fit_season: int
    n: dict                # band -> position -> calibration sample size

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @staticmethod
    def load(path: Path) -> "Calibration":
        d = json.loads(Path(path).read_text())
        return Calibration(**d)

    def widen(self, lo: np.ndarray, hi: np.ndarray, pos: np.ndarray,
              band: str = "80") -> tuple[np.ndarray, np.ndarray]:
        """Apply the fitted widening, keeping the interval non-negative."""
        f = self.factors.get(band, {})
        q = np.array([f.get(p, f.get("_all", 0.0)) for p in pos], dtype=float)
        w = np.maximum(hi - lo, 1e-9)
        return np.maximum(lo - q * w, 0.0), hi + q * w


def _conformity(lo, hi, y):
    """How far outside its interval each outcome fell, in units of interval width.

    Negative when the outcome landed inside, which is what lets the quantile of
    these scores *narrow* an interval that turned out to be too wide.
    """
    w = np.maximum(hi - lo, 1e-9)
    return np.maximum(lo - y, y - hi) / w


def fit(df: pd.DataFrame, season: int, min_n: int = 25,
        cohort: int | None = 200) -> Calibration:
    """Fit widening factors from a scored backtest frame.

    `df` must carry the projected quantiles and an `actual` column, i.e. the
    output of `backtest.run_backtest`.
    """
    d = df if cohort is None else df.nlargest(cohort, "points")
    factors, counts = {}, {}

    for band, (locol, hicol) in BANDS.items():
        target = int(band) / 100.0
        fb, nb = {}, {}
        scores_all = _conformity(d[locol].to_numpy(), d[hicol].to_numpy(),
                                 d["actual"].to_numpy())
        # Conformal quantile level, with the finite-sample correction.
        def q_of(s):
            n = len(s)
            lvl = min(np.ceil((n + 1) * target) / n, 1.0)
            return float(np.quantile(s, lvl, method="higher"))

        fb["_all"] = max(q_of(scores_all), 0.0)
        nb["_all"] = int(len(scores_all))

        for pos, sub in d.groupby("pos"):
            if len(sub) < min_n:
                continue          # fall back to the pooled factor
            s = _conformity(sub[locol].to_numpy(), sub[hicol].to_numpy(),
                            sub["actual"].to_numpy())
            fb[pos] = max(q_of(s), 0.0)
            nb[pos] = int(len(sub))

        factors[band] = fb
        counts[band] = nb

    return Calibration(factors=factors, fit_season=season, n=counts)


def coverage(df: pd.DataFrame, cal: Calibration | None = None,
             cohort: int | None = 200) -> pd.DataFrame:
    """Empirical coverage of each band, before and optionally after widening."""
    d = df if cohort is None else df.nlargest(cohort, "points")
    rows = []
    for band, (locol, hicol) in BANDS.items():
        lo, hi = d[locol].to_numpy(), d[hicol].to_numpy()
        y = d["actual"].to_numpy()
        raw = float(((y >= lo) & (y <= hi)).mean())
        width_raw = float(np.mean(hi - lo))
        row = {"band": f"{band}%", "nominal": int(band) / 100.0,
               "raw": raw, "raw_width": width_raw}
        if cal is not None:
            lo2, hi2 = cal.widen(lo, hi, d["pos"].to_numpy(), band)
            row["calibrated"] = float(((y >= lo2) & (y <= hi2)).mean())
            row["cal_width"] = float(np.mean(hi2 - lo2))
        rows.append(row)
    return pd.DataFrame(rows)


def coverage_by_position(df: pd.DataFrame, cal: Calibration | None,
                         band: str = "80", cohort: int | None = 200) -> pd.DataFrame:
    d = df if cohort is None else df.nlargest(cohort, "points")
    locol, hicol = BANDS[band]
    rows = []
    for pos, sub in d.groupby("pos"):
        lo, hi, y = sub[locol].to_numpy(), sub[hicol].to_numpy(), sub["actual"].to_numpy()
        r = {"pos": pos, "n": len(sub), "raw": float(((y >= lo) & (y <= hi)).mean())}
        if cal is not None:
            lo2, hi2 = cal.widen(lo, hi, sub["pos"].to_numpy(), band)
            r["calibrated"] = float(((y >= lo2) & (y <= hi2)).mean())
            r["factor"] = cal.factors[band].get(pos, cal.factors[band]["_all"])
        rows.append(r)
    return pd.DataFrame(rows).sort_values("pos")
