"""Awards analytics + Hall of Fame API tests."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.awards import compute_awards
from league.analytics.drafts import compute_draft_values
from league.analytics.engine import compute_league
from league.analytics.frames import load_frames
from league.models import Award


def _season_rows_for(league_id: int) -> tuple:
    # Rebuild the inputs compute_awards needs, mirroring the engine.
    from league.analytics.engine import _team_manager_season_rows

    frames = load_frames(league_id)
    season_rows = _team_manager_season_rows(frames)
    draft_values = compute_draft_values(frames)
    return frames, season_rows, draft_values


@pytest.mark.django_db
def test_awards_are_data_backed(synthetic_league) -> None:
    frames, season_rows, draft_values = _season_rows_for(999999)
    awards = compute_awards(frames, season_rows, draft_values)
    slugs = {a.slug for a in awards}
    # Core per-season awards present.
    assert {"heartbreak", "daylight_robbery", "benchwarmer", "sacko"} <= slugs
    # Every award has a winner and a context explaining it.
    for a in awards:
        assert a.context  # non-empty context
    # Heartbreak: the score must exceed the opponent... no, it's a loss.
    heartbreaks = [a for a in awards if a.slug == "heartbreak"]
    for h in heartbreaks:
        assert h.context["score"] < h.context["opponent_score"]


@pytest.mark.django_db
def test_most_loyal_award_spans_seasons(synthetic_league) -> None:
    compute_league(999999)
    loyal = Award.objects.filter(slug="most_loyal").first()
    assert loyal is not None
    # Franchise keeper spans all 3 fixture seasons.
    assert len(loyal.context["seasons"]) == 3


@pytest.mark.django_db
def test_awards_and_records_endpoints(synthetic_league) -> None:
    compute_league(999999)
    client = APIClient()
    awards = client.get(reverse("api:awards")).json()
    assert awards["seasons"]
    assert all("winner" in a for season in awards["seasons"] for a in season["awards"])

    records = client.get(reverse("api:records")).json()
    assert len(records["most_points_season"]) == 5
    # Sorted descending by value.
    vals = [r["value"] for r in records["most_points_season"]]
    assert vals == sorted(vals, reverse=True)
