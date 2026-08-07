"""Invariant checks for the simulation engine.

These target the failure modes that are silent -- the ones that still produce a
full, plausible-looking projection table while being wrong underneath. Each of
these guards a bug that actually occurred during development.

Run with:  python -m pytest tests/ -q      (or: python tests/test_engine.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nflsim.build import _redistribution, _norm
from nflsim.engine import _add, _effective_shares, _sample_player


def test_shares_renormalise_to_one():
    """Usage shares must remain a probability distribution after injuries."""
    base = np.array([0.4, 0.3, 0.2, 0.1])
    pos = np.array([1, 1, 2, 2])
    depth = np.array([1, 2, 1, 2])
    R = _redistribution(pos, depth)

    avail = np.ones((5, 4))
    avail[1, 0] = 0.0            # the primary is out
    avail[2, [0, 1]] = 0.0       # both backs are out
    avail[3, :] = 0.0            # nobody is available

    eff = _effective_shares(base, avail, R)
    assert np.allclose(eff.sum(axis=1), 1.0), "shares must sum to one in every replication"
    assert (eff >= 0).all(), "shares must be non-negative"
    # An unavailable player must receive no usage at all.
    assert eff[1, 0] == 0.0
    assert eff[2, 0] == 0.0 and eff[2, 1] == 0.0


def test_vacated_usage_favours_the_direct_backup():
    """A starter's absence should mostly promote his backup, not the whole offence."""
    base = np.array([0.5, 0.25, 0.15, 0.10])
    pos = np.array([1, 1, 2, 2])
    depth = np.array([1, 2, 1, 2])
    R = _redistribution(pos, depth)

    healthy = _effective_shares(base, np.ones((1, 4)), R)[0]
    hurt = np.ones((1, 4)); hurt[0, 0] = 0.0
    after = _effective_shares(base, hurt, R)[0]

    gain_backup = after[1] - healthy[1]
    gain_other = after[2] - healthy[2]
    assert gain_backup > gain_other > 0, "the backup must absorb more than a different position"


def test_redistribution_columns_are_distributions():
    pos = np.array([0, 1, 1, 2, 2, 2])
    depth = np.array([1, 1, 2, 1, 2, 3])
    R = _redistribution(pos, depth)
    assert np.allclose(R.sum(axis=0), 1.0), "each vacated share must be fully reallocated"
    assert np.allclose(np.diag(R), 0.0), "a player cannot absorb his own vacated share"


def test_scatter_add_accumulates_correctly():
    """The flat fancy-index add is only valid because rows are unique per play."""
    S, n = 6, 4
    plane = np.zeros((S, n))
    rows = np.array([0, 2, 5])
    slots = np.array([1, 3, 0])
    _add(plane, rows, slots, np.array([2.5, 1.0, 4.0]), n)

    expect = np.zeros((S, n))
    expect[0, 1], expect[2, 3], expect[5, 0] = 2.5, 1.0, 4.0
    assert np.array_equal(plane, expect)

    # Scalar values must broadcast the same way.
    _add(plane, rows, slots, 1.0, n)
    expect[0, 1] += 1; expect[2, 3] += 1; expect[5, 0] += 1
    assert np.array_equal(plane, expect)


def test_sampler_respects_the_weights():
    """A zero-weight player must never be selected; weights must be honoured."""
    rng = np.random.default_rng(0)
    shares = np.array([[0.7, 0.3, 0.0]])
    cum = np.cumsum(np.repeat(shares, 4000, axis=0), axis=1)
    draws = _sample_player(cum, np.arange(4000), rng)
    counts = np.bincount(draws, minlength=3) / 4000
    assert counts[2] == 0.0, "a zero-weight player must never be drawn"
    assert abs(counts[0] - 0.7) < 0.03 and abs(counts[1] - 0.3) < 0.03


def test_norm_handles_degenerate_input():
    assert np.allclose(_norm(np.zeros(4)), 0.25), "an all-zero weight vector must not divide by zero"
    assert np.allclose(_norm(np.array([np.nan, 1.0, 1.0])), [0.0, 0.5, 0.5])


def test_nan_wind_cannot_poison_completion_probability():
    """A blank wind field must resolve to zero, not nan.

    Dome games and games with unrecorded conditions carry a blank wind. When
    that reached the engine as nan it propagated into every completion
    probability, making every pass in the game incomplete -- catch rates came
    out near 39% instead of 65% and nothing raised.
    """
    from nflsim.season import coerce_wind

    for blank in (np.nan, None, "", "nan", float("nan")):
        assert coerce_wind(blank) == 0.0, f"{blank!r} must resolve to 0.0"
    assert coerce_wind(12.0) == 12.0
    assert coerce_wind("8") == 8.0
    assert np.isfinite(coerce_wind(np.nan))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
