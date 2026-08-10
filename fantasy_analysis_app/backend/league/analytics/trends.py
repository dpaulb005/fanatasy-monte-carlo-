"""League-wide trend metrics, emitted as chart-shaped JSON blobs.

Scoring evolution, weekly-score distribution (boxplot), and positional share
over the seasons. See docs/METRICS_CATALOG.md (League trends).
"""

from __future__ import annotations

from collections import defaultdict

from league.analytics.frames import LeagueFrames
from league.analytics.records import stddev

FLEX_POSITIONS = ["QB", "RB", "WR", "TE", "DST", "K"]


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(sorted_values) - 1)
    return round(sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo]), 2)


def _reg_scores_by_year(frames: LeagueFrames) -> dict[int, list[float]]:
    scores: dict[int, list[float]] = defaultdict(list)
    for tw in frames.team_weeks:
        if tw.kind == "REG":
            scores[tw.season_year].append(tw.score)
    return scores


def scoring_evolution(frames: LeagueFrames) -> dict:
    """Mean weekly team score per season, with a ±1σ band."""
    by_year = _reg_scores_by_year(frames)
    years = sorted(by_year)
    means = [round(sum(by_year[y]) / len(by_year[y]), 1) if by_year[y] else 0.0 for y in years]
    stds = [stddev(by_year[y]) for y in years]
    return {
        "labels": years,
        "series": [
            {"name": "Mean weekly score", "data": means},
            {"name": "Std dev", "data": stds},
        ],
    }


def weekly_distribution(frames: LeagueFrames) -> dict:
    """Boxplot stats [min, q1, median, q3, max] of team-week scores per season."""
    by_year = _reg_scores_by_year(frames)
    years = sorted(by_year)
    boxes = []
    for y in years:
        vals = sorted(by_year[y])
        boxes.append(
            [
                round(vals[0], 1) if vals else 0.0,
                _quantile(vals, 0.25),
                _quantile(vals, 0.5),
                _quantile(vals, 0.75),
                round(vals[-1], 1) if vals else 0.0,
            ]
        )
    return {"labels": years, "boxes": boxes}


def positional_share(frames: LeagueFrames) -> dict:
    """Share of started points by position per season (positional scarcity)."""
    # year -> position -> started points
    totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for tsf in frames.team_seasons.values():
        for roster in tsf.roster_by_week.values():
            for p in roster:
                if p.started:
                    pos = p.position if p.position in FLEX_POSITIONS else "OTHER"
                    totals[tsf.season_year][pos] += p.points
    years = sorted(totals)
    series = []
    for pos in FLEX_POSITIONS:
        data = []
        for y in years:
            year_total = sum(totals[y].values()) or 1.0
            data.append(round(100.0 * totals[y].get(pos, 0.0) / year_total, 1))
        series.append({"name": pos, "data": data})
    return {"labels": years, "series": series}


def compute_trends(frames: LeagueFrames) -> dict[str, dict]:
    """All league-wide trend blobs, keyed by trend name."""
    return {
        "scoring_evolution": scoring_evolution(frames),
        "weekly_distribution": weekly_distribution(frames),
        "positional_share": positional_share(frames),
    }


def compute_season_fingerprints(frames: LeagueFrames) -> dict[int, dict]:
    """Per-season small-multiple data: each team's weekly scores + W/L, with
    the league's weekly median for that season as the reference line.
    Answers "volatile or steady?" per manager without a radar chart (V-3)."""
    from statistics import median

    by_year: dict[int, dict] = {}
    weeks_by_team: dict[int, dict[int, tuple[float, bool]]] = defaultdict(dict)
    for tw in frames.team_weeks:
        if tw.kind == "REG":
            weeks_by_team[tw.team_season_id][tw.week] = (tw.score, tw.won)

    for year, week_scores in frames.scores_by_week.items():
        weeks = sorted(week_scores)
        if not weeks:
            continue
        all_scores = [s for w in weeks for _tsid, s in week_scores[w]]
        teams = []
        season_teams = [
            (ts_id, tsf) for ts_id, tsf in frames.team_seasons.items() if tsf.season_year == year
        ]
        for ts_id, tsf in sorted(season_teams, key=lambda e: e[1].final_standing or 99):
            label = tsf.manager_labels.get(tsf.manager_ids[0], "—") if tsf.manager_ids else "—"
            teams.append(
                {
                    "manager": label,
                    "final_standing": tsf.final_standing,
                    "weeks": [
                        {
                            "week": w,
                            "score": round(weeks_by_team[ts_id][w][0], 1),
                            "won": weeks_by_team[ts_id][w][1],
                        }
                        for w in weeks
                        if w in weeks_by_team[ts_id]
                    ],
                }
            )
        by_year[year] = {
            "weeks": weeks,
            "league_median": round(median(all_scores), 1) if all_scores else 0.0,
            "max_score": round(max(all_scores), 1) if all_scores else 0.0,
            "teams": teams,
        }
    return by_year
