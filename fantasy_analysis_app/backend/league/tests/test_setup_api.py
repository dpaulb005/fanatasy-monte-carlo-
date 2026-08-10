"""Manager setup API: inventory predictions + operator corrections."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.engine import compute_league
from league.api.setup import predict_real_name
from league.models import Manager, ManagerCareerStats


def test_predict_real_name() -> None:
    # ESPN auto-handles and single words are not names.
    assert predict_real_name("espnfan6721714153") == ""
    assert predict_real_name("dave2020") == ""
    assert predict_real_name("Braylan") == ""
    assert predict_real_name("") == ""
    # Name-shaped display names are cleaned up conservatively.
    assert predict_real_name("braylan covol") == "Braylan Covol"
    assert predict_real_name("MATT WEYANDT") == "Matt Weyandt"
    assert predict_real_name("DeAndre McCoy") == "DeAndre McCoy"
    assert predict_real_name("mary-jo o'neil") == "Mary-jo O'neil"


@pytest.mark.django_db
def test_setup_inventory(synthetic_league) -> None:
    client = APIClient()
    body = client.get(reverse("api:setup-managers")).json()
    rows = body["managers"]
    assert len(rows) == Manager.objects.count()
    row = rows[0]
    for key in (
        "id",
        "guid",
        "display_name",
        "real_name",
        "predicted_real_name",
        "email",
        "merged_into",
        "seasons",
        "merge_suggestion",
    ):
        assert key in row
    # Every synthetic manager fielded teams; seasons carry year + team name.
    assert row["seasons"] and {"year", "team"} <= set(row["seasons"][0])


@pytest.mark.django_db
def test_setup_saves_names_and_emails(synthetic_league) -> None:
    client = APIClient()
    manager = Manager.objects.order_by("id").first()
    assert manager is not None
    resp = client.post(
        reverse("api:setup-managers"),
        {"managers": [{"id": manager.id, "real_name": "Dave Brown", "email": "dave@example.com"}]},
        format="json",
    )
    assert resp.status_code == 200
    manager.refresh_from_db()
    assert manager.real_name == "Dave Brown"
    assert manager.email == "dave@example.com"
    # Name changes rebuild analytics so baked-in labels update.
    assert resp.json()["analytics_recomputed"] is True

    bad = client.post(
        reverse("api:setup-managers"),
        {"managers": [{"id": manager.id, "email": "not-an-email"}]},
        format="json",
    )
    assert bad.status_code == 400
    manager.refresh_from_db()
    assert manager.email == "dave@example.com"


@pytest.mark.django_db
def test_setup_merge_validated_and_recomputed(synthetic_league) -> None:
    compute_league(999999)
    client = APIClient()
    a, b = list(Manager.objects.order_by("id")[:2])
    # Synthetic managers all coexist every season, so a merge must be refused.
    resp = client.post(
        reverse("api:setup-managers"),
        {"managers": [{"id": a.id, "merged_into": b.id}]},
        format="json",
    )
    assert resp.status_code == 400
    assert "both fielded teams" in str(resp.json())

    # A duplicate account with no seasons merges cleanly and consolidates careers.
    dupe = Manager.objects.create(guid="{DUPE-GUID}", display_name=a.display_name)
    resp = client.post(
        reverse("api:setup-managers"),
        {"managers": [{"id": dupe.id, "merged_into": a.id}]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["merges_changed"] == 1
    dupe.refresh_from_db()
    assert dupe.merged_into_id == a.id
    assert not ManagerCareerStats.objects.filter(manager=dupe).exists()

    # Unmerge by clearing the pointer.
    resp = client.post(
        reverse("api:setup-managers"),
        {"managers": [{"id": dupe.id, "merged_into": None}]},
        format="json",
    )
    assert resp.status_code == 200
    dupe.refresh_from_db()
    assert dupe.merged_into_id is None
