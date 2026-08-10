"""Draft pattern/sequence analytics + API tests."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.draft_patterns import OPENING_ROUNDS, compute_draft_patterns
from league.analytics.drafts import compute_draft_values
from league.analytics.engine import compute_league
from league.analytics.frames import load_frames


@pytest.mark.django_db
def test_draft_patterns_computed(synthetic_league) -> None:
    frames = load_frames(999999)
    blob = compute_draft_patterns(frames, compute_draft_values(frames))

    assert blob["rounds"] == 15
    assert blob["seasons"] == sorted(blob["seasons"])
    assert len(blob["managers"]) == 10

    for entry in blob["managers"]:
        # Every manager drafted every synthetic season, 15 picks per draft,
        # sequenced in pick order.
        assert len(entry["drafts"]) == len(blob["seasons"])
        for draft in entry["drafts"]:
            picks = draft["picks"]
            assert len(picks) == 15
            overalls = [p["overall_pick"] for p in picks]
            assert overalls == sorted(overalls)

        profile = entry["profile"]
        signature = profile["opening"]["signature"]
        assert len(signature.split("-")) == OPENING_ROUNDS
        # Tendencies count only live picks — keepers are excluded.
        drafted = sum(1 for d in entry["drafts"] for p in d["picks"] if not p["is_keeper"])
        assert profile["total_picks"] == drafted
        assert drafted < 15 * len(blob["seasons"])  # synthetic league has keepers
        # Phase shares are proportions over that phase's picks.
        for shares in profile["position_shares"].values():
            if shares:
                assert sum(shares.values()) == pytest.approx(1.0, abs=0.01)


@pytest.mark.django_db
def test_draft_patterns_endpoint(synthetic_league) -> None:
    compute_league(999999)
    client = APIClient()
    resp = client.get(reverse("api:draft-patterns"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["rounds"] == 15
    assert len(body["managers"]) == 10
    # Standalone blob must not leak into the generic trends payload.
    trends = client.get(reverse("api:trends")).json()
    assert "draft_patterns" not in trends


@pytest.mark.django_db
def test_projection_retrospectives(synthetic_league) -> None:
    from league.analytics.engine import compute_league
    from league.ingestion.nfl_context import SyntheticADPSource, persist_adp
    from league.ingestion.projections import SyntheticProjectionSource, persist_projections
    from league.models import SeasonTrend

    persist_adp(SyntheticADPSource().fetch(999999))
    persist_projections(SyntheticProjectionSource().fetch(999999))
    compute_league(999999)

    blob = SeasonTrend.objects.get(season__isnull=True, key="draft_patterns").data
    proj = blob["projection"]
    assert proj["scale"] == "pts_ppr"
    assert proj["matched_picks"] > 100
    assert len(proj["steals"]) == 10 and len(proj["busts"]) == 10
    assert proj["steals"][0]["delta"] >= proj["steals"][-1]["delta"]
    assert proj["busts"][0]["delta"] <= proj["busts"][-1]["delta"]
    assert proj["steals"][0]["delta"] > 0 > proj["busts"][0]["delta"]

    for entry in blob["managers"]:
        p = entry["profile"]["projection"]
        # Keepers get no projection credit; everything else matches (synthetic
        # projections cover every draft pick).
        assert p["picks"] == entry["profile"]["total_picks"]
        assert p["beat_rate"] is None or 0.0 <= p["beat_rate"] <= 1.0


@pytest.mark.django_db
def test_position_runs(synthetic_league) -> None:
    from league.analytics.drafts import compute_draft_values

    frames = load_frames(999999)
    blob = compute_draft_patterns(frames, compute_draft_values(frames))
    runs = blob["position_runs"]
    assert runs["min_length"] == 3
    assert runs["total"] > 0
    longest = runs["longest"]
    assert longest and len(longest) <= 10
    # Sorted by length desc; every run meets the minimum and is one position.
    lengths = [r["length"] for r in longest]
    assert lengths == sorted(lengths, reverse=True)
    for r in longest:
        assert r["length"] >= 3
        assert len(r["picks"]) == r["length"]
        # First pick of a run is never a "panic" — panic requires joining.
        assert r["picks"][0]["panic"] is False
    # Per-manager run behavior is attached to every profile.
    for entry in blob["managers"]:
        b = entry["profile"]["runs"]
        assert set(b) == {"started", "joined", "panic_joins"}
        assert b["panic_joins"] <= b["joined"]
