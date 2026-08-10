"""Museum of Pain: formula-backed exhibits of the league's worst moments.

Every exhibit is a documented formula over real matchup/lineup data with the
games behind it attached — comedy grounded entirely in evidence (see the
comedy rules in docs/autonomous/PRODUCT_BACKLOG.md). Stored as a SeasonTrend
blob (key ``museum_of_pain``), so adding an exhibit needs no schema change.
"""

from __future__ import annotations

from typing import Any

from league.analytics.frames import LeagueFrames, TeamWeekFrame
from league.analytics.lineups import week_efficiency

TOP_N = 5


def _label(frames: LeagueFrames, team_season_id: int) -> str:
    tsf = frames.team_seasons.get(team_season_id)
    if tsf is None or not tsf.manager_ids:
        return "—"
    return tsf.manager_labels.get(tsf.manager_ids[0], "—")


def _game(frames: LeagueFrames, tw: TeamWeekFrame, value: float) -> dict:
    return {
        "year": tw.season_year,
        "week": tw.week,
        "manager": _label(frames, tw.team_season_id),
        "opponent": (
            _label(frames, tw.opponent_team_season_id)
            if tw.opponent_team_season_id is not None
            else "—"
        ),
        "score": round(tw.score, 2),
        "opponent_score": round(tw.opponent_score, 2),
        "value": round(value, 2),
    }


def compute_museum(frames: LeagueFrames, careers: dict[int, dict]) -> dict:
    """Assemble the exhibits. ``careers`` is the engine's per-manager career
    aggregate (for streaks); manager labels come from the frames."""
    reg = [tw for tw in frames.team_weeks if tw.kind == "REG"]
    losses = [tw for tw in reg if tw.lost]
    wins = [tw for tw in reg if tw.won]

    exhibits: list[dict[str, Any]] = []

    def add(slug: str, title: str, formula: str, entries: list[dict]) -> None:
        if entries:
            exhibits.append(
                {"slug": slug, "title": title, "formula": formula, "entries": entries[:TOP_N]}
            )

    add(
        "closest-loss",
        "Agony by a Whisker",
        "Smallest positive losing margin (opponent score − score), regular season.",
        [
            _game(frames, tw, tw.opponent_score - tw.score)
            for tw in sorted(losses, key=lambda t: t.opponent_score - t.score)
        ],
    )
    add(
        "highest-score-loss",
        "Wasted Masterpiece",
        "Highest score that still lost, regular season.",
        [_game(frames, tw, tw.score) for tw in sorted(losses, key=lambda t: -t.score)],
    )
    add(
        "lowest-score-win",
        "Daylight Burglary",
        "Lowest score that still won, regular season.",
        [_game(frames, tw, tw.score) for tw in sorted(wins, key=lambda t: t.score)],
    )
    add(
        "biggest-blowout",
        "Total Annihilation",
        "Largest losing margin, regular season (shown from the loser's side).",
        [
            _game(frames, tw, tw.opponent_score - tw.score)
            for tw in sorted(losses, key=lambda t: t.score - t.opponent_score)
        ],
    )

    # Single worst bench week: biggest (optimal − actual) gap in one week.
    bench_weeks: list[tuple[float, TeamWeekFrame]] = []
    tw_by_team_week = {(tw.team_season_id, tw.week): tw for tw in reg}
    for ts_id, tsf in frames.team_seasons.items():
        for week, roster in tsf.roster_by_week.items():
            tw = tw_by_team_week.get((ts_id, week))
            if tw is None:
                continue
            actual, optimal, bench = week_efficiency(roster)
            if bench > 0:
                bench_weeks.append((bench, tw))
    add(
        "worst-bench-week",
        "The Bench Was Right There",
        "Largest single-week gap between the best legal lineup and the one started.",
        [_game(frames, tw, gap) for gap, tw in sorted(bench_weeks, key=lambda e: -e[0])],
    )

    # Longest losing streaks, from career aggregates (labels via frames).
    labels: dict[int, str] = {}
    for tsf in frames.team_seasons.values():
        labels.update(tsf.manager_labels)
    streaks = sorted(
        (
            (agg.get("longest_lose_streak", 0), mid)
            for mid, agg in careers.items()
            if agg.get("longest_lose_streak", 0) > 0
        ),
        key=lambda e: -e[0],
    )
    add(
        "longest-losing-streak",
        "The Dark Ages",
        "Most consecutive regular-season losses, career.",
        [
            {
                "year": None,
                "week": None,
                "manager": labels.get(mid, "—"),
                "opponent": "everyone",
                "score": None,
                "opponent_score": None,
                "value": streak,
            }
            for streak, mid in streaks
        ],
    )

    return {"exhibits": exhibits}
