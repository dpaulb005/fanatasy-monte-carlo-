"""Contract tests for the nflsim snapshot bridge."""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from league.analytics.engine import compute_league
from league.ingestion.nfl_context import SyntheticADPSource, persist_adp
from league.models import PlayerADP, SimulationSnapshot


@pytest.mark.django_db
def test_import_snapshot_enriches_draft_board_and_roster_fit(synthetic_league, tmp_path) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)
    names = list(
        PlayerADP.objects.order_by("adp").values_list("player_name", flat=True)[:2]
    )
    payload = {
        "schema": "nflsim.application-snapshot",
        "schema_version": 1,
        "generated_at": "2026-08-10T12:00:00+00:00",
        "model": {
            "season": 2026,
            "simulations": 5000,
            "scoring": {"name": "Full PPR"},
            "league": {"teams": 10},
            "weekly_capture": True,
        },
        "players": [
            {
                "player": names[0], "points": 301.2, "p10": 205.0, "p90": 390.0,
                "vor_sim": 88.4, "vor_sim_p10": 4.0, "vor_sim_p90": 171.0,
                "p_pos1": 0.143, "p_top3": 0.31, "p_starter": 0.91,
                "playoff_delta": 1.7,
            },
            {
                "player": names[1], "points": 280.0, "p10": 190.0, "p90": 370.0,
                "vor_sim": 72.0, "p_pos1": 0.09, "p_top3": 0.23, "p_starter": 0.84,
            },
        ],
        "pairs": [{
            "a": names[0], "b": names[1], "corr": 0.18,
            "lift": 1.27, "p_both_boom": 0.079,
        }],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload))

    call_command("import_nflsim", path)
    assert SimulationSnapshot.objects.get().simulations == 5000

    body = APIClient().get(
        reverse("api:draft-suggest"),
        [("pick", "1"), ("teams", "10"), ("roster", names[1])],
    ).json()
    assert body["simulation_model"]["simulations"] == 5000
    row = next(player for player in body["players"] if player["player_name"] == names[0])
    assert row["monte_carlo"]["p_position_1"] == 0.143
    assert row["monte_carlo"]["roster_fit"]["average_tail_lift"] == 1.27


@pytest.mark.django_db
def test_no_matching_league_shape_degrades_cleanly(synthetic_league) -> None:
    persist_adp(SyntheticADPSource().fetch(999999))
    compute_league(999999)
    body = APIClient().get(
        reverse("api:draft-suggest"), {"pick": "1", "teams": "8"}
    ).json()
    assert body["simulation_model"] is None
    assert all(player["monte_carlo"] is None for player in body["players"])
