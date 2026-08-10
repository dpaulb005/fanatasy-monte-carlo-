"""Shared test fixtures."""

from __future__ import annotations

import pytest

from league.ingestion.persist import persist_season
from league.ingestion.synthetic import generate_league
from league.models import League


@pytest.fixture
def synthetic_league(db) -> League:
    """A persisted 3-season synthetic league for fast tests."""
    league = League.objects.create(espn_league_id=999999, name="Test League")
    for bundle in generate_league([2021, 2022, 2023]):
        persist_season(league, bundle)
    return league


@pytest.fixture
def computed_league(synthetic_league) -> League:
    """The synthetic league with analytics computed (for API tests)."""
    from league.analytics.engine import compute_league

    compute_league(synthetic_league.espn_league_id)
    return synthetic_league
