"""Read helpers that shape computed tables into API/chart-ready payloads.

Keeps query logic out of views. Everything here reads precomputed tables, so
these are cheap indexed lookups.
"""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Max, Min, Q, Sum
from django.http import Http404

from league.analytics.frames import normalize_position
from league.models import (
    Award,
    DraftPick,
    HeadToHeadRecord,
    League,
    LineupSlot,
    Manager,
    ManagerCareerStats,
    ManagerSeasonStats,
    Player,
    PlayerManagerSeasonValue,
    PlayerSeasonValue,
    Season,
    SeasonTrend,
    SyncLog,
    TeamSeason,
)


def get_active_league() -> League:
    league = League.objects.order_by("id").first()
    if league is None:
        raise Http404("No league has been synced yet.")
    return league


def _manager_ref(manager: Manager) -> dict:
    return {"id": manager.id, "label": manager.label}


def _opt_manager_ref(manager: Manager | None) -> dict | None:
    return _manager_ref(manager) if manager is not None else None


def league_overview() -> dict:
    league = get_active_league()
    seasons = list(Season.objects.filter(league=league).order_by("-year"))
    champions = []
    for season in seasons:
        champ = (
            TeamSeason.objects.filter(season=season, final_standing=1)
            .prefetch_related("managers")
            .first()
        )
        winner = None
        if champ:
            mgr = champ.managers.first()
            winner = {
                "team": champ.team_name,
                "manager": _opt_manager_ref(mgr),
            }
        champions.append(
            {
                "year": season.year,
                "team_count": season.team_seasons.count(),
                "is_complete": season.is_complete,
                "champion": winner,
            }
        )

    last_sync = (
        SyncLog.objects.filter(status=SyncLog.Status.SUCCESS).order_by("-finished_at").first()
    )

    return {
        "league": {"id": league.espn_league_id, "name": league.name},
        "seasons": champions,
        "champions_timeline": [
            {"year": c["year"], "champion": c["champion"]} for c in reversed(champions)
        ],
        "last_sync": (
            {
                "command": last_sync.command,
                "finished_at": last_sync.finished_at,
                "row_counts": last_sync.row_counts,
            }
            if last_sync
            else None
        ),
    }


def manager_career_table() -> list[dict]:
    rows = ManagerCareerStats.objects.select_related("manager").order_by("-wins", "-championships")
    table = []
    for c in rows:
        table.append(
            {
                "manager": _manager_ref(c.manager),
                "seasons_played": c.seasons_played,
                "wins": c.wins,
                "losses": c.losses,
                "ties": c.ties,
                "win_pct": round(c.win_pct, 3),
                "championships": c.championships,
                "playoff_appearances": c.playoff_appearances,
                "sackos": c.sackos,
                "total_luck_delta": round(c.total_luck_delta, 2),
                "longest_win_streak": c.longest_win_streak,
                "longest_lose_streak": c.longest_lose_streak,
            }
        )
    return table


def _season_stat_row(s: ManagerSeasonStats) -> dict:
    return {
        "year": s.season.year,
        "wins": s.wins,
        "losses": s.losses,
        "ties": s.ties,
        "points_for": round(s.points_for, 1),
        "points_against": round(s.points_against, 1),
        "expected_wins": round(s.expected_wins, 2),
        "luck_delta": round(s.luck_delta, 2),
        "lineup_efficiency": round(s.lineup_efficiency, 4),
        "bench_points_lost": round(s.bench_points_lost, 1),
        "bench_losses": s.bench_losses,
        "points_against_percentile": round(s.points_against_percentile, 3),
        "weekly_score_stddev": s.weekly_score_stddev,
        "final_standing": s.final_standing,
        "made_playoffs": s.made_playoffs,
    }


