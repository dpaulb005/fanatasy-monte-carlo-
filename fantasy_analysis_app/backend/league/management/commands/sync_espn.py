"""Sync ESPN league history into the database.

    python manage.py sync_espn --years 2019-2023
    python manage.py sync_espn --current-only
    python manage.py sync_espn --source synthetic     # no credentials needed

Real ESPN sync requires ESPN_LEAGUE_ID / ESPN_S2 / ESPN_SWID in the environment
(see docs/DATA_SOURCES.md). The synthetic source lets the same pipeline run
credential-free for development.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from league.ingestion.espn_source import EspnApiSource
from league.ingestion.ports import LeagueDataSource
from league.ingestion.runner import run_sync
from league.ingestion.synthetic import DEFAULT_SEASONS
from league.ingestion.synthetic_source import SyntheticSource

SYNTHETIC_LEAGUE_ID = 999999


def _parse_years(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    years: list[int] = []
    for part in spec.replace(",", " ").split():
        if "-" in part:
            start, end = part.split("-", 1)
            years.extend(range(int(start), int(end) + 1))
        else:
            years.append(int(part))
    return sorted(set(years))


class Command(BaseCommand):
    help = "Sync ESPN league history (or a synthetic league) into the database."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--years", type=str, default=None, help="e.g. 2019-2023 or '2019 2021'")
        parser.add_argument("--source", choices=["espn", "synthetic"], default="espn")
        parser.add_argument("--current-only", action="store_true", help="Only the latest year")
        parser.add_argument("--force", action="store_true", help="Re-sync completed seasons")

    def handle(self, *args: Any, **options: Any) -> None:
        years = _parse_years(options["years"])

        if options["source"] == "synthetic":
            source: LeagueDataSource = SyntheticSource(years)
            league_id = SYNTHETIC_LEAGUE_ID
            league_name = "The Synthetic League (fixtures)"
        else:
            league_id = int(getattr(settings, "ESPN_LEAGUE_ID", 0) or 0)
            if not league_id:
                raise CommandError(
                    "ESPN_LEAGUE_ID is not set. Configure ESPN credentials in .env "
                    "(see docs/DATA_SOURCES.md) or run with --source synthetic."
                )
            source = EspnApiSource(
                league_id=league_id,
                espn_s2=getattr(settings, "ESPN_S2", ""),
                swid=getattr(settings, "ESPN_SWID", ""),
                years=years or [],
            )
            league_name = ""

        effective_years = years or source.available_years()
        if options["current_only"] and effective_years:
            effective_years = [max(effective_years)]
        if not effective_years:
            effective_years = DEFAULT_SEASONS if options["source"] == "synthetic" else []
        if not effective_years:
            raise CommandError("No years to sync. Pass --years or set ESPN_START_YEAR.")

        sync = run_sync(
            source,
            league_id=league_id,
            league_name=league_name,
            years=effective_years,
            force=options["force"],
        )
        self.stdout.write(self.style.SUCCESS(f"Sync {sync.status}: {sync.row_counts}"))
