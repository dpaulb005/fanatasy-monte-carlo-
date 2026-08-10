"""Optimal-lineup solver and coaching-efficiency metrics.

Greedy fill of dedicated slots then FLEX — exact for standard ESPN single-FLEX
roster structures (docs/METRICS_CATALOG.md). Operates on the roster frames.
"""

from __future__ import annotations

from league.analytics.frames import RosterPlayerFrame

DEFAULT_STARTER_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DST", "K"]
FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def optimal_points(
    roster: list[RosterPlayerFrame],
    starter_slots: list[str] | None = None,
) -> float:
    """Best legal starting-lineup total for one team-week."""
    slots = starter_slots or DEFAULT_STARTER_SLOTS
    # Sort players by points desc; greedily assign to slots.
    order = sorted(range(len(roster)), key=lambda i: -roster[i].points)
    used: set[int] = set()
    total = 0.0
    for slot in slots:
        eligible = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        for i in order:
            if i in used:
                continue
            if roster[i].position in eligible:
                used.add(i)
                total += roster[i].points
                break
    return round(total, 2)


def actual_started_points(roster: list[RosterPlayerFrame]) -> float:
    return round(sum(p.points for p in roster if p.started), 2)


def week_efficiency(
    roster: list[RosterPlayerFrame],
    starter_slots: list[str] | None = None,
) -> tuple[float, float, float]:
    """Return (actual, optimal, bench_points_lost) for one team-week."""
    optimal = optimal_points(roster, starter_slots)
    actual = actual_started_points(roster)
    return actual, optimal, round(max(0.0, optimal - actual), 2)
