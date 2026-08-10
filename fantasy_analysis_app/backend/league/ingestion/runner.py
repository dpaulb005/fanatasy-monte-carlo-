"""Sync orchestration: drive a ``LeagueDataSource`` into the database.

Source-agnostic and side-effect-contained so it is testable with a fake source.
Handles incremental skipping (completed seasons are not re-fetched unless
forced) and SyncLog bookkeeping.
"""

from __future__ import annotations

from django.utils import timezone

from league.ingestion.persist import persist_season
from league.ingestion.ports import LeagueDataSource, SeasonRef
from league.models import League, Season, SyncLog


def _already_synced(league: League, year: int) -> bool:
    return Season.objects.filter(league=league, year=year, is_complete=True).exists()


def run_sync(
    source: LeagueDataSource,
    league_id: int,
    league_name: str = "",
    years: list[int] | None = None,
    *,
    force: bool = False,
    command: str = "sync_espn",
) -> SyncLog:
    """Fetch and persist the requested years from ``source``.

    Completed seasons are skipped unless ``force``. Returns the SyncLog with
    per-run row counts.
    """
    target_years = sorted(years if years is not None else source.available_years())
    sync = SyncLog.objects.create(command=command, years=",".join(map(str, target_years)))

    league, _ = League.objects.get_or_create(
        espn_league_id=league_id,
        defaults={"name": league_name or f"League {league_id}"},
    )

    totals: dict[str, int] = {"seasons": 0, "skipped": 0}
    try:
        for year in target_years:
            if not force and _already_synced(league, year):
                totals["skipped"] += 1
                continue
            bundle = source.fetch_season(SeasonRef(league_id=league_id, year=year))
            counts = persist_season(league, bundle)
            totals["seasons"] += 1
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
    except Exception as exc:  # noqa: BLE001 - record failure on the SyncLog
        sync.status = SyncLog.Status.FAILED
        sync.finished_at = timezone.now()
        sync.message = f"{type(exc).__name__}: {exc}"
        sync.row_counts = totals
        sync.save(update_fields=["status", "finished_at", "message", "row_counts"])
        raise

    sync.status = SyncLog.Status.SUCCESS
    sync.finished_at = timezone.now()
    sync.row_counts = totals
    sync.save(update_fields=["status", "finished_at", "row_counts"])
    return sync
