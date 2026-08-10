"""Load expert cheat-sheet JSON fixtures into ExpertRanking.

    python manage.py load_expert_ranks
    python manage.py load_expert_ranks --dir path/to/jsons

Fixtures are produced by parsing operator-supplied PDFs (see
league/fixtures/expert_ranks/). Each file: {source, season, adp_teams?,
players: [{name, position, team, tier, rank_overall?, rank_pos?, adp_text?,
consensus_adp?, espn_rank?, risk?, upside?}]}. Rows replace wholesale per
(source, season).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from league.models import ExpertRanking

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "expert_ranks"


def _adp_overall(entry: dict, teams: int) -> float | None:
    """Overall pick number from either an explicit value or 'round.pick' text."""
    if entry.get("consensus_adp") is not None:
        return float(entry["consensus_adp"])
    text = entry.get("adp_text")
    if not text:
        return None
    try:
        rnd, pick = text.split(".")
        return (int(rnd) - 1) * teams + int(pick)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Load expert cheat-sheet JSON fixtures into ExpertRanking."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dir", type=str, default=str(DEFAULT_DIR))

    def handle(self, *args: Any, **options: Any) -> None:
        directory = Path(options["dir"])
        files = sorted(directory.glob("*.json"))
        if not files:
            raise CommandError(f"No JSON fixtures in {directory}")

        total = 0
        for path in files:
            data = json.loads(path.read_text())
            source = data["source"]
            season = int(data["season"])
            teams = int(data.get("adp_teams") or 12)
            rows = []
            seen: set[tuple[str, str]] = set()
            for p in data.get("players", []):
                key = (p.get("position") or "", p["name"])
                if key in seen:  # defensive: sheets occasionally repeat rows
                    continue
                seen.add(key)
                rows.append(
                    ExpertRanking(
                        source=source,
                        season=season,
                        player_name=p["name"],
                        position=p.get("position") or "",
                        team=p.get("team") or "",
                        rank_overall=p.get("rank_overall"),
                        rank_pos=p.get("rank_pos"),
                        tier=str(p["tier"]) if p.get("tier") is not None else "",
                        adp_overall=_adp_overall(p, teams),
                        espn_rank=p.get("espn_rank"),
                        risk=p.get("risk"),
                        upside=p.get("upside"),
                    )
                )
            ExpertRanking.objects.filter(source=source, season=season).delete()
            ExpertRanking.objects.bulk_create(rows)
            total += len(rows)
            self.stdout.write(f"  {path.name}: {len(rows)} rows ({source} {season})")

        self.stdout.write(self.style.SUCCESS(f"Loaded {total} expert ranking rows."))
