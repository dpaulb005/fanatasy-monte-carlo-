"""API contract tests + query-count budgets on read endpoints."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_league_overview_shape(client, computed_league) -> None:
    resp = client.get(reverse("api:league-overview"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["league"]["name"]
    assert len(body["seasons"]) == 3
    assert len(body["champions_timeline"]) == 3
    # Champions timeline is chronological.
    years = [c["year"] for c in body["champions_timeline"]]
    assert years == sorted(years)


@pytest.mark.django_db
def test_managers_table(client, computed_league) -> None:
    resp = client.get(reverse("api:managers"))
    assert resp.status_code == 200
    table = resp.json()
    assert len(table) == 10
    # Sorted by wins descending.
    wins = [row["wins"] for row in table]
    assert wins == sorted(wins, reverse=True)
    assert 0.0 <= table[0]["win_pct"] <= 1.0


@pytest.mark.django_db
def test_manager_detail_shape(client, computed_league) -> None:
    manager_id = client.get(reverse("api:managers")).json()[0]["manager"]["id"]
    resp = client.get(reverse("api:manager-detail", args=[manager_id]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["career"]["seasons_played"] == 3
    assert len(body["seasons"]) == 3
    assert len(body["luck_chart"]["series"]) == 2
    assert body["luck_chart"]["labels"] == sorted(body["luck_chart"]["labels"])


@pytest.mark.django_db
def test_season_detail_standings(client, computed_league) -> None:
    resp = client.get(reverse("api:season-detail", args=[2023]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["champion"]["rank"] == 1
    ranks = [row["rank"] for row in body["standings"]]
    assert ranks == sorted(ranks)
    assert len(body["standings"]) == 10


@pytest.mark.django_db
def test_h2h_matrix_symmetry(client, computed_league) -> None:
    resp = client.get(reverse("api:h2h-matrix"))
    assert resp.status_code == 200
    body = resp.json()
    n = len(body["managers"])
    assert n == 10
    matrix = body["matrix"]
    # Diagonal is empty; off-diagonal cells are mirror records.
    for i in range(n):
        assert matrix[i][i] is None
        for j in range(n):
            if i != j and matrix[i][j] and matrix[j][i]:
                assert matrix[i][j]["wins"] == matrix[j][i]["losses"]


@pytest.mark.django_db
def test_missing_season_returns_404(client, computed_league) -> None:
    assert client.get(reverse("api:season-detail", args=[1990])).status_code == 404


@pytest.mark.django_db
def test_endpoints_have_bounded_queries(client, computed_league) -> None:
    # Read endpoints must not scale queries with data size (no N+1).
    budgets = {
        reverse("api:managers"): 8,
        reverse("api:season-detail", args=[2023]): 8,
        reverse("api:h2h-matrix"): 8,
    }
    for url, budget in budgets.items():
        with CaptureQueriesContext(connection) as ctx:
            client.get(url)
        assert len(ctx) <= budget, f"{url} used {len(ctx)} queries (budget {budget})"


@pytest.mark.django_db
def test_manager_scouting_percentiles(computed_league) -> None:
    from rest_framework.test import APIClient

    from league.models import ManagerSeasonStats

    first_stat = ManagerSeasonStats.objects.first()
    assert first_stat is not None
    mid = first_stat.manager_id
    data = APIClient().get(f"/api/v1/managers/{mid}/scouting/").json()
    assert data["qualified"] is True  # synthetic managers all have 3 seasons
    assert data["pool_size"] == 10
    keys = [t["key"] for t in data["traits"]]
    assert keys == ["firepower", "volatility", "fortune", "discipline", "self_sabotage"]
    for t in data["traits"]:
        assert t["percentile"] is None or 0.0 <= t["percentile"] <= 1.0
        assert t["definition"]

    assert APIClient().get("/api/v1/managers/999999/scouting/").status_code == 404


@pytest.mark.django_db
def test_manager_scouting_min_sample_rule(computed_league) -> None:
    from rest_framework.test import APIClient

    from league.analytics.engine import compute_league
    from league.models import Manager, TeamSeason

    # Give one team-season to a fresh single-season manager: no percentiles.
    rookie = Manager.objects.create(guid="{ROOKIE-GUID}", display_name="Rookie")
    team = TeamSeason.objects.order_by("id").first()
    assert team is not None
    team.managers.set([rookie])
    compute_league(999999)

    data = APIClient().get(f"/api/v1/managers/{rookie.id}/scouting/").json()
    assert data["qualified"] is False
    assert all(t["percentile"] is None for t in data["traits"])
