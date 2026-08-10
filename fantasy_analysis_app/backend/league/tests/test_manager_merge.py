"""Identity continuity: merge_managers command + compute-time resolution."""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from league.analytics.engine import compute_league
from league.models import (
    HeadToHeadRecord,
    Manager,
    ManagerCareerStats,
    PlayerManagerSeasonValue,
    TeamSeason,
)


def _split_alt_account(synthetic_league) -> tuple[Manager, Manager]:
    """Model the real duplicate-account case: give one manager's earliest
    team-season to a fresh 'alternate account' Manager, so the same human
    appears as two non-overlapping Manager rows."""
    canonical = Manager.objects.order_by("id").first()
    assert canonical is not None
    earliest_team = TeamSeason.objects.filter(managers=canonical).order_by("season__year").first()
    assert earliest_team is not None
    alt = Manager.objects.create(guid="{ALT-ACCOUNT-GUID}", display_name="Alt Account")
    earliest_team.managers.set([alt])
    return alt, canonical


@pytest.mark.django_db
def test_merge_combines_career_and_purges_source(synthetic_league) -> None:
    alt, canonical = _split_alt_account(synthetic_league)
    compute_league(999999)
    alt_career = ManagerCareerStats.objects.get(manager=alt)
    canonical_career = ManagerCareerStats.objects.get(manager=canonical)
    assert alt_career.seasons_played == 1
    assert canonical_career.seasons_played == 2
    combined_wins = alt_career.wins + canonical_career.wins
    pairs_before = HeadToHeadRecord.objects.count()

    call_command("merge_managers", alt.id, canonical.id)
    compute_league(999999)

    # Careers combine on the canonical manager; the alt row is purged.
    merged = ManagerCareerStats.objects.get(manager=canonical)
    assert merged.wins == combined_wins
    assert merged.seasons_played == 3
    assert not ManagerCareerStats.objects.filter(manager=alt).exists()

    # The alt account disappears from H2H and the pair count shrinks
    # (11 apparent managers collapse back to 10 humans).
    assert not HeadToHeadRecord.objects.filter(manager_a=alt).exists()
    assert not HeadToHeadRecord.objects.filter(manager_b=alt).exists()
    assert HeadToHeadRecord.objects.count() < pairs_before

    # Player attribution follows the canonical manager.
    assert not PlayerManagerSeasonValue.objects.filter(manager=alt).exists()
    assert PlayerManagerSeasonValue.objects.filter(manager=canonical).exists()

    # Source data was NOT rewritten — the merge is a resolvable pointer.
    assert TeamSeason.objects.filter(managers=alt).exists()


@pytest.mark.django_db
def test_unmerge_restores_separate_careers(synthetic_league) -> None:
    alt, canonical = _split_alt_account(synthetic_league)
    call_command("merge_managers", alt.id, canonical.id)
    call_command("merge_managers", "--unmerge", alt.id)
    compute_league(999999)
    assert ManagerCareerStats.objects.get(manager=alt).seasons_played == 1
    assert ManagerCareerStats.objects.get(manager=canonical).seasons_played == 2


@pytest.mark.django_db
def test_merge_refuses_overlapping_humans(synthetic_league) -> None:
    # Two ORIGINAL managers fielded teams in the same seasons — one human
    # cannot own two teams at once, so this merge must be refused.
    a, b = list(Manager.objects.order_by("id")[:2])
    with pytest.raises(CommandError, match="Refusing to merge"):
        call_command("merge_managers", a.id, b.id)


@pytest.mark.django_db
def test_merge_validation_rules(synthetic_league) -> None:
    alt, canonical = _split_alt_account(synthetic_league)
    third = Manager.objects.exclude(id__in=[alt.id, canonical.id]).first()
    assert third is not None

    with pytest.raises(CommandError, match="into itself"):
        call_command("merge_managers", alt.id, alt.id)

    call_command("merge_managers", alt.id, canonical.id)
    # No chains: cannot merge INTO a merged manager...
    with pytest.raises(CommandError, match="chains"):
        call_command("merge_managers", third.id, alt.id)
    # ...and cannot merge away a manager that has others merged into it.
    with pytest.raises(CommandError, match="chains"):
        call_command("merge_managers", canonical.id, third.id)
    # Cannot re-merge without unmerging first.
    with pytest.raises(CommandError, match="already merged"):
        call_command("merge_managers", alt.id, third.id)
    # Unmerging a non-merged manager is an error.
    with pytest.raises(CommandError, match="not merged"):
        call_command("merge_managers", "--unmerge", third.id)


@pytest.mark.django_db
def test_merged_manager_profile_resolves_to_canonical(synthetic_league) -> None:
    alt, canonical = _split_alt_account(synthetic_league)
    call_command("merge_managers", alt.id, canonical.id)
    compute_league(999999)

    profile = APIClient().get(f"/api/v1/managers/{alt.id}/").json()
    assert profile["manager"]["id"] == canonical.id
    assert profile["career"] is not None
    assert profile["career"]["seasons_played"] == 3
