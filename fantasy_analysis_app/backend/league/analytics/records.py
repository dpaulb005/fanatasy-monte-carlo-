"""Record helpers: streaks and simple aggregations over game sequences."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StreakResult:
    longest_win_streak: int
    longest_lose_streak: int


def longest_streaks(outcomes: list[str]) -> StreakResult:
    """Longest win/lose streaks from a chronological list of 'W'/'L'/'T'."""
    best_w = best_l = cur_w = cur_l = 0
    for o in outcomes:
        if o == "W":
            cur_w += 1
            cur_l = 0
        elif o == "L":
            cur_l += 1
            cur_w = 0
        else:
            cur_w = cur_l = 0
        best_w = max(best_w, cur_w)
        best_l = max(best_l, cur_l)
    return StreakResult(best_w, best_l)


def stddev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return round(var**0.5, 3)
