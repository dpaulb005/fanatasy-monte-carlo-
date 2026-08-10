"""Draft priors + suggester endpoint tests."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.draft_priors import MIN_SIGMA, compute_draft_priors
from league.analytics.drafts import compute_draft_values
from league.analytics.engine import compute_league
from league.analytics.frames import load_frames
from league.api.suggester import snake_picks
from league.ingestion.nfl_context import SyntheticADPSource, persist_adp


def test_snake_picks() -> None:
    assert snake_picks(10, 1, 4) == [1, 20, 21, 40]
    assert snake_picks(10, 10, 4) == [10, 11, 30, 31]
    assert snake_picks(12, 5, 2) == [5, 20]


@pytest.mark.django_db
def test_draft_priors_computed(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    frames = load_frames(999999)
    # ADP rows exist but compute_draft_values needs the lookup wired the same
    # way the engine does it; empty lookup means no residuals — so priors must
    # still compute with calibration falling back gracefully.
    priors = compute_draft_priors(frames, compute_draft_values(frames))
    assert priors["rounds"] == 15
    assert priors["team_count_recent"] == 10
    assert priors["value_bands"]  # PoR quantiles per position exist regardless
    for by_round in priors["value_bands"].values():
        for band in by_round.values():
            assert band["p10"] <= band["p25"] <= band["p50"] <= band["p75"] <= band["p90"]


@pytest.mark.django_db
def test_priors_calibration_from_league_residuals(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)  # wires the ADP lookup and stores the blob
    from league.models import SeasonTrend

    priors = SeasonTrend.objects.get(season__isnull=True, key="draft_priors").data
    overall = priors["adp_calibration"]["overall"]
    # Synthetic ADP is the pick plus small noise, so the league tracks the
    # market: tiny bias, sigma at (or near) the floor.
    assert overall["n"] > 100
    assert abs(overall["bias"]) < 2.0
    assert overall["sigma"] >= MIN_SIGMA


@pytest.mark.django_db
def test_suggest_endpoint(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)
    client = APIClient()

    resp = client.get(reverse("api:draft-suggest"), {"pick": 15, "teams": 10, "slot": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["round"] == 2
    # Snake: slot 5 of 10, picks are 5, 16, 25, 36... next after 15 is 16.
    assert body["next_pick"] == 16
    players = body["players"]
    assert players
    for p in players:
        lo, hi = p["ci80"]
        assert lo <= p["expected_pick"] <= hi
        assert 0.0 <= p["p_available_now"] <= 1.0
        assert p["p_available_next"] is not None
        # Waiting can only lose availability.
        assert p["p_available_next"] <= p["p_available_now"] + 1e-9
    # Board is in league-adjusted market order.
    mus = [p["expected_pick"] for p in players]
    assert mus == sorted(mus)

    # Top-of-board players are practically gone by pick 140.
    late = client.get(reverse("api:draft-suggest"), {"pick": 140}).json()
    late_names = {p["player_name"] for p in late["players"]}
    early_names = {p["player_name"] for p in players[:5]}
    assert not (late_names & early_names)

    # Position filter.
    rbs = client.get(reverse("api:draft-suggest"), {"pick": "15", "position": "RB"}).json()
    assert rbs["players"] and all(p["position"] == "RB" for p in rbs["players"])

    # The priors blob stays out of the generic trends payload.
    trends = client.get(reverse("api:trends")).json()
    assert "draft_priors" not in trends


@pytest.mark.django_db
def test_suggest_with_projection_cis(synthetic_league) -> None:
    from league.ingestion.projections import SyntheticProjectionSource, persist_projections
    from league.models import SeasonTrend

    persist_adp(SyntheticADPSource().fetch(999999))
    persist_projections(SyntheticProjectionSource().fetch(999999))
    compute_league(999999)

    priors = SeasonTrend.objects.get(season__isnull=True, key="draft_priors").data
    error = priors["projection_error"]
    assert error is not None
    # Synthetic projections are built on the PPR column; detection should agree.
    assert error["scale"] == "pts_ppr"
    assert error["matched"] > 100
    q = error["overall"]
    assert q["p10"] <= q["p25"] <= q["p50"] <= q["p75"] <= q["p90"]

    client = APIClient()
    body = client.get(reverse("api:draft-suggest"), {"pick": "15"}).json()
    assert body["projection_season"] is not None
    assert body["projection_scale"] == "pts_ppr"
    with_proj = [p for p in body["players"] if p["projected_points"] is not None]
    assert with_proj
    for p in with_proj:
        lo, hi = p["projected_range"]
        assert lo <= p["projected_points"] + error["overall"]["p90"] + 1e-6
        assert lo < hi


@pytest.mark.django_db
def test_suggest_experts_gap_and_history(synthetic_league) -> None:
    import json
    from pathlib import Path

    from django.core.management import call_command

    from league.ingestion.projections import SyntheticProjectionSource, persist_projections
    from league.models import Player

    persist_adp(SyntheticADPSource().fetch(999999))
    persist_projections(SyntheticProjectionSource().fetch(999999))
    compute_league(999999)

    # Expert sheet fixture covering some synthetic players, with tiers/risk.
    players = list(Player.objects.all()[:6])
    fixture = {
        "source": "testsheet",
        "season": 2026,
        "players": [
            {
                "name": p.name,
                "position": p.position,
                "team": "AAA",
                "tier": chr(ord("A") + i // 2),
                "rank_overall": i + 1,
                "consensus_adp": i + 1.0,
                "risk": 3.0 + i,
                "upside": 9.0 - i,
            }
            for i, p in enumerate(players)
        ],
    }
    tmp = Path("/tmp/expert_ranks_test")
    tmp.mkdir(exist_ok=True)
    (tmp / "test_2026.json").write_text(json.dumps(fixture))
    call_command("load_expert_ranks", "--dir", str(tmp))

    client = APIClient()
    body = client.get(
        reverse("api:draft-suggest"), {"pick": "5", "teams": "10", "slot": "5"}
    ).json()
    assert body["expert_season"] == 2026

    with_expert = [p for p in body["players"] if p["expert"]]
    assert with_expert
    e = with_expert[0]["expert"]
    assert e["rank"] is not None and e["tier"] and e["risk"] is not None

    gap = body["gap_forecast"]
    assert gap and gap["expected_taken"]
    # Expected takes between picks are non-negative and bounded by the gap.
    picks_between = body["next_pick"] - body["pick"]
    assert 0 <= sum(gap["expected_taken"].values()) <= picks_between + 1
    for entry in gap["tier_survival"].values():
        assert 0.0 <= entry["p_any_next"] <= 1.0

    # League history (affinity) flags exist for at least one player overall
    # (synthetic projections guarantee big deltas for someone).
    trends_blob = client.get(reverse("api:draft-patterns")).json()
    assert any(
        m["profile"]["affinity"]["burned"] or m["profile"]["affinity"]["loyal"]
        for m in trends_blob["managers"]
    )


@pytest.mark.django_db
def test_monte_carlo_simulation(synthetic_league) -> None:
    from league.ingestion.projections import SyntheticProjectionSource, persist_projections

    persist_adp(SyntheticADPSource().fetch(999999))
    persist_projections(SyntheticProjectionSource().fetch(999999))
    compute_league(999999)
    client = APIClient()
    body = client.get(
        reverse("api:draft-suggest"),
        {"pick": "15", "teams": "10", "slot": "5", "simulate": "1"},
    ).json()
    sim = body["simulation"]
    assert sim is not None
    assert sim["picks_simulated"] == body["next_pick"] - body["pick"] - 1
    assert sim["best_available_next"]
    for q in sim["best_available_next"].values():
        assert q["p10"] <= q["p50"] <= q["p90"]
    with_mc = [p for p in body["players"] if p.get("mc_survival_next") is not None]
    assert with_mc
    for p in with_mc:
        assert 0.0 <= p["mc_survival_next"] <= 1.0
    # MC and the normal model should roughly agree on ordering: the top of
    # the board must be less likely to survive than the bottom of the list.
    top, bottom = with_mc[0], with_mc[-1]
    assert top["mc_survival_next"] <= bottom["mc_survival_next"] + 0.3