def manager_profile(manager_id: int) -> dict:
    try:
        manager = Manager.objects.get(id=manager_id)
    except Manager.DoesNotExist as exc:
        raise Http404("Manager not found.") from exc
    # A merged (duplicate-account) id resolves to its canonical manager so old
    # links keep working after an identity merge.
    manager = manager.canonical

    seasons = list(
        ManagerSeasonStats.objects.filter(manager=manager)
        .select_related("season")
        .order_by("season__year")
    )
    career = getattr(manager, "career_stats", None)

    return {
        "manager": _manager_ref(manager),
        "career": (
            {
                "seasons_played": career.seasons_played,
                "wins": career.wins,
                "losses": career.losses,
                "ties": career.ties,
                "win_pct": round(career.win_pct, 3),
                "championships": career.championships,
                "playoff_appearances": career.playoff_appearances,
                "sackos": career.sackos,
                "total_luck_delta": round(career.total_luck_delta, 2),
                "longest_win_streak": career.longest_win_streak,
                "longest_lose_streak": career.longest_lose_streak,
            }
            if career
            else None
        ),
        "seasons": [_season_stat_row(s) for s in seasons],
        # Chart-shaped: actual vs expected wins over time (luck visual).
        "luck_chart": {
            "labels": [s.season.year for s in seasons],
            "series": [
                {"name": "Actual wins", "data": [s.wins for s in seasons]},
                {"name": "Expected wins", "data": [round(s.expected_wins, 2) for s in seasons]},
            ],
        },
    }


def season_detail(year: int) -> dict:
    league = get_active_league()
    try:
        season = Season.objects.get(league=league, year=year)
    except Season.DoesNotExist as exc:
        raise Http404("Season not found.") from exc

    stats = (
        ManagerSeasonStats.objects.filter(season=season)
        .select_related("manager", "team_season")
        .order_by("final_standing")
    )
    standings = []
    for s in stats:
        standings.append(
            {
                "rank": s.final_standing,
                "team": s.team_season.team_name,
                "manager": _manager_ref(s.manager),
                "wins": s.wins,
                "losses": s.losses,
                "ties": s.ties,
                "points_for": round(s.points_for, 1),
                "points_against": round(s.points_against, 1),
                "expected_wins": round(s.expected_wins, 2),
                "luck_delta": round(s.luck_delta, 2),
                "made_playoffs": s.made_playoffs,
            }
        )
    champion = next((row for row in standings if row["rank"] == 1), None)

    fp = SeasonTrend.objects.filter(season=season, key="weekly_fingerprints").first()

    return {
        "year": season.year,
        "is_complete": season.is_complete,
        "lineups_available": season.lineups_available,
        "champion": champion,
        "standings": standings,
        # Small-multiple weekly scoring data; null until analytics recompute.
        "fingerprints": fp.data if fp else None,
    }


def season_draft(year: int) -> dict:
    """Draft board for one season with retrospective value + ADP, chart-shaped."""
    league = get_active_league()
    try:
        season = Season.objects.get(league=league, year=year)
    except Season.DoesNotExist as exc:
        raise Http404("Season not found.") from exc

    picks_qs = (
        DraftPick.objects.filter(season=season)
        .select_related("player", "team_season", "value")
        .prefetch_related("team_season__managers")
        .order_by("overall_pick")
    )

    picks = []
    round_points: dict[int, list[float]] = {}
    scatter = []  # [adp, season_points, por] for the ADP-vs-outcome chart
    for p in picks_qs:
        value = getattr(p, "value", None)
        manager = p.team_season.managers.first()
        season_points = value.season_points if value else 0.0
        picks.append(
            {
                "overall_pick": p.overall_pick,
                "round": p.round,
                "round_pick": p.round_pick,
                "team": p.team_season.team_name,
                "manager": _manager_ref(manager) if manager else None,
                "player_name": p.player.name,
                "position": p.player.position,
                "season_points": round(season_points, 1),
                "points_over_replacement": round(value.points_over_replacement, 1)
                if value
                else 0.0,
                "adp": value.adp if value else None,
                "adp_delta": value.adp_delta if value else None,
            }
        )
        round_points.setdefault(p.round, []).append(season_points)
        if value and value.adp is not None:
            scatter.append(
                [value.adp, round(season_points, 1), round(value.points_over_replacement, 1)]
            )

    rounds = sorted(round_points)
    median_by_round = []
    for r in rounds:
        vals = sorted(round_points[r])
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        median_by_round.append(round(median, 1))

    return {
        "year": season.year,
        "picks": picks,
        "round_value_curve": {
            "labels": rounds,
            "series": [{"name": "Median points by round", "data": median_by_round}],
        },
        "scatter": scatter,
    }


