"""Load-once in-memory frames for the analytics engine.

The whole league is pulled into plain dataclasses in a handful of queries, then
every metric module reads these — nothing re-queries the DB mid-compute. At
league scale (a few thousand team-weeks) pure-Python aggregation is instant, so
we avoid a pandas dependency on the compute path (ADR-010).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from league.models import DraftPick, LineupSlot, Matchup, Season, TeamSeason

# ESPN labels defenses "D/ST" but every analytics table (starter slots,
# replacement levels, trend buckets) uses the canonical "DST". Normalize at the
# frames boundary so no metric module ever sees a raw ESPN label.
_POSITION_ALIASES = {"D/ST": "DST"}


def normalize_position(position: str) -> str:
    return _POSITION_ALIASES.get(position, position)


@dataclass
class TeamWeekFrame:
    season_year: int
    week: int
    team_season_id: int
    score: float
    opponent_team_season_id: int | None
    opponent_score: float
    kind: str
    won: bool
    lost: bool
    tied: bool


@dataclass
class RosterPlayerFrame:
    position: str
    points: float
    slot: str
    started: bool


@dataclass
class PlayerWeekFrame:
    """One rostered player-week, with identity — the basis of player value."""

    season_year: int
    week: int
    espn_player_id: int
    player_name: str
    position: str
    team_season_id: int
    started: bool
    points: float


@dataclass
class TeamSeasonFrame:
    id: int
    season_year: int
    manager_ids: list[int]
    manager_labels: dict[int, str]
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    final_standing: int
    made_playoffs: bool
    # (week -> list of rostered players that week)
    roster_by_week: dict[int, list[RosterPlayerFrame]] = field(default_factory=dict)


@dataclass
class LeagueFrames:
    league_id: int
    team_count_by_year: dict[int, int]
    team_seasons: dict[int, TeamSeasonFrame]  # keyed by TeamSeason.id
    team_weeks: list[TeamWeekFrame]
    # season_year -> week -> list of (team_season_id, score) for all-play
    scores_by_week: dict[int, dict[int, list[tuple[int, float]]]]
    draft_picks: list[DraftPick]
    # season_year -> espn_player_id -> total fantasy points that season
    player_season_points: dict[int, dict[int, float]]
    # espn_player_id -> latest position seen across all seasons (display only)
    player_position: dict[int, str]
    # every rostered player-week with identity (started + bench)
    player_weeks: list[PlayerWeekFrame] = field(default_factory=list)
    # espn_player_id -> latest name seen
    player_names: dict[int, str] = field(default_factory=dict)
    # season_year -> espn_player_id -> position label that season. Use this for
    # per-season pools (rank, replacement) — ESPN relabels players across
    # seasons (TE→WR reclassifications, Taysom Hill), so the career-wide map
    # must never decide a season's position bucket.
    player_position_by_year: dict[int, dict[int, str]] = field(default_factory=dict)


def _team_week_rows(matchups: list[Matchup]) -> list[TeamWeekFrame]:
    rows: list[TeamWeekFrame] = []
    for m in matchups:
        if m.away_id is None:
            continue
        rows.append(
            TeamWeekFrame(
                season_year=m.season.year,
                week=m.week,
                team_season_id=m.home_id,
                score=m.home_score,
                opponent_team_season_id=m.away_id,
                opponent_score=m.away_score,
                kind=m.kind,
                won=m.home_score > m.away_score,
                lost=m.home_score < m.away_score,
                tied=m.home_score == m.away_score,
            )
        )
        rows.append(
            TeamWeekFrame(
                season_year=m.season.year,
                week=m.week,
                team_season_id=m.away_id,
                score=m.away_score,
                opponent_team_season_id=m.home_id,
                opponent_score=m.home_score,
                kind=m.kind,
                won=m.away_score > m.home_score,
                lost=m.away_score < m.home_score,
                tied=m.away_score == m.home_score,
            )
        )
    return rows


def load_frames(league_id: int) -> LeagueFrames:
    seasons = list(Season.objects.filter(league__espn_league_id=league_id))
    season_ids = [s.id for s in seasons]

    team_seasons_qs = (
        TeamSeason.objects.filter(season_id__in=season_ids)
        .select_related("season")
        .prefetch_related("managers", "managers__merged_into")
    )
    team_seasons: dict[int, TeamSeasonFrame] = {}
    team_count_by_year: dict[int, int] = defaultdict(int)
    for ts in team_seasons_qs:
        # Identity continuity: attribute every team to the canonical manager.
        # Source rows (second ESPN accounts) are resolved here, in one place,
        # so every metric downstream sees a single human per identity.
        managers = list({m.canonical.id: m.canonical for m in ts.managers.all()}.values())
        team_seasons[ts.id] = TeamSeasonFrame(
            id=ts.id,
            season_year=ts.season.year,
            manager_ids=[m.id for m in managers],
            manager_labels={m.id: m.label for m in managers},
            wins=ts.wins,
            losses=ts.losses,
            ties=ts.ties,
            points_for=ts.points_for,
            points_against=ts.points_against,
            final_standing=ts.final_standing,
            made_playoffs=ts.made_playoffs,
        )
        team_count_by_year[ts.season.year] += 1

    matchups = list(Matchup.objects.filter(season_id__in=season_ids).select_related("season"))
    team_weeks = _team_week_rows(matchups)

    # All-play scores per (year, week) from regular-season games only.
    scores_by_week: dict[int, dict[int, list[tuple[int, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for tw in team_weeks:
        if tw.kind == Matchup.Kind.REGULAR:
            scores_by_week[tw.season_year][tw.week].append((tw.team_season_id, tw.score))

    # Rosters by week for lineup analytics, plus per-player season totals for
    # draft value (a player's full-season fantasy production while rostered).
    player_season_points: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    player_position: dict[int, str] = {}
    player_position_by_year: dict[int, dict[int, str]] = defaultdict(dict)
    player_weeks: list[PlayerWeekFrame] = []
    player_names: dict[int, str] = {}
    lineup_qs = (
        LineupSlot.objects.filter(team_season__season_id__in=season_ids)
        .select_related("player")
        .only(
            "team_season_id",
            "week",
            "slot",
            "points",
            "player__espn_player_id",
            "player__position",
            "player__name",
        )
        # Deterministic iteration so "latest label wins" is stable.
        .order_by("team_season__season__year", "week", "id")
    )
    for slot in lineup_qs:
        tsf = team_seasons.get(slot.team_season_id)
        if tsf is None:
            continue
        started = slot.slot not in {LineupSlot.Slot.BENCH, LineupSlot.Slot.IR}
        position = normalize_position(slot.player.position)
        tsf.roster_by_week.setdefault(slot.week, []).append(
            RosterPlayerFrame(
                position=position,
                points=slot.points,
                slot=slot.slot,
                started=started,
            )
        )
        pid = slot.player.espn_player_id
        player_season_points[tsf.season_year][pid] += slot.points
        player_position[pid] = position
        player_position_by_year[tsf.season_year][pid] = position
        player_names[pid] = slot.player.name
        player_weeks.append(
            PlayerWeekFrame(
                season_year=tsf.season_year,
                week=slot.week,
                espn_player_id=pid,
                player_name=slot.player.name,
                position=position,
                team_season_id=slot.team_season_id,
                started=started,
                points=slot.points,
            )
        )

    draft_picks = list(
        DraftPick.objects.filter(season_id__in=season_ids).select_related(
            "player", "team_season", "season"
        )
    )

    return LeagueFrames(
        league_id=league_id,
        team_count_by_year=dict(team_count_by_year),
        team_seasons=team_seasons,
        team_weeks=team_weeks,
        scores_by_week={y: dict(w) for y, w in scores_by_week.items()},
        draft_picks=draft_picks,
        player_season_points={y: dict(p) for y, p in player_season_points.items()},
        player_position=player_position,
        player_weeks=player_weeks,
        player_names=player_names,
        player_position_by_year={y: dict(p) for y, p in player_position_by_year.items()},
    )
