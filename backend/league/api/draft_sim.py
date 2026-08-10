"""Tendency-conditioned Monte Carlo draft simulation (MC-1).

Simulates the remainder of a snake draft many times. Each simulated opponent
drafts from the live board with weights built from three signals this league
uniquely has:

1. Market order — softmax over league-calibrated expected pick (ADP + bias),
   with sigma-scaled noise per simulation (the standard ADP-noise mock).
2. Positional tendency — the drafting slot's real position-share profile for
   the current draft phase (early/mid/late) when a slot->manager mapping is
   provided; league-average otherwise.
3. Affinity — a manager reaches for players they're loyal to and avoids
   players who burned them (draft_patterns blob).

Output: per-player survival probability to the user's next pick, and the
distribution of best-available projected points per position at that pick.
Pure Python; ~1k sims x ~200 board players runs in well under a second.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

from league.analytics.draft_patterns import _phase

# Softmax temperature over expected-pick gaps, in units of picks. Lower =
# chalkier drafts. Calibrated so the top candidate is heavily favored but
# top-10 all receive real probability, matching observed ADP scatter.
TEMPERATURE = 6.0
LOYAL_BOOST = 2.0
BURNED_PENALTY = 0.35
DEFAULT_SIMS = 1000


def _phase_of_pick(pick: int, teams: int) -> str:
    return _phase(max(1, math.ceil(pick / teams)))


def simulate_draft(
    board: list[dict],
    pick: int,
    next_pick: int,
    teams: int,
    slot: int,
    slot_profiles: dict[int, dict] | None = None,
    sims: int = DEFAULT_SIMS,
    seed: int = 0,
) -> dict:
    """board rows: {name, position, mu, projected_points, loyal_slots,
    burned_slots}; mu = league-adjusted expected pick. Returns survival
    probabilities at next_pick and best-available distributions."""
    slot_profiles = slot_profiles or {}
    n_between = max(0, next_pick - pick - 1)
    survived: dict[str, int] = defaultdict(int)
    best_available: dict[str, list[float]] = defaultdict(list)

    rng = random.Random(seed)
    for _ in range(sims):
        available = list(range(len(board)))
        # Per-sim jitter re-ranks the board once (a "world"), then each
        # opponent picks with tendency-weighted softmax over that world.
        jitter = [rng.gauss(0.0, 1.0) for _ in board]
        current = pick
        for _step in range(n_between):
            drafting_slot = _slot_for_pick(current, teams)
            profile = slot_profiles.get(drafting_slot, {})
            shares = profile.get("shares", {}).get(_phase_of_pick(current, teams), {})
            weights = []
            for idx in available:
                p = board[idx]
                score = -(p["mu"] + 4.0 * jitter[idx] - current) / TEMPERATURE
                w = math.exp(min(score, 30.0))
                share = shares.get(p["position"])
                if share is not None:
                    w *= 0.25 + 1.5 * share  # tendency tilt, never zero
                if drafting_slot in p.get("loyal_slots", ()):
                    w *= LOYAL_BOOST
                if drafting_slot in p.get("burned_slots", ()):
                    w *= BURNED_PENALTY
                weights.append(w)
            total = sum(weights)
            r = rng.random() * total
            acc = 0.0
            chosen = available[-1]
            for idx, w in zip(available, weights, strict=True):
                acc += w
                if acc >= r:
                    chosen = idx
                    break
            available.remove(chosen)
            current += 1

        # Tally what's left at the user's next pick.
        best_by_pos: dict[str, float] = {}
        for idx in available:
            p = board[idx]
            survived[p["name"]] += 1
            proj = p.get("projected_points")
            if proj is not None and proj > best_by_pos.get(p["position"], -1.0):
                best_by_pos[p["position"]] = proj
        for pos, proj in best_by_pos.items():
            best_available[pos].append(proj)

    def quantile(values: list[float], q: float) -> float:
        s = sorted(values)
        return s[min(len(s) - 1, int(q * len(s)))]

    return {
        "sims": sims,
        "picks_simulated": n_between,
        "survival": {name: round(n / sims, 3) for name, n in survived.items()},
        "best_available_next": {
            pos: {
                "p10": round(quantile(v, 0.10), 1),
                "p50": round(quantile(v, 0.50), 1),
                "p90": round(quantile(v, 0.90), 1),
            }
            for pos, v in sorted(best_available.items())
            if v
        },
    }


def _slot_for_pick(pick: int, teams: int) -> int:
    rnd = math.ceil(pick / teams)
    in_round = pick - (rnd - 1) * teams
    return in_round if rnd % 2 == 1 else teams + 1 - in_round
