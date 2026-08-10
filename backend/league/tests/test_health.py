"""Smoke test for the health endpoint and API wiring."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_endpoint_reports_ok() -> None:
    client = APIClient()
    response = client.get(reverse("api:health"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "fantasy-analysis-api"
    assert body["database"] == "ok"
