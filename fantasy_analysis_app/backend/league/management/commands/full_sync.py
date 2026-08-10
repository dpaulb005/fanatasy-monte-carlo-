"""Run the full pipeline: sync the current season then recompute analytics.

    python manage.py full_sync [--source synthetic]

Intended for a weekly in-season cron. For a synthetic demo it loads all
fixtures then computes. No Celery/Redis — this is a plain command (ADR-003).
"""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

SYNTHETIC_LEAGUE_ID = 999999


class Command(BaseCommand):
    help = "Sync (current season) then recompute analytics."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source", choices=["espn", "synthetic"], default="espn")
        parser.add_argument("--current-only", action="store_true", default=True)

    def handle(self, *args: Any, **options: Any) -> None:
        source = options["source"]
        if source == "synthetic":
            call_command("sync_espn", source="synthetic")
            call_command("sync_nfl_context", source="synthetic", league_id=SYNTHETIC_LEAGUE_ID)
            call_command("compute_analytics", league_id=SYNTHETIC_LEAGUE_ID)
        else:
            call_command("sync_espn", current_only=options["current_only"])
            call_command("sync_nfl_context", source="synthetic")
            call_command("compute_analytics")
        self.stdout.write(self.style.SUCCESS("full_sync complete"))
