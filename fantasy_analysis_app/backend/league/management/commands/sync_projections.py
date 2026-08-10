"""Sync draft-time player projections for the suggester + retrospectives.

    python manage.py sync_projections --source synthetic          # no network
    python manage.py sync_projections --source sleeper --years 2019-2025

The synthetic source derives projections from the league's own realized
seasons so projection analytics work offline. The sleeper source pulls real
frozen preseason projections from Sleeper's keyless API (operator step;
network required; ~1 request per season plus one player-dump request).
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from league.ingestion.projections import (
    SyntheticProjectionSource,
    fetch_sleeper_player_map,
    fetch_sleeper_projections,
    persist_projections,
)
from league.models import League, SyncLog


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
    help = "Sync draft-time player projections from a synthetic or Sleeper source."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--source", choices=["synthetic", "sleeper"], default="synthetic")
        parser.add_argument("--league-id", type=int, default=None)
        parser.add_argument("--years", type=str, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        sync = SyncLog.objects.create(command="sync_projections", years=options["years"] or "")

        if options["source"] == "synthetic":
            league_id = options["league_id"]
            if league_id is None:
                league = League.objects.order_by("id").first()
                if league is None:
                    raise CommandError("No league found. Run load_fixtures or sync_espn first.")
                league_id = league.espn_league_id
            rows = SyntheticProjectionSource().fetch(league_id)
        else:
            years = _parse_years(options["years"])
            if not years:
                raise CommandError("--years is required for the sleeper source (e.g. 2019-2025).")
            self.stdout.write("Fetching Sleeper player map (one large request)...")
            player_map = fetch_sleeper_player_map()
            rows = []
            for year in years:
                rows.extend(fetch_sleeper_projections(year, player_map))
                self.stdout.write(f"  {year}: {len(rows)} rows so far")
                time.sleep(1.0)  # polite pacing; Sleeper asks < 1000 calls/min

        count = persist_projections(rows)
        matched = sum(1 for r in rows if r.espn_player_id)
        sync.status = SyncLog.Status.SUCCESS
        sync.finished_at = timezone.now()
        sync.row_counts = {"projection_rows": count, "espn_id_matched": matched}
        sync.save(update_fields=["status", "finished_at", "row_counts"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {count} projection rows ({options['source']}), {matched} with ESPN ids."
            )
        )
