"""Idempotent persistence of a normalized ``SeasonBundle`` into the ORM.

Keyed on natural keys so re-running a sync updates in place rather than
duplicating. One ``transaction.atomic()`` per season. Source-agnostic: ESPN,
fixtures, and synthetic data all flow through here.
"""

from __future__ import annotations

from django.db import transaction

from league.ingestion.schemas import PlayerRef, SeasonBundle
from league.models import (
    DraftPick,
    League,
    LineupSlot,
    Manager,
    Matchup,
    Player,
    Season,
    TeamSeason,
)


def _upsert_player(ref: PlayerRef, cache: dict[int, Player]) -> Player:
    """Upsert a player once per persist call.

    A player appears in many lineup slots (once per week) and possibly a draft
    pick, so caching by espn_player_id collapses ~2000 round-trips per season to
    one per unique player.
    """
    cached = cache.get(ref.espn_player_id)
    if cached is not None:
        # Draft rows carry no position; backfill it when a later ref (e.g. a
        # lineup slot) knows it, so drafted players don't end up positionless.
        if ref.position and not cached.position:
            cached.position = ref.position
            cached.save(update_fields=["position"])
        return cached
    player, created = Player.objects.get_or_create(
        espn_player_id=ref.espn_player_id,
        defaults={"name": ref.name, "position": ref.position, "gsis_id": ref.gsis_id},
    )
    if not created:
        # Refresh with the latest non-empty values; never clobber good data
        # with the blanks some sources (draft picks) legitimately carry.
        fields: list[str] = []
        for attr in ("name", "position", "gsis_id"):
            value = getattr(ref, attr)
            if value and getattr(player, attr) != value:
                setattr(player, attr, value)
                fields.append(attr)
        if fields:
            player.save(update_fields=fields)
    cache[ref.espn_player_id] = player
    return player


@transaction.atomic
def persist_season(league: League, bundle: SeasonBundle) -> dict[str, int]:
    """Persist one season bundle idempotently. Returns row counts."""

    # The bundle carries the league's display name (from ESPN settings); the
    # League row is created before any season is fetched, so refresh it here.
    league_name = str((bundle.scoring_settings or {}).get("name") or "").strip()
    if league_name and league.name != league_name:
        league.name = league_name
        league.save(update_fields=["name"])

    season, _ = Season.objects.update_or_create(
        league=league,
        year=bundle.year,
        defaults={
            "scoring_settings": bundle.scoring_settings,
            "roster_slots": bundle.roster_slots,
            "regular_season_weeks": bundle.regular_season_weeks,
            "playoff_team_count": bundle.playoff_team_count,
            "is_complete": bundle.is_complete,
            "lineups_available": bundle.lineups_available,
        },
    )

    managers_by_guid: dict[str, Manager] = {}
    for manager_ref in bundle.managers:
        manager, _ = Manager.objects.get_or_create(
            guid=manager_ref.guid,
            defaults={"display_name": manager_ref.display_name},
        )
        # Refresh the display name to the latest seen, but never clobber an
        # operator-set real_name alias.
        if manager_ref.display_name and manager.display_name != manager_ref.display_name:
            manager.display_name = manager_ref.display_name
            manager.save(update_fields=["display_name"])
        managers_by_guid[manager_ref.guid] = manager

    player_cache: dict[int, Player] = {}
    teams_by_espn_id: dict[int, TeamSeason] = {}
    for team_row in bundle.teams:
        team_season, _ = TeamSeason.objects.update_or_create(
            season=season,
            espn_team_id=team_row.espn_team_id,
            defaults={
                "team_name": team_row.team_name,
                "abbrev": team_row.abbrev,
                "division": team_row.division,
                "wins": team_row.wins,
                "losses": team_row.losses,
                "ties": team_row.ties,
                "points_for": team_row.points_for,
                "points_against": team_row.points_against,
                "final_standing": team_row.final_standing,
                "made_playoffs": team_row.made_playoffs,
            },
        )
        owners = [managers_by_guid[g] for g in team_row.owner_guids if g in managers_by_guid]
        team_season.managers.set(owners)
        teams_by_espn_id[team_row.espn_team_id] = team_season

    # Draft
    DraftPick.objects.filter(season=season).delete()
    draft_objs = []
    for pick in bundle.draft:
        player = _upsert_player(pick.player, player_cache)
        draft_objs.append(
            DraftPick(
                season=season,
                team_season=teams_by_espn_id[pick.team_espn_id],
                player=player,
                round=pick.round,
                round_pick=pick.round_pick,
                overall_pick=pick.overall_pick,
                is_keeper=pick.is_keeper,
                auction_price=pick.auction_price,
            )
        )
    DraftPick.objects.bulk_create(draft_objs)

    # Matchups
    Matchup.objects.filter(season=season).delete()
    matchup_objs = []
    for game in bundle.matchups:
        away = teams_by_espn_id.get(game.away_espn_id) if game.away_espn_id else None
        matchup_objs.append(
            Matchup(
                season=season,
                week=game.week,
                home=teams_by_espn_id[game.home_espn_id],
                away=away,
                home_score=game.home_score,
                away_score=game.away_score,
                kind=game.kind,
                is_bye=game.is_bye,
            )
        )
    Matchup.objects.bulk_create(matchup_objs)

    # Lineups (bulk upsert on the high-volume table)
    LineupSlot.objects.filter(team_season__season=season).delete()
    lineup_objs = []
    for slot in bundle.lineups:
        player = _upsert_player(slot.player, player_cache)
        lineup_objs.append(
            LineupSlot(
                team_season=teams_by_espn_id[slot.team_espn_id],
                week=slot.week,
                player=player,
                slot=slot.slot,
                points=slot.points,
                projected_points=slot.projected_points,
            )
        )
    LineupSlot.objects.bulk_create(lineup_objs)

    return {
        "managers": len(bundle.managers),
        "teams": len(bundle.teams),
        "draft_picks": len(draft_objs),
        "matchups": len(matchup_objs),
        "lineup_slots": len(lineup_objs),
    }
