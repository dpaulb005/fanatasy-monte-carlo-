"""Analytics orchestration: compute all metrics and rebuild computed tables.

Loads frames once, runs the metric modules, and truncate-and-rebuilds the
computed tables in one transaction. Computed tables are pure derivations, so a
full rebuild is always safe. See docs/METRICS_CATALOG.md.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q

from league.analytics.awards import compute_awards
from league.analytics.draft_patterns import compute_draft_patterns
from league.analytics.draft_priors import compute_draft_priors
from league.analytics.drafts import compute_draft_values, normalize_player_name
from league.analytics.frames import LeagueFrames, load_frames
from league.analytics.h2h import compute_h2h
from league.analytics.lineups import week_efficiency
from league.analytics.luck import all_play_for_team, points_against_percentile
from league.analytics.museum import compute_museum
from league.analytics.players import compute_player_values
from league.analytics.records import longest_streaks, stddev
from league.analytics.trends import compute_season_fingerprints, compute_trends
from league.models import (
    Award,
    DraftPickValue,
    HeadToHeadRecord,
    League,
    ManagerCareerStats,
    ManagerSeasonStats,
    Player,
    PlayerADP,
    PlayerManagerSeasonValue,
    PlayerProjection,
    PlayerSeasonValue,
    Season,
    SeasonTrend,
    TeamSeason,
)

CACHE_VERSION_KEY = "analytics:version"


def _team_manager_season_rows(frames: LeagueFrames) -> list[dict]:
    """One row per (manager, team-season) with all per-season metrics."""
    # Group team-weeks by team-season for weekly score series and W/L.
    weeks_by_team: dict[int, list] = defaultdict(list)
    for tw in frames.team_weeks:
        if tw.kind == "REG":
            weeks_by_team[tw.team_season_id].append(tw)

    # Points-against per team, per season, for percentile.
    pa_by_year: dict[int, dict[int, float]] = defaultdict(dict)
    for ts_id, tsf in frames.team_seasons.items():
        pa_by_year[tsf.season_year][ts_id] = tsf.points_against

    rows: list[dict] = []
    for ts_id, tsf in frames.team_seasons.items():
        scores_by_week = frames.scores_by_week.get(tsf.season_year, {})
        ap = all_play_for_team(scores_by_week, ts_id)
        wins = sum(1 for tw in weeks_by_team[ts_id] if tw.won)
        losses = sum(1 for tw in weeks_by_team[ts_id] if tw.lost)
        ties = sum(1 for tw in weeks_by_team[ts_id] if tw.tied)
        weekly_scores = [tw.score for tw in weeks_by_team[ts_id]]

        # Lineup efficiency across the season (only if rosters are present).
        opt_total = act_total = bench_total = 0.0
        optimal_by_week: dict[int, float] = {}
        for week, roster in tsf.roster_by_week.items():
            actual, optimal, bench = week_efficiency(roster)
            act_total += actual
            opt_total += optimal
            bench_total += bench
            optimal_by_week[week] = optimal
        efficiency = round(act_total / opt_total, 4) if opt_total else 0.0

        # Games lost on the bench: losses where the best LEGAL lineup from the
        # roster that week (optimal_points respects slot eligibility) would
        # have beaten the opponent's actual score. Never "sum of bench points"
        # — only weeks where a real alternate lineup flips the result count.
        # Requires lineup data; eras without rosters contribute zero.
        bench_losses = 0
        bench_loss_weeks: list[dict] = []
        for tw in weeks_by_team[ts_id]:
            week_optimal = optimal_by_week.get(tw.week)
            if tw.lost and week_optimal is not None and week_optimal > tw.opponent_score:
                bench_losses += 1
                bench_loss_weeks.append(
                    {
                        "week": tw.week,
                        "score": round(tw.score, 2),
                        "optimal": round(week_optimal, 2),
                        "opponent_score": round(tw.opponent_score, 2),
                    }
                )
        bench_loss_weeks.sort(key=lambda w: w["week"])

        luck_delta = round(wins - ap.expected_wins, 3)
        pa_pct = points_against_percentile(ts_id, pa_by_year[tsf.season_year])

        for manager_id in tsf.manager_ids:
            rows.append(
                {
                    "manager_id": manager_id,
                    "season_year": tsf.season_year,
                    "team_season_id": ts_id,
                    "wins": wins,
                    "losses": losses,
                    "ties": ties,
                    "points_for": tsf.points_for,
                    "points_against": tsf.points_against,
                    "all_play_wins": round(ap.all_play_wins, 3),
                    "all_play_games": round(ap.all_play_games, 3),
                    "expected_wins": round(ap.expected_wins, 3),
                    "luck_delta": luck_delta,
                    "points_against_percentile": round(pa_pct, 4),
                    "weekly_score_stddev": stddev(weekly_scores),
                    "optimal_points": round(opt_total, 2),
                    "bench_points_lost": round(bench_total, 2),
                    "lineup_efficiency": efficiency,
                    "bench_losses": bench_losses,
                    "bench_loss_weeks": bench_loss_weeks,
                    "final_standing": tsf.final_standing,
                    "made_playoffs": tsf.made_playoffs,
                }
            )
    return rows


def _career_rows(frames: LeagueFrames, season_rows: list[dict]) -> dict[int, dict]:
    by_manager: dict[int, dict] = {}
    # Chronological outcomes per manager for streaks.
    games_by_manager: dict[int, list] = defaultdict(list)
    team_to_managers = {ts_id: tsf.manager_ids for ts_id, tsf in frames.team_seasons.items()}
    ordered = sorted(frames.team_weeks, key=lambda tw: (tw.season_year, tw.week))
    for tw in ordered:
        outcome = "W" if tw.won else "L" if tw.lost else "T"
        for manager_id in team_to_managers.get(tw.team_season_id, []):
            games_by_manager[manager_id].append(outcome)

    team_count_by_year = frames.team_count_by_year
    for row in season_rows:
        mid = row["manager_id"]
        agg = by_manager.setdefault(
            mid,
            {
                "seasons_played": 0,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "championships": 0,
                "playoff_appearances": 0,
                "sackos": 0,
                "total_points_for": 0.0,
                "total_luck_delta": 0.0,
            },
        )
        agg["seasons_played"] += 1
        agg["wins"] += row["wins"]
        agg["losses"] += row["losses"]
        agg["ties"] += row["ties"]
        agg["total_points_for"] += row["points_for"]
        agg["total_luck_delta"] += row["luck_delta"]
        if row["made_playoffs"]:
            agg["playoff_appearances"] += 1
        if row["final_standing"] == 1:
            agg["championships"] += 1
        if row["final_standing"] == team_count_by_year.get(row["season_year"], 0):
            agg["sackos"] += 1

    for mid, agg in by_manager.items():
        streak = longest_streaks(games_by_manager.get(mid, []))
        agg["longest_win_streak"] = streak.longest_win_streak
        agg["longest_lose_streak"] = streak.longest_lose_streak
        agg["total_points_for"] = round(agg["total_points_for"], 2)
        agg["total_luck_delta"] = round(agg["total_luck_delta"], 3)
    return by_manager


@transaction.atomic
def compute_league(league_id: int) -> dict[str, int]:
    frames = load_frames(league_id)

    season_rows = _team_manager_season_rows(frames)
    career = _career_rows(frames, season_rows)
    h2h = compute_h2h(frames)
    trends = compute_trends(frames)

    adp_lookup = {
        (a.season, normalize_player_name(a.player_name)): a.adp
        for a in PlayerADP.objects.filter(season__in=frames.team_count_by_year)
    }
    draft_values = compute_draft_values(frames, adp_lookup)
    projections = list(PlayerProjection.objects.filter(week=0))
    draft_priors = compute_draft_priors(frames, draft_values, projections=projections)
    projection_error = draft_priors.get("projection_error") or {}
    draft_patterns = compute_draft_patterns(
        frames,
        draft_values,
        projections=projections,
        projection_scale=projection_error.get("scale", "pts_ppr"),
    )
    awards = compute_awards(frames, season_rows, draft_values)
    player_season_values, player_manager_values = compute_player_values(frames)

    # Rebuild computed tables for this league.
    league = League.objects.get(espn_league_id=league_id)
    season_ids = list(Season.objects.filter(league=league).values_list("id", flat=True))
    # Purge scope must cover managers no longer present in frames (e.g. a
    # source account merged into its canonical row since the last compute),
    # so derive it from the raw team-season links, not the resolved frames.
    manager_ids = set(
        TeamSeason.objects.filter(season_id__in=season_ids).values_list("managers", flat=True)
    ) | {mid for tsf in frames.team_seasons.values() for mid in tsf.manager_ids}
    manager_ids.discard(None)

    ManagerSeasonStats.objects.filter(season_id__in=season_ids).delete()
    ManagerCareerStats.objects.filter(manager_id__in=manager_ids).delete()
    HeadToHeadRecord.objects.filter(
        Q(manager_a_id__in=manager_ids) | Q(manager_b_id__in=manager_ids)
    ).delete()

    season_by_year = {s.year: s for s in Season.objects.filter(league=league)}
    season_stat_objs = [
        ManagerSeasonStats(
            manager_id=row["manager_id"],
            season=season_by_year[row["season_year"]],
            team_season_id=row["team_season_id"],
            wins=row["wins"],
            losses=row["losses"],
            ties=row["ties"],
            points_for=row["points_for"],
            points_against=row["points_against"],
            all_play_wins=row["all_play_wins"],
            all_play_games=row["all_play_games"],
            expected_wins=row["expected_wins"],
            luck_delta=row["luck_delta"],
            points_against_percentile=row["points_against_percentile"],
            weekly_score_stddev=row["weekly_score_stddev"],
            optimal_points=row["optimal_points"],
            bench_points_lost=row["bench_points_lost"],
            lineup_efficiency=row["lineup_efficiency"],
            bench_losses=row["bench_losses"],
            final_standing=row["final_standing"],
            made_playoffs=row["made_playoffs"],
        )
        for row in season_rows
    ]
    ManagerSeasonStats.objects.bulk_create(season_stat_objs)

    ManagerCareerStats.objects.bulk_create(
        [ManagerCareerStats(manager_id=mid, **agg) for mid, agg in career.items()]
    )

    HeadToHeadRecord.objects.bulk_create(
        [
            HeadToHeadRecord(
                manager_a_id=a,
                manager_b_id=b,
                a_wins=rec.a_wins,
                b_wins=rec.b_wins,
                ties=rec.ties,
                a_points=round(rec.a_points, 2),
                b_points=round(rec.b_points, 2),
                playoff_meetings=rec.playoff_meetings,
                largest_margin=round(rec.largest_margin, 2),
            )
            for (a, b), rec in h2h.pairs.items()
        ]
    )

    # Trend blobs: league-wide (season=None) + per-season fingerprints.
    # Rebuild in full. The Museum of Pain rides along as one more blob — no
    # schema, one more exhibit is one more entry in compute_museum.
    museum = compute_museum(frames, career)
    fingerprints = compute_season_fingerprints(frames)
    SeasonTrend.objects.filter(Q(season__isnull=True) | Q(season_id__in=season_ids)).delete()
    SeasonTrend.objects.bulk_create(
        [SeasonTrend(season=None, key=key, data=data) for key, data in trends.items()]
        + [SeasonTrend(season=None, key="museum_of_pain", data=museum)]
        + [SeasonTrend(season=None, key="draft_patterns", data=draft_patterns)]
        + [SeasonTrend(season=None, key="draft_priors", data=draft_priors)]
        + [
            SeasonTrend(season=season_by_year[year], key="weekly_fingerprints", data=blob)
            for year, blob in fingerprints.items()
            if year in season_by_year
        ]
    )

    # Draft pick values.
    DraftPickValue.objects.filter(draft_pick__season_id__in=season_ids).delete()
    DraftPickValue.objects.bulk_create(
        [
            DraftPickValue(
                draft_pick_id=row.draft_pick_id,
                season_points=row.season_points,
                points_over_replacement=row.points_over_replacement,
                adp=row.adp,
                adp_delta=row.adp_delta,
                round_expectation_delta=row.round_expectation_delta,
            )
            for row in draft_values
        ]
    )

    # Awards (per-season + all-time). Rebuild in full.
    Award.objects.filter(season_id__in=season_ids).delete()
    Award.objects.filter(season__isnull=True).delete()
    Award.objects.bulk_create(
        [
            Award(
                season=season_by_year.get(a.season_year) if a.season_year else None,
                slug=a.slug,
                title=a.title,
                winner_id=a.winner_manager_id,
                value=a.value,
                context=a.context,
            )
            for a in awards
        ]
    )

    # Player values (season + manager-attributed). Rebuild in full.
    PlayerSeasonValue.objects.filter(season_id__in=season_ids).delete()
    PlayerManagerSeasonValue.objects.filter(season_id__in=season_ids).delete()
    espn_ids = {row.espn_player_id for row in player_season_values}
    player_id_by_espn = dict(
        Player.objects.filter(espn_player_id__in=espn_ids).values_list("espn_player_id", "id")
    )
    PlayerSeasonValue.objects.bulk_create(
        [
            PlayerSeasonValue(
                player_id=player_id_by_espn[row.espn_player_id],
                season=season_by_year[row.season_year],
                position=row.position,
                total_points=row.total_points,
                started_points=row.started_points,
                bench_points=row.bench_points,
                weeks_rostered=row.weeks_rostered,
                weeks_started=row.weeks_started,
                points_over_replacement=row.points_over_replacement,
                position_rank=row.position_rank,
            )
            for row in player_season_values
        ]
    )
    PlayerManagerSeasonValue.objects.bulk_create(
        [
            PlayerManagerSeasonValue(
                player_id=player_id_by_espn[row.espn_player_id],
                manager_id=row.manager_id,
                season=season_by_year[row.season_year],
                total_points=row.total_points,
                started_points=row.started_points,
                bench_points=row.bench_points,
                weeks_rostered=row.weeks_rostered,
                weeks_started=row.weeks_started,
            )
            for row in player_manager_values
        ]
    )

    _bump_cache_version()

    return {
        "manager_seasons": len(season_stat_objs),
        "careers": len(career),
        "h2h_pairs": len(h2h.pairs),
        "trends": len(trends),
        "draft_values": len(draft_values),
        # ADP join health: how many picks resolved a public ADP. Surfaced by
        # compute_analytics so name-matching regressions are visible per run.
        "draft_adp_matched": sum(1 for row in draft_values if row.adp is not None),
        "draft_pattern_managers": len(draft_patterns["managers"]),
        "draft_prior_positions": len(draft_priors["value_bands"]),
        "awards": len(awards),
        "player_seasons": len(player_season_values),
        "player_manager_seasons": len(player_manager_values),
    }


def _bump_cache_version() -> None:
    try:
        cache.incr(CACHE_VERSION_KEY)
    except ValueError:
        cache.set(CACHE_VERSION_KEY, 1)


def cache_version() -> int:
    return cache.get(CACHE_VERSION_KEY, 1)
