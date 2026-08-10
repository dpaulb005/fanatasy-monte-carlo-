"""Tests for synthetic generation, persistence, idempotency, and identity."""

from __future__ import annotations

import pytest

from league.ingestion.persist import persist_season
from league.ingestion.synthetic import (
    NUM_TEAMS,
    REG_WEEKS,
    ROSTER_SIZE,
    generate_league,
    generate_season,
)
from league.models import (
    DraftPick,
    LineupSlot,
    Manager,
    Matchup,
    Season,
    TeamSeason,
)


def test_generation_is_deterministic() -> None:
    a = generate_season(2022)
    b = generate_season(2022)
    assert [t.points_for for t in a.teams] == [t.points_for for t in b.teams]
    assert [d.player.espn_player_id for d in a.draft] == [d.player.espn_player_id for d in b.draft]


def test_season_bundle_shape() -> None:
    bundle = generate_season(2023)
    assert len(bundle.teams) == NUM_TEAMS
    assert len(bundle.draft) == NUM_TEAMS * ROSTER_SIZE
    # Every team plays every regular week; scores derive from lineups.
    assert len(bundle.lineups) == NUM_TEAMS * REG_WEEKS * ROSTER_SIZE
    # Final standings are a permutation of 1..N.
    assert sorted(t.final_standing for t in bundle.teams) == list(range(1, NUM_TEAMS + 1))


@pytest.mark.django_db
def test_persist_counts(synthetic_league) -> None:
    assert Season.objects.count() == 3
    assert Manager.objects.count() == NUM_TEAMS
    assert TeamSeason.objects.count() == NUM_TEAMS * 3
    assert DraftPick.objects.count() == NUM_TEAMS * ROSTER_SIZE * 3


@pytest.mark.django_db
def test_manager_identity_survives_rename(synthetic_league) -> None:
    # Manager 0 renames every season; identity must key on GUID, not name.
    manager = Manager.objects.get(guid="{MGR-00-GUID}")
    assert manager.team_seasons.count() == 3
    # Only NUM_TEAMS unique managers exist despite 3 * NUM_TEAMS team-seasons.
    assert Manager.objects.count() == NUM_TEAMS


@pytest.mark.django_db
def test_persist_is_idempotent(synthetic_league) -> None:
    before = TeamSeason.objects.count()
    for bundle in generate_league([2021, 2022, 2023]):
        persist_season(synthetic_league, bundle)
    assert TeamSeason.objects.count() == before
    assert Manager.objects.count() == NUM_TEAMS


@pytest.mark.django_db
def test_team_score_matches_started_lineup(synthetic_league) -> None:
    # A regular-season team's weekly score equals the sum of its started slots.
    matchup = Matchup.objects.filter(kind=Matchup.Kind.REGULAR).select_related("home").first()
    assert matchup is not None
    started = LineupSlot.objects.filter(team_season=matchup.home, week=matchup.week).exclude(
        slot__in=[LineupSlot.Slot.BENCH, LineupSlot.Slot.IR]
    )
    total = round(sum(s.points for s in started), 1)
    assert total == pytest.approx(matchup.home_score, abs=0.11)
