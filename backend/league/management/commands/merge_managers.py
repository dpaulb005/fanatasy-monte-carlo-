"""Merge a duplicate Manager (second ESPN account) into a canonical one.

    python manage.py merge_managers <source_id> <target_id>
    python manage.py merge_managers --unmerge <source_id>

Operator-only identity continuity (backlog I-1): never run automatically and
never inferred from names. The merge is a pointer (`Manager.merged_into`) —
source data (TeamSeason.managers M2M) is not rewritten, and analytics resolve
the pointer at compute time, so a merge is fully reversible with --unmerge.
Run `compute_analytics` afterwards; this command reminds you.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from league.identity import merge_error
from league.models import Manager


class Command(BaseCommand):
    help = "Merge a duplicate manager account into its canonical manager (reversible)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("source_id", type=int, help="Manager id to merge away")
        parser.add_argument(
            "target_id",
            type=int,
            nargs="?",
            default=None,
            help="Canonical manager id to merge into",
        )
        parser.add_argument(
            "--unmerge",
            action="store_true",
            help="Clear source's merged_into pointer instead of setting one",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        source = self._get(options["source_id"])

        if options["unmerge"]:
            previous = source.merged_into
            if previous is None:
                raise CommandError(f"Manager {source.id} ({source.label}) is not merged.")
            source.merged_into = None
            source.save(update_fields=["merged_into"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Unmerged {source.label} (id {source.id}) from "
                    f"{previous.label} (id {previous.id})."
                )
            )
            self._remind()
            return

        if options["target_id"] is None:
            raise CommandError("target_id is required unless --unmerge is given.")
        target = self._get(options["target_id"])

        if source.merged_into_id is not None:
            raise CommandError(
                f"Source {source.label} (id {source.id}) is already merged into "
                f"manager {source.merged_into_id}; --unmerge first to change it."
            )
        error = merge_error(source, target)
        if error:
            raise CommandError(error)

        source.merged_into = target
        source.save(update_fields=["merged_into"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Merged {source.label} (id {source.id}, {source.guid}) into "
                f"{target.label} (id {target.id}, {target.guid})."
            )
        )
        self._remind()

    def _get(self, manager_id: int) -> Manager:
        try:
            return Manager.objects.get(id=manager_id)
        except Manager.DoesNotExist as exc:
            raise CommandError(f"Manager {manager_id} does not exist.") from exc

    def _remind(self) -> None:
        self.stdout.write(
            "Now rebuild analytics so careers/H2H/player attributions reflect it:\n"
            "  python manage.py compute_analytics"
        )