# League-wide SeasonTrend blobs that have their own endpoint and must not leak
# into the generic /trends/ payload.
_STANDALONE_TREND_KEYS = ("museum_of_pain", "draft_patterns", "draft_priors")


def league_trends() -> dict:
    """All league-wide trend blobs, keyed by trend name."""
    get_active_league()  # 404 if nothing synced
    trends = SeasonTrend.objects.filter(season__isnull=True).exclude(key__in=_STANDALONE_TREND_KEYS)
    return {t.key: t.data for t in trends}


def draft_patterns() -> dict:
    """The draft patterns blob (computed by analytics/draft_patterns.py)."""
    get_active_league()
    row = SeasonTrend.objects.filter(season__isnull=True, key="draft_patterns").first()
    if row is None:
        raise Http404("Draft patterns not computed yet — run compute_analytics.")
    return row.data


def museum_of_pain() -> dict:
    """The Museum of Pain exhibits blob (computed by analytics/museum.py)."""
    get_active_league()
    row = SeasonTrend.objects.filter(season__isnull=True, key="museum_of_pain").first()
    if row is None:
        raise Http404("Museum not computed yet — run compute_analytics.")
    return row.data


def awards() -> dict:
    """All awards grouped by season (plus an all-time list) for the Hall of Fame."""
    get_active_league()
    rows = Award.objects.select_related("winner", "season").order_by("-season__year", "slug")
    by_season: dict[str, list[dict]] = defaultdict(list)
    all_time: list[dict] = []
    for a in rows:
        entry = {
            "slug": a.slug,
            "title": a.title,
            "winner": _manager_ref(a.winner) if a.winner else None,
            "value": round(a.value, 1),
            "context": a.context,
        }
        if a.season is None:
            all_time.append(entry)
        else:
            by_season[str(a.season.year)].append(entry)
    return {
        "seasons": [
            {"year": int(year), "awards": entries}
            for year, entries in sorted(by_season.items(), key=lambda kv: -int(kv[0]))
        ],
        "all_time": all_time,
    }


def record_book() -> dict:
    """All-time single-game and career records for the record book."""
    league = get_active_league()
    season_ids = list(Season.objects.filter(league=league).values_list("id", flat=True))

    top_weeks = (
        ManagerSeasonStats.objects.filter(season_id__in=season_ids)
        .select_related("manager", "season")
        .order_by("-points_for")[:5]
    )
    best_luck = (
        ManagerSeasonStats.objects.filter(season_id__in=season_ids)
        .select_related("manager", "season")
        .order_by("-luck_delta")[:5]
    )
    worst_benches = (
        ManagerSeasonStats.objects.filter(season_id__in=season_ids)
        .select_related("manager", "season")
        .order_by("-bench_points_lost")[:5]
    )

    def _rows(qs, field: str) -> list[dict]:
        return [
            {
                "manager": _manager_ref(s.manager),
                "year": s.season.year,
                "value": round(getattr(s, field), 1),
            }
            for s in qs
        ]

    return {
        "most_points_season": _rows(top_weeks, "points_for"),
        "luckiest_seasons": _rows(best_luck, "luck_delta"),
        "biggest_bench_disasters": _rows(worst_benches, "bench_points_lost"),
    }


def h2h_matrix() -> dict:
    managers = list(Manager.objects.order_by("id"))
    index = {m.id: i for i, m in enumerate(managers)}
    n = len(managers)
    # cell[i][j] = manager i's record vs manager j.
    matrix: list[list[dict | None]] = [[None] * n for _ in range(n)]

    for rec in HeadToHeadRecord.objects.all():
        i, j = index.get(rec.manager_a_id), index.get(rec.manager_b_id)
        if i is None or j is None:
            continue
        a_games = rec.a_wins + rec.b_wins + rec.ties
        matrix[i][j] = {
            "wins": rec.a_wins,
            "losses": rec.b_wins,
            "ties": rec.ties,
            "win_pct": round((rec.a_wins + 0.5 * rec.ties) / a_games, 3) if a_games else None,
        }
        matrix[j][i] = {
            "wins": rec.b_wins,
            "losses": rec.a_wins,
            "ties": rec.ties,
            "win_pct": round((rec.b_wins + 0.5 * rec.ties) / a_games, 3) if a_games else None,
        }

    return {
        "managers": [_manager_ref(m) for m in managers],
        "matrix": matrix,
    }


