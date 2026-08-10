"""Provenance & sync bookkeeping.

``SyncLog`` records each ingestion run (powering incremental sync and a status
endpoint). ``RawSourcePayload`` stores the raw source JSON keyed by request so
parsing can be re-run offline and completed seasons are fetched only once.
"""

from __future__ import annotations

from django.db import models


class SyncLog(models.Model):
    """One ingestion run of a management command."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    command = models.CharField(max_length=64)
    years = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    row_counts = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.command} [{self.status}] {self.started_at:%Y-%m-%d}"


class RawSourcePayload(models.Model):
    """Raw source JSON captured before parsing, for provenance and re-processing.

    Keyed by the logical request tuple. Immutable completed-season data is
    fetched once and re-parsed from here. May contain personal data — never
    exposed via the API; excluded from public output.
    """

    source = models.CharField(max_length=32, default="espn")
    league_id = models.BigIntegerField(default=0)
    year = models.PositiveIntegerField(default=0)
    view = models.CharField(max_length=64, blank=True)
    scoring_period = models.PositiveSmallIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "league_id", "year", "view", "scoring_period"],
                name="uniq_raw_payload",
            ),
        ]
        indexes = [models.Index(fields=["league_id", "year"])]

    def __str__(self) -> str:
        return f"{self.source} {self.year} {self.view} sp={self.scoring_period}"
