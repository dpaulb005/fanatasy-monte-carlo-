"""Retrospective draft value.

Grades what actually happened: how many points a pick returned vs a positional
replacement level derived from the league's own data, its ADP delta (public
consensus, when available), and how it did vs the median pick in its round.
See docs/METRICS_CATALOG.md. Nothing here is predictive.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass

from league.analytics.frames import LeagueFrames, normalize_position

# Starting slots per position used to locate replacement level. FLEX adds ~0.5
# to each flex-eligible pool.
STARTERS_PER_POSITION = {"QB": 1.0, "RB": 2.5, "WR": 2.5, "TE": 1.2, "DST": 1.0, "K": 1.0}


@dataclass
class DraftValueRow:
    draft_pick_id: int
    season_points: float
    points_over_replacement: float
    adp: float | None
    adp_delta: float | None
    round_expectation_delta: float


def _replacement_levels(frames: LeagueFrames, year: int) -> dict[str, float]:
    """Points of the replacement-level player at each position, for one season.

    Replacement rank = round(starters_at_position * num_teams). Baseline = the
    points of the player at that rank; picks above it returned starter value.
    """
    num_teams = frames.team_count_by_year.get(year, 0)
    points = frames.player_season_points.get(year, {})
    positions = frames.player_position_by_year.get(year, {})
    by_pos: dict[str, list[float]] = defaultdict(list)
    for pid, pts in points.items():
        pos = positions.get(pid, "")
        if pos:
            by_pos[pos].append(pts)

    levels: dict[str, float] = {}
    for pos, starters in STARTERS_PER_POSITION.items():
        ranked = sorted(by_pos.get(pos, []), reverse=True)
        if not ranked:
            levels[pos] = 0.0
            continue
        rank = max(1, round(starters * num_teams))
        idx = min(rank, len(ranked)) - 1
        levels[pos] = ranked[idx]
    return levels


def compute_draft_values(
    frames: LeagueFrames,
    adp_lookup: dict[tuple[int, str], float] | None = None,
) -> list[DraftValueRow]:
    """One value row per draft pick. ``adp_lookup`` maps (year, norm_name)->adp."""
    adp_lookup = adp_lookup or {}

    # Round -> list of season points, across all history, for the round-median.
    round_points: dict[int, list[float]] = defaultdict(list)
    for pick in frames.draft_picks:
        year = pick.season.year
        pid = pick.player.espn_player_id
        pts = frames.player_season_points.get(year, {}).get(pid, 0.0)
        round_points[pick.round].append(pts)
    round_median = {r: statistics.median(v) for r, v in round_points.items() if v}

    levels_by_year = {y: _replacement_levels(frames, y) for y in frames.team_count_by_year}

    rows: list[DraftValueRow] = []
    for pick in frames.draft_picks:
        year = pick.season.year
        pid = pick.player.espn_player_id
        pos = frames.player_position_by_year.get(year, {}).get(
            pid, normalize_position(pick.player.position)
        )
        season_points = frames.player_season_points.get(year, {}).get(pid, 0.0)
        baseline = levels_by_year.get(year, {}).get(pos, 0.0)
        por = round(season_points - baseline, 2)

        adp = adp_lookup.get((year, _norm(pick.player.name)))
        adp_delta = round(pick.overall_pick - adp, 1) if adp is not None else None

        median = round_median.get(pick.round, season_points)
        rows.append(
            DraftValueRow(
                draft_pick_id=pick.id,
                season_points=round(season_points, 2),
                points_over_replacement=por,
                adp=adp,
                adp_delta=adp_delta,
                round_expectation_delta=round(season_points - median, 2),
            )
        )
    return rows


# Generational suffixes that FFC and ESPN apply inconsistently
# ("Deebo Samuel" vs "Deebo Samuel Sr.", "Anthony Richardson" vs "... Sr.").
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# ESPN names defenses by nickname ("Ravens D/ST"); FFC by city ("Baltimore
# Defense"). Static crosswalk, nickname -> FFC city label.
_DST_CITY = {
    "cardinals": "arizona",
    "falcons": "atlanta",
    "ravens": "baltimore",
    "bills": "buffalo",
    "panthers": "carolina",
    "bears": "chicago",
    "bengals": "cincinnati",
    "browns": "cleveland",
    "cowboys": "dallas",
    "broncos": "denver",
    "lions": "detroit",
    "packers": "green bay",
    "texans": "houston",
    "colts": "indianapolis",
    "jaguars": "jacksonville",
    "chiefs": "kansas city",
    "raiders": "las vegas",
    "chargers": "la chargers",
    "rams": "la rams",
    "dolphins": "miami",
    "vikings": "minnesota",
    "patriots": "new england",
    "saints": "new orleans",
    "giants": "ny giants",
    "jets": "ny jets",
    "eagles": "philadelphia",
    "steelers": "pittsburgh",
    "49ers": "san francisco",
    "seahawks": "seattle",
    "buccaneers": "tampa bay",
    "titans": "tennessee",
    "commanders": "washington",
    "washington": "washington",
}


def normalize_player_name(name: str) -> str:
    """Join key for ESPN<->FFC player names.

    Lowercases, drops periods/apostrophes, turns hyphens into spaces, strips
    trailing generational suffixes, and maps "<Nickname> D/ST" onto FFC's
    "<city> defense" form. Applied to BOTH sides of the ADP join so the rules
    only need to be mutually consistent, never "correct" in isolation.
    """
    n = name.strip().lower()
    if n.endswith(" d/st"):
        nickname = n[: -len(" d/st")].strip()
        return f"{_DST_CITY.get(nickname, nickname)} defense"
    n = n.replace(".", "").replace("'", "").replace("’", "").replace("-", " ")
    parts = n.split()
    while parts and parts[-1] in _NAME_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _norm(name: str) -> str:
    return normalize_player_name(name)
