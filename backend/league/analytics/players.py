"""Player value: per-season and manager-attributed production.

Derived entirely from rostered player-weeks (LineupSlot via frames), so it
covers started AND benched production but never free agents — this is "points
while rostered in this league", not NFL totals. Attribution is weekly: a
manager is credited only for weeks the player sat on a team they manage, so
mid-season moves split cleanly and manager rows sum to season rows (tested).
Replacement level reuses the draft-value definition so the league has exactly
one replacement concept. See docs/autonomous/METRIC_CATALOG.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from league.analytics.drafts import _replacement_levels
from league.analytics.frames import LeagueFrames


@dataclass
class _Tally:
    total_points: float = 0.0
    started_points: float = 0.0
    bench_points: float = 0.0
    weeks: set[int] = field(default_factory=set)
    started_weeks: set[int] = field(default_factory=set)


@dataclass
class PlayerSeasonRow:
    espn_player_id: int
    season_year: int
    position: str
    total_points: float
    started_points: float
    bench_points: float
    weeks_rostered: int
    weeks_started: int
    points_over_replacement: float
    position_rank: int


@dataclass
class PlayerManagerRow:
    espn_player_id: int
    manager_id: int
    season_year: int
    total_points: float
    started_points: float
    bench_points: float
    weeks_rostered: int
    weeks_started: int


def compute_player_values(
    frames: LeagueFrames,
) -> tuple[list[PlayerSeasonRow], list[PlayerManagerRow]]:
    season_tallies: dict[tuple[int, int], _Tally] = defaultdict(_Tally)
    manager_tallies: dict[tuple[int, int, int], _Tally] = defaultdict(_Tally)

    for pw in frames.player_weeks:
        tally = season_tallies[(pw.season_year, pw.espn_player_id)]
        _add(tally, pw.points, pw.started, pw.week)
        team = frames.team_seasons.get(pw.team_season_id)
        if team is None:
            continue
        for manager_id in team.manager_ids:
            _add(
                manager_tallies[(pw.season_year, pw.espn_player_id, manager_id)],
                pw.points,
                pw.started,
                pw.week,
            )

    levels_by_year = {y: _replacement_levels(frames, y) for y in frames.team_count_by_year}

    def season_position(year: int, pid: int) -> str:
        # Per-season label: ESPN relabels players across seasons, so a season's
        # pool must never be decided by the career-wide latest label.
        return frames.player_position_by_year.get(year, {}).get(pid, "")

    # Rank players by total points within (season, position).
    by_season_pos: dict[tuple[int, str], list[tuple[float, int]]] = defaultdict(list)
    for (year, pid), tally in season_tallies.items():
        by_season_pos[(year, season_position(year, pid))].append((tally.total_points, pid))
    position_rank: dict[tuple[int, int], int] = {}
    for (year, _pos), entries in by_season_pos.items():
        entries.sort(key=lambda e: (-e[0], e[1]))
        for rank, (_pts, pid) in enumerate(entries, start=1):
            position_rank[(year, pid)] = rank

    def points_over_replacement(year: int, pid: int, total: float) -> float:
        # Unknown/blank positions have no replacement pool; report 0 rather
        # than total-minus-nothing, which would float them above real stars.
        baseline = levels_by_year.get(year, {}).get(season_position(year, pid))
        return round(total - baseline, 2) if baseline is not None else 0.0

    season_rows = [
        PlayerSeasonRow(
            espn_player_id=pid,
            season_year=year,
            position=season_position(year, pid),
            total_points=round(tally.total_points, 2),
            started_points=round(tally.started_points, 2),
            bench_points=round(tally.bench_points, 2),
            weeks_rostered=len(tally.weeks),
            weeks_started=len(tally.started_weeks),
            points_over_replacement=points_over_replacement(year, pid, tally.total_points),
            position_rank=position_rank[(year, pid)],
        )
        for (year, pid), tally in season_tallies.items()
    ]

    manager_rows = [
        PlayerManagerRow(
            espn_player_id=pid,
            manager_id=manager_id,
            season_year=year,
            total_points=round(tally.total_points, 2),
            started_points=round(tally.started_points, 2),
            bench_points=round(tally.bench_points, 2),
            weeks_rostered=len(tally.weeks),
            weeks_started=len(tally.started_weeks),
        )
        for (year, pid, manager_id), tally in manager_tallies.items()
    ]
    return season_rows, manager_rows


def _add(tally: _Tally, points: float, started: bool, week: int) -> None:
    tally.total_points += points
    tally.weeks.add(week)
    if started:
        tally.started_points += points
        tally.started_weeks.add(week)
    else:
        tally.bench_points += points