def h2h_pair(a_id: int, b_id: int) -> dict:
    lo, hi = sorted((a_id, b_id))
    rec = HeadToHeadRecord.objects.filter(Q(manager_a_id=lo, manager_b_id=hi)).first()
    managers = {m.id: m for m in Manager.objects.filter(id__in=(a_id, b_id))}
    if a_id not in managers or b_id not in managers:
        raise Http404("Manager not found.")
    if rec is None:
        return {
            "manager_a": _manager_ref(managers[a_id]),
            "manager_b": _manager_ref(managers[b_id]),
            "record": {"a_wins": 0, "b_wins": 0, "ties": 0},
        }
    # Orient so a=a_id.
    if a_id == lo:
        a_wins, b_wins, a_pts, b_pts = rec.a_wins, rec.b_wins, rec.a_points, rec.b_points
    else:
        a_wins, b_wins, a_pts, b_pts = rec.b_wins, rec.a_wins, rec.b_points, rec.a_points
    return {
        "manager_a": _manager_ref(managers[a_id]),
        "manager_b": _manager_ref(managers[b_id]),
        "record": {
            "a_wins": a_wins,
            "b_wins": b_wins,
            "ties": rec.ties,
            "a_points": round(a_pts, 1),
            "b_points": round(b_pts, 1),
            "playoff_meetings": rec.playoff_meetings,
            "largest_margin": round(rec.largest_margin, 1),
        },
    }


# --- Players (P-1: player value + explorer) ---------------------------------


def _player_ref(player: Player) -> dict:
    # espn_player_id is ESPN's public identifier — safe to expose, unlike pks.
    return {
        "id": player.espn_player_id,
        "name": player.name,
        "position": normalize_position(player.position),
    }


def players_index(
    season: int | None = None,
    position: str = "",
    sort: str = "por",
    query: str = "",
    limit: int = 100,
) -> dict:
    """Bounded player list. Season view reads PlayerSeasonValue directly;
    career view aggregates it per player. Sort: 'por' | 'points'."""
    limit = max(1, min(int(limit), 200))
    league = get_active_league()
    years = list(
        Season.objects.filter(league=league).order_by("-year").values_list("year", flat=True)
    )

    qs = PlayerSeasonValue.objects.filter(season__league=league).select_related("player", "season")
    if position:
        qs = qs.filter(position=position)
    if query:
        qs = qs.filter(player__name__icontains=query)

    rows: list[dict]
    if season is not None:
        order = "-points_over_replacement" if sort == "por" else "-total_points"
        rows = [
            {
                "player": _player_ref(v.player),
                "season": v.season.year,
                "total_points": v.total_points,
                "started_points": v.started_points,
                "bench_points": v.bench_points,
                "weeks_rostered": v.weeks_rostered,
                "weeks_started": v.weeks_started,
                "points_over_replacement": v.points_over_replacement,
                "position_rank": v.position_rank,
            }
            for v in qs.filter(season__year=season).order_by(order)[:limit]
        ]
    else:
        agg = (
            qs.values(
                "player__espn_player_id",
                "player__name",
            )
            .annotate(
                # Normalized position from the computed rows (a player's raw
                # ESPN label may be "D/ST"; PlayerSeasonValue stores "DST").
                pos=Max("position"),
                total_points=Sum("total_points"),
                started_points=Sum("started_points"),
                bench_points=Sum("bench_points"),
                weeks_rostered=Sum("weeks_rostered"),
                weeks_started=Sum("weeks_started"),
                points_over_replacement=Sum("points_over_replacement"),
                seasons=Count("season", distinct=True),
                best_position_rank=Min("position_rank"),
            )
            .order_by("-points_over_replacement" if sort == "por" else "-total_points")[:limit]
        )
        rows = [
            {
                "player": {
                    "id": a["player__espn_player_id"],
                    "name": a["player__name"],
                    "position": a["pos"],
                },
                "seasons": a["seasons"],
                "total_points": round(a["total_points"] or 0.0, 2),
                "started_points": round(a["started_points"] or 0.0, 2),
                "bench_points": round(a["bench_points"] or 0.0, 2),
                "weeks_rostered": a["weeks_rostered"],
                "weeks_started": a["weeks_started"],
                "points_over_replacement": round(a["points_over_replacement"] or 0.0, 2),
                "best_position_rank": a["best_position_rank"],
            }
            for a in agg
        ]

    return {
        "mode": "season" if season is not None else "career",
        "season": season,
        "available_seasons": years,
        "players": rows,
        # UI copy relies on this caveat: value counts only weeks ON a roster.
        "note": (
            "Points while rostered in this league (started + benched); "
            "free-agent weeks are not visible to ESPN league data."
        ),
    }


