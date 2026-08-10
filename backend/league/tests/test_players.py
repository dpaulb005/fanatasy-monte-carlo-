"""Player value tests: attribution math, reconciliation invariants, API."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from league.analytics.engine import compute_league
from league.analytics.frames import LeagueFrames, PlayerWeekFrame, TeamSeasonFrame
from league.analytics.players import compute_player_values
from league.models import LineupSlot, PlayerManagerSeasonValue, PlayerSeasonValue

# --- Pure attribution tests (hand-built frames) ---


def _frames_with_midseason_move() -> LeagueFrames:
    """Player 7 spends weeks 1-2 on team 1 (manager 100), week 3 on team 2
    (manager 200); started weeks 1 and 3, benched week 2."""
    team_seasons = {
        1: TeamSeasonFrame(
            id=1,
            season_year=2023,
            manager_ids=[100],
            manager_labels={100: "A"},
            wins=0,
            losses=0,
            ties=0,
            points_for=0,
            points_against=0,
            final_standing=1,
            made_playoffs=False,
        ),
        2: TeamSeasonFrame(
            id=2,
            season_year=2023,
            manager_ids=[200],
            manager_labels={200: "B"},
            wins=0,
            losses=0,
            ties=0,
            points_for=0,
            points_against=0,
            final_standing=2,
            made_playoffs=False,
        ),
    }
    weeks = [
        PlayerWeekFrame(2023, 1, 7, "Mover", "RB", 1, True, 10.0),
        PlayerWeekFrame(2023, 2, 7, "Mover", "RB", 1, False, 8.0),
        PlayerWeekFrame(2023, 3, 7, "Mover", "RB", 2, True, 12.0),
    ]
    return LeagueFrames(
        league_id=1,
        team_count_by_year={2023: 2},
        team_seasons=team_seasons,
        team_weeks=[],
        scores_by_week={},
        draft_picks=[],
        player_season_points={2023: {7: 30.0}},
        player_position={7: "RB"},
        player_weeks=weeks,
        player_names={7: "Mover"},
        player_position_by_year={2023: {7: "RB"}},
    )


def test_midseason_move_splits_by_week() -> None:
    season_rows, manager_rows = compute_player_values(_frames_with_midseason_move())

    assert len(season_rows) == 1
    row = season_rows[0]
    assert row.total_points == pytest.approx(30.0)
    assert row.started_points == pytest.approx(22.0)
    assert row.bench_points == pytest.approx(8.0)
    assert row.weeks_rostered == 3
    assert row.weeks_started == 2
    assert row.position_rank == 1

    by_manager = {r.manager_id: r for r in manager_rows}
    assert by_manager[100].total_points == pytest.approx(18.0)
    assert by_manager[100].weeks_rostered == 2
    assert by_manager[100].weeks_started == 1
    assert by_manager[200].total_points == pytest.approx(12.0)
    assert by_manager[200].weeks_rostered == 1
    # Manager splits sum to the season totals.
    assert sum(r.total_points for r in manager_rows) == pytest.approx(row.total_points)


def test_replacement_baseline_matches_draft_definition() -> None:
    frames = _frames_with_midseason_move()
    season_rows, _ = compute_player_values(frames)
    # Only RB in the pool: rank round(2.5 * 2 teams)=5 -> clamped to pool size 1,
    # so the player IS the replacement level and PoR is 0.
    assert season_rows[0].points_over_replacement == pytest.approx(0.0)


# --- Engine invariants on the synthetic league ---


@pytest.mark.django_db
def test_player_values_reconcile_with_lineup_slots(synthetic_league) -> None:
    compute_league(999999)
    assert PlayerSeasonValue.objects.exists()
    for psv in PlayerSeasonValue.objects.select_related("player", "season")[:25]:
        slot_total = sum(
            s.points
            for s in LineupSlot.objects.filter(player=psv.player, team_season__season=psv.season)
        )
        assert psv.total_points == pytest.approx(slot_total, abs=0.01)
        assert psv.total_points == pytest.approx(psv.started_points + psv.bench_points, abs=0.01)
        assert psv.weeks_started <= psv.weeks_rostered


@pytest.mark.django_db
def test_manager_splits_sum_to_season_totals(synthetic_league) -> None:
    # Synthetic teams are single-managed, so splits must sum exactly.
    compute_league(999999)
    for psv in PlayerSeasonValue.objects.all()[:50]:
        split = sum(
            v.total_points
            for v in PlayerManagerSeasonValue.objects.filter(player=psv.player, season=psv.season)
        )
        assert split == pytest.approx(psv.total_points, abs=0.01)


@pytest.mark.django_db
def test_position_rank_is_dense_from_one(synthetic_league) -> None:
    compute_league(999999)
    first = PlayerSeasonValue.objects.select_related("season").first()
    assert first is not None
    season = first.season
    rb_ranks = sorted(
        PlayerSeasonValue.objects.filter(season=season, position="RB").values_list(
            "position_rank", flat=True
        )
    )
    assert rb_ranks == list(range(1, len(rb_ranks) + 1))


# --- API ---


@pytest.mark.django_db
def test_players_index_career_and_season_modes(computed_league) -> None:
    client = APIClient()
    career = client.get("/api/v1/players/").json()
    assert career["mode"] == "career"
    assert career["players"], "career list should not be empty"
    assert career["available_seasons"] == [2023, 2022, 2021]

    season = client.get("/api/v1/players/", {"season": "2022", "position": "QB"}).json()
    assert season["mode"] == "season"
    assert all(p["player"]["position"] == "QB" for p in season["players"])

    bounded = client.get("/api/v1/players/", {"limit": 5000}).json()
    assert len(bounded["players"]) <= 200


@pytest.mark.django_db
def test_player_detail_and_404(computed_league) -> None:
    client = APIClient()
    first = PlayerSeasonValue.objects.select_related("player").first()
    assert first is not None
    espn_id = first.player.espn_player_id
    detail = client.get(f"/api/v1/players/{espn_id}/").json()
    assert detail["player"]["id"] == espn_id
    assert detail["career"]["seasons"] >= 1
    assert detail["seasons"]
    assert detail["managers"]
    assert detail["weekly"]
    # Manager splits shown on the page must sum to the career total.
    split = sum(m["total_points"] for m in detail["managers"])
    assert split == pytest.approx(detail["career"]["total_points"], abs=0.05)

    assert APIClient().get("/api/v1/players/999999999/").status_code == 404


@pytest.mark.django_db
def test_espn_dst_label_is_normalized(synthetic_league) -> None:
    # ESPN labels defenses "D/ST"; analytics tables key on "DST". The frames
    # boundary must normalize so replacement level and slots resolve.
    from league.analytics.frames import load_frames, normalize_position
    from league.models import Player

    assert normalize_position("D/ST") == "DST"
    assert normalize_position("RB") == "RB"

    victim = Player.objects.filter(season_values__isnull=False).first() or Player.objects.first()
    assert victim is not None
    Player.objects.filter(id=victim.id).update(position="D/ST")
    frames = load_frames(999999)
    assert frames.player_position.get(victim.espn_player_id) == "DST"


@pytest.mark.django_db
def test_players_index_rejects_malformed_params(computed_league) -> None:
    client = APIClient()
    assert client.get("/api/v1/players/", {"season": "abc"}).status_code == 400
    assert client.get("/api/v1/players/", {"limit": "all"}).status_code == 400
    # Empty values fall back to defaults instead of crashing.
    assert client.get("/api/v1/players/", {"limit": "", "season": ""}).status_code == 200


@pytest.mark.django_db
def test_player_with_no_league_data_is_404(computed_league) -> None:
    from league.models import Player

    ghost = Player.objects.create(espn_player_id=424242, name="Ghost", position="QB")
    assert APIClient().get(f"/api/v1/players/{ghost.espn_player_id}/").status_code == 404
