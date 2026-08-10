"""Projection ingestion tests (synthetic path — network never touched)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from league.ingestion.projections import SyntheticProjectionSource, persist_projections
from league.models import PlayerProjection, SyncLog


@pytest.mark.django_db
def test_synthetic_projections_persist(synthetic_league) -> None:
    rows = SyntheticProjectionSource().fetch(999999)
    # One projection per draft pick (10 teams x 15 rounds x 3 seasons).
    assert len(rows) == 10 * 15 * 3
    count = persist_projections(rows)
    assert count == len(rows)
    # ESPN ids resolve to synced Player rows.
    assert PlayerProjection.objects.filter(player__isnull=False).count() == count
    # Season-long rows are week 0 and carry all three scale columns.
    row = PlayerProjection.objects.exclude(pts_ppr=0).first()
    assert row is not None
    assert row.week == 0
    assert row.pts_std is not None and row.pts_half_ppr is not None

    # Idempotent: re-persisting replaces, not duplicates.
    persist_projections(rows)
    assert PlayerProjection.objects.count() == count


@pytest.mark.django_db
def test_sync_projections_command(synthetic_league) -> None:
    call_command("sync_projections", "--source", "synthetic")
    assert PlayerProjection.objects.exists()
    log = SyncLog.objects.filter(command="sync_projections").latest("id")
    assert log.status == SyncLog.Status.SUCCESS
    assert log.row_counts["projection_rows"] == PlayerProjection.objects.count()
    assert log.row_counts["espn_id_matched"] == log.row_counts["projection_rows"]