def player_detail(espn_player_id: int) -> dict:
    league = get_active_league()
    player = Player.objects.filter(espn_player_id=espn_player_id).first()
    if player is None:
        raise Http404("Player not found.")

    season_values = list(
        PlayerSeasonValue.objects.filter(player=player, season__league=league)
        .select_related("season")
        .order_by("season__year")
    )
    if not season_values:
        # Player row exists (possibly from another synced league or a
        # no-lineup era) but has no data here — treat as not found rather
        # than rendering a degenerate all-zero page.
        raise Http404("Player has no data in this league.")
    manager_values = list(
        PlayerManagerSeasonValue.objects.filter(player=player, season__league=league)
        .select_related("season", "manager")
        .order_by("season__year", "-total_points")
    )
    picks = list(
        DraftPick.objects.filter(player=player, season__league=league)
        .select_related("season", "team_season")
        .prefetch_related("team_season__managers")
        .order_by("season__year")
    )
    # .all() hits the prefetch cache; .first() would re-query per row (N+1).
    pick_managers = {p.id: next(iter(p.team_season.managers.all()), None) for p in picks}

    # Ownership strip: one row per rostered week (~17 per season, bounded).
    slots = list(
        LineupSlot.objects.filter(player=player, team_season__season__league=league)
        .select_related("team_season__season")
        .prefetch_related("team_season__managers")
        .order_by("team_season__season__year", "week")
    )
    weekly: dict[int, list[dict]] = defaultdict(list)
    best_week: dict | None = None
    for s in slots:
        mgr = next(iter(s.team_season.managers.all()), None)
        row = {
            "week": s.week,
            "points": s.points,
            "started": s.slot not in (LineupSlot.Slot.BENCH, LineupSlot.Slot.IR),
            "slot": s.slot,
            "manager": _opt_manager_ref(mgr),
            "team": s.team_season.team_name,
        }
        weekly[s.team_season.season.year].append(row)
        if best_week is None or s.points > best_week["points"]:
            best_week = {"year": s.team_season.season.year, **row}

    career = {
        "seasons": len(season_values),
        "total_points": round(sum(v.total_points for v in season_values), 2),
        "started_points": round(sum(v.started_points for v in season_values), 2),
        "bench_points": round(sum(v.bench_points for v in season_values), 2),
        "weeks_rostered": sum(v.weeks_rostered for v in season_values),
        "weeks_started": sum(v.weeks_started for v in season_values),
        "points_over_replacement": round(sum(v.points_over_replacement for v in season_values), 2),
        "best_position_rank": min((v.position_rank for v in season_values), default=None),
        "best_week": best_week,
    }

    return {
        "player": _player_ref(player),
        "career": career,
        "seasons": [
            {
                "year": v.season.year,
                "position": v.position,
                "total_points": v.total_points,
                "started_points": v.started_points,
                "bench_points": v.bench_points,
                "weeks_rostered": v.weeks_rostered,
                "weeks_started": v.weeks_started,
                "points_over_replacement": v.points_over_replacement,
                "position_rank": v.position_rank,
            }
            for v in season_values
        ],
        "managers": [
            {
                "year": v.season.year,
                "manager": _manager_ref(v.manager),
                "total_points": v.total_points,
                "started_points": v.started_points,
                "bench_points": v.bench_points,
                "weeks_rostered": v.weeks_rostered,
                "weeks_started": v.weeks_started,
            }
            for v in manager_values
        ],
        "draft_picks": [
            {
                "year": p.season.year,
                "round": p.round,
                "round_pick": p.round_pick,
                "overall_pick": p.overall_pick,
                "is_keeper": p.is_keeper,
                "manager": _opt_manager_ref(pick_managers.get(p.id)),
            }
            for p in picks
        ],
        "weekly": [{"year": year, "weeks": rows} for year, rows in sorted(weekly.items())],
    }


