"""Import a versioned nflsim application snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from league.models import SimulationSnapshot

SCHEMA = "nflsim.application-snapshot"
SUPPORTED_VERSION = 1


class Command(BaseCommand):
    help = "Import an nflsim app-export JSON snapshot"

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path)

    def handle(self, *args, **options):
        path: Path = options["path"]
        try:
            raw = path.read_bytes()
            payload = json.loads(
                raw, parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite number {value}")
                ),
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise CommandError(f"cannot read a strict JSON snapshot: {exc}") from exc

        model = payload.get("model") or {}
        if payload.get("schema") != SCHEMA:
            raise CommandError(f"unsupported snapshot schema: {payload.get('schema')!r}")
        if payload.get("schema_version") != SUPPORTED_VERSION:
            raise CommandError(f"unsupported schema version: {payload.get('schema_version')!r}")
        if not isinstance(payload.get("players"), list) or not isinstance(
            payload.get("pairs"), list
        ):
            raise CommandError("snapshot players and pairs must be lists")

        generated_at = parse_datetime(str(payload.get("generated_at", "")))
        scoring = model.get("scoring") or {}
        league = model.get("league") or {}
        required = (model.get("season"), model.get("simulations"), league.get("teams"))
        if generated_at is None or any(value is None for value in required):
            raise CommandError("snapshot is missing required model provenance")

        names = [row.get("player") for row in payload["players"]]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise CommandError("snapshot player names must be present and unique")

        checksum = hashlib.sha256(raw).hexdigest()
        row, created = SimulationSnapshot.objects.update_or_create(
            source="nflsim",
            season=int(model["season"]),
            scoring=str(scoring.get("name") or "custom"),
            league_teams=int(league["teams"]),
            defaults={
                "schema_version": SUPPORTED_VERSION,
                "simulations": int(model["simulations"]),
                "generated_at": generated_at,
                "checksum": checksum,
                "payload": payload,
            },
        )
        verb = "Imported" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {len(names)} players and {len(payload['pairs'])} joint pairs "
            f"from {model['simulations']:,} simulated seasons (snapshot {row.id})."
        ))
