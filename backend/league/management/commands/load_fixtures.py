"""Load the deterministic synthetic league for credential-free dev and tests.

Usage:
    python manage.py load_fixtures [--years 2019 2020 ...] [--reset]

Idempotent: re-running updates in place. ``--reset`` clears the synthetic
league first for a clean slate.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from league.ingestion.persist import persist_season
from league.ingestion.synthetic import DEFAULT_SEASONS, generate_league
from league.models import League, SyncLog

SYNTHETIC_LEAGUE_ID = 999999


class Command(BaseCommand):
    help = "Load a deterministic synthetic multi-season league (no ESPN needed)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--years", nargs="*", type=int, default=None)
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        years = options["years"] or DEFAULT_SEASONS
        sync = SyncLog.objects.create(command="load_fixtures", years=",".join(map(str, years)))

        if options["reset"]:
            League.objects.filter(espn_league_id=SYNTHETIC_LEAGUE_ID).delete()

        league, _ = League.objects.get_or_create(
            espn_league_id=SYNTHETIC_LEAGUE_ID,
            defaults={"name": "The Synthetic League (fixtures)"},
        )

        totals: dict[str, int] = {}
        for bundle in generate_league(years):
            counts = persist_season(league, bundle)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
            self.stdout.write(f"  {bundle.year}: {counts}")

        sync.status = SyncLog.Status.SUCCESS
        sync.finished_at = timezone.now()
        sync.row_counts = totals
        sync.save(update_fields=["status", "finished_at", "row_counts"])

        self.stdout.write(self.style.SUCCESS(f"Loaded synthetic league: {totals}"))
