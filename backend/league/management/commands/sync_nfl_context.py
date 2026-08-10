"""Sync public NFL context (ADP) for draft analytics.

    python manage.py sync_nfl_context --source synthetic   # no network
    python manage.py sync_nfl_context --source ffc --years 2019-2023

The synthetic source derives ADP from the league's own drafts so draft
steal/reach analytics work offline. The ffc source pulls real historical ADP
from FantasyFootballCalculator (network required; operator step).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from league.ingestion.nfl_context import (
    SyntheticADPSource,
    fetch_ffc_adp,
    persist_adp,
)
from league.models import League, SyncLog

SYNTHETIC_LEAGUE_ID = 999999


def _parse_years(spec: str | None) -> list[int]:
    if not spec:
        return []
    years: list[int] = []
    for part in spec.replace(",", " ").split():
        if "-" in part:
            start, end = part.split("-", 1)
            years.extend(range(int(start), int(end) + 1))
        else:
            years.append(int(part))
    return sorted(set(years))


class Command(BaseCommand):
    help = "Sync public NFL context (ADP) from a synthetic or FFC source."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source", choices=["synthetic", "ffc"], default="synthetic")
        parser.add_argument("--league-id", type=int, default=None)
        parser.add_argument("--years", type=str, default=None)
        parser.add_argument("--format", type=str, default="standard")

    def handle(self, *args: Any, **options: Any) -> None:
        sync = SyncLog.objects.create(command="sync_nfl_context", years=options["years"] or "")

        if options["source"] == "synthetic":
            league_id = options["league_id"]
            if league_id is None:
                league = League.objects.order_by("id").first()
                if league is None:
                    raise CommandError("No league found. Run load_fixtures or sync_espn first.")
                league_id = league.espn_league_id
            rows = SyntheticADPSource().fetch(league_id)
        else:
            years = _parse_years(options["years"])
            if not years:
                raise CommandError("--years is required for the ffc source (e.g. 2019-2023).")
            rows = []
            for year in years:
                rows.extend(fetch_ffc_adp(year, fmt=options["format"]))

        count = persist_adp(rows)
        sync.status = SyncLog.Status.SUCCESS
        sync.finished_at = timezone.now()
        sync.row_counts = {"adp_rows": count}
        sync.save(update_fields=["status", "finished_at", "row_counts"])

        self.stdout.write(self.style.SUCCESS(f"Synced {count} ADP rows ({options['source']})."))
