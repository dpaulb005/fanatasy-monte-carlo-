"""Recompute all analytics for a league (truncate-and-rebuild computed tables).

    python manage.py compute_analytics [--league-id 999999]

Defaults to the synthetic league id when none is given, so it works out of the
box after ``load_fixtures``.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from league.analytics.engine import compute_league
from league.models import League, SyncLog

SYNTHETIC_LEAGUE_ID = 999999


class Command(BaseCommand):
    help = "Recompute analytics (manager/season stats, careers, H2H) for a league."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--league-id", type=int, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        league_id = options["league_id"]
        if league_id is None:
            league = League.objects.order_by("id").first()
            if league is None:
                raise CommandError("No league found. Run load_fixtures or sync_espn first.")
            league_id = league.espn_league_id

        if not League.objects.filter(espn_league_id=league_id).exists():
            raise CommandError(f"League {league_id} not found.")

        sync = SyncLog.objects.create(command="compute_analytics", years=str(league_id))
        counts = compute_league(league_id)
        sync.status = SyncLog.Status.SUCCESS
        sync.finished_at = timezone.now()
        sync.row_counts = counts
        sync.save(update_fields=["status", "finished_at", "row_counts"])

        self.stdout.write(self.style.SUCCESS(f"Computed analytics: {counts}"))
