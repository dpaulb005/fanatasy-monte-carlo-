"""Luck metrics: all-play record, expected wins, luck delta, PA percentile.

See docs/METRICS_CATALOG.md. All functions are pure and operate on frames.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AllPlayResult:
    all_play_wins: float
    all_play_games: float
    expected_wins: float


def all_play_for_team(
    scores_by_week: dict[int, list[tuple[int, float]]],
    team_season_id: int,
) -> AllPlayResult:
    """Expected wins = sum over weeks of (teams outscored)/(n-1).

    Ties count as half. ``scores_by_week`` maps week -> [(team_id, score)].
    """
    all_play_wins = 0.0
    all_play_games = 0.0
    for _week, entries in scores_by_week.items():
        mine = next((s for tid, s in entries if tid == team_season_id), None)
        if mine is None:
            continue
        others = [s for tid, s in entries if tid != team_season_id]
        if not others:
            continue
        beat = sum(1 for s in others if mine > s)
        tied = sum(1 for s in others if mine == s)
        all_play_wins += beat + 0.5 * tied
        all_play_games += len(others)
    expected_wins = 0.0
    # Expected wins expressed on the team's own schedule length: the fraction of
    # all-play games won, scaled by the number of weeks played.
    weeks_played = sum(
        1 for entries in scores_by_week.values() if any(tid == team_season_id for tid, _ in entries)
    )
    if all_play_games:
        expected_wins = (all_play_wins / all_play_games) * weeks_played
    return AllPlayResult(all_play_wins, all_play_games, expected_wins)


def points_against_percentile(
    team_season_id: int,
    pa_by_team: dict[int, float],
) -> float:
    """Percentile rank of this team's points-against within the season.

    1.0 = highest PA in the league (unluckiest schedule of opponents).
    """
    values = list(pa_by_team.values())
    if len(values) <= 1:
        return 0.0
    mine = pa_by_team[team_season_id]
    below = sum(1 for v in values if v < mine)
    return below / (len(values) - 1)