# --- Manager scouting report (M-1) ------------------------------------------

# Minimum seasons before a manager gets percentile-ranked. One season of
# variance is not an identity.
SCOUTING_MIN_SEASONS = 2


def _scouting_traits(stats_by_manager: dict[int, list[ManagerSeasonStats]]) -> dict[int, dict]:
    """Career trait values per manager, from per-season computed stats only."""
    traits: dict[int, dict] = {}
    for mid, seasons in stats_by_manager.items():
        games = sum(s.wins + s.losses + s.ties for s in seasons)
        weeks = max(games, 1)
        losses = sum(s.losses for s in seasons)
        optimal = sum(s.optimal_points for s in seasons)
        pf = sum(s.points_for for s in seasons)
        traits[mid] = {
            "seasons": len(seasons),
            "firepower": round(pf / weeks, 2),
            "volatility": round(sum(s.weekly_score_stddev for s in seasons) / len(seasons), 2),
            "fortune": round(sum(s.luck_delta for s in seasons), 2),
            "discipline": round(pf / optimal, 4) if optimal else 0.0,
            "self_sabotage": round(sum(s.bench_losses for s in seasons) / losses, 3)
            if losses
            else 0.0,
        }
    return traits


_TRAIT_META = [
    ("firepower", "Firepower", "Career points per game", False),
    ("volatility", "Volatility", "Average weekly scoring swing (std dev)", False),
    ("fortune", "Fortune", "Career wins above expected (all-play)", False),
    ("discipline", "Discipline", "Started points as a share of the best legal lineup", False),
    ("self_sabotage", "Self-sabotage", "Share of losses a legal lineup swap would have won", True),
]


def manager_scouting(manager_id: int) -> dict:
    """Percentile-based identity card. Percentiles are among managers with at
    least SCOUTING_MIN_SEASONS seasons; smaller samples get no ranking."""
    manager = Manager.objects.filter(id=manager_id).first()
    if manager is None:
        raise Http404("Manager not found.")
    manager = manager.canonical

    # Traits only read numeric per-season fields; no season join needed.
    all_stats = ManagerSeasonStats.objects.all()
    stats_by_manager: dict[int, list[ManagerSeasonStats]] = defaultdict(list)
    for s in all_stats:
        stats_by_manager[s.manager_id].append(s)

    traits = _scouting_traits(stats_by_manager)
    mine = traits.get(manager.id)
    if mine is None:
        raise Http404("Manager has no computed seasons.")

    qualified = {mid: t for mid, t in traits.items() if t["seasons"] >= SCOUTING_MIN_SEASONS}
    is_qualified = manager.id in qualified

    rows = []
    for key, label, definition, lower_is_better in _TRAIT_META:
        percentile = None
        if is_qualified and len(qualified) > 1:
            values = sorted(t[key] for t in qualified.values())
            below = sum(1 for v in values if v < mine[key])
            ties = sum(1 for v in values if v == mine[key]) - 1
            pct = (below + ties * 0.5) / (len(values) - 1)
            if lower_is_better:
                pct = 1.0 - pct
            percentile = round(pct, 3)
        rows.append(
            {
                "key": key,
                "label": label,
                "definition": definition,
                "value": mine[key],
                "percentile": percentile,
            }
        )

    return {
        "manager": _manager_ref(manager),
        "qualified": is_qualified,
        "min_seasons": SCOUTING_MIN_SEASONS,
        "seasons": mine["seasons"],
        "pool_size": len(qualified),
        "traits": rows,
    }
