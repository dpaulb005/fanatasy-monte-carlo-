"""Draft value analytics + draft API tests."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.drafts import compute_draft_values
from league.analytics.engine import compute_league
from league.analytics.frames import load_frames
from league.ingestion.nfl_context import SyntheticADPSource, persist_adp
from league.models import DraftPickValue


@pytest.mark.django_db
def test_draft_values_computed(synthetic_league) -> None:
    rows = compute_draft_values(load_frames(999999))
    # One value row per draft pick (10 teams * 15 rounds * 3 seasons).
    assert len(rows) == 10 * 15 * 3
    # Points over replacement should be positive for at least some early picks.
    assert any(r.points_over_replacement > 0 for r in rows)
    # Season points are non-negative.
    assert all(r.season_points >= 0 for r in rows)


@pytest.mark.django_db
def test_synthetic_adp_feeds_adp_delta(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)
    # With ADP present, adp_delta should be populated for picks.
    with_adp = DraftPickValue.objects.filter(adp__isnull=False).count()
    assert with_adp > 0


@pytest.mark.django_db
def test_season_draft_endpoint(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)
    client = APIClient()
    resp = client.get(reverse("api:season-draft", args=[2023]))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["picks"]) == 150
    assert body["round_value_curve"]["labels"][0] == 1
    # Scatter points are [adp, season_points, por] triples.
    assert all(len(pt) == 3 for pt in body["scatter"])


def test_normalize_player_name_join_key() -> None:
    from league.analytics.drafts import normalize_player_name as norm

    # Suffixes and punctuation FFC/ESPN apply inconsistently.
    assert norm("Deebo Samuel Sr.") == norm("Deebo Samuel")
    assert norm("Anthony Richardson Sr.") == norm("Anthony Richardson")
    assert norm("Patrick Mahomes II") == norm("Patrick Mahomes")
    assert norm("Ja'Marr Chase") == "jamarr chase"
    assert norm("A.J. Brown") == "aj brown"
    assert norm("Jaxon Smith-Njigba") == "jaxon smith njigba"
    # ESPN nickname D/ST maps onto FFC's "<city> Defense" form.
    assert norm("Ravens D/ST") == norm("Baltimore Defense")
    assert norm("Jets D/ST") == norm("NY Jets Defense")
    assert norm("Chargers D/ST") == norm("LA Chargers Defense")
    assert norm("49ers D/ST") == norm("San Francisco Defense")
    # Plain names pass through untouched.
    assert norm("Josh Allen") == "josh allen"
