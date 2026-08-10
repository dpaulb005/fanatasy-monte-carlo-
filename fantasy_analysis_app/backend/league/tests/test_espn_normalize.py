"""Unit tests for the espn-api -> SeasonBundle normalizer using fakes.

These verify the field mapping in isolation (no network, no espn-api package)
so the one place ESPN API drift bites has explicit coverage.
"""

from __future__ import annotations

from types import SimpleNamespace

from league.ingestion.espn_normalize import (
    normalize_season,
    normalize_week_box_scores,
)
from league.ingestion.ports import capabilities_for_year


def _fake_team(team_id, name, owner_guid, wins=0, losses=0, pf=0.0):
    return SimpleNamespace(
        team_id=team_id,
        team_name=name,
        team_abbrev=name[:3],
        owners=[{"id": owner_guid, "firstName": "First", "lastName": name}],
        wins=wins,
        losses=losses,
        ties=0,
        points_for=pf,
        points_against=0.0,
        final_standing=1,
        division_name="",
    )


def _fake_boxplayer(pid, name, position, slot, points):
    return SimpleNamespace(
        playerId=pid,
        name=name,
        position=position,
        slot_position=slot,
        points=points,
        projected_points=points,
    )


def test_normalize_managers_and_teams() -> None:
    league = SimpleNamespace(
        year=2022,
        settings=SimpleNamespace(name="Test", reg_season_count=13, playoff_team_count=6),
        members=[{"id": "{SWID-A}", "displayName": "Alpha"}],
        teams=[
            _fake_team(1, "Alpha", "{SWID-A}", wins=9, losses=4, pf=1500.0),
            _fake_team(2, "Bravo", "{SWID-B}", wins=4, losses=9, pf=1200.0),
        ],
        draft=[],
    )
    caps = capabilities_for_year(2022)
    bundle = normalize_season(league, caps, week_box_scores=None)

    assert bundle.year == 2022
    assert bundle.regular_season_weeks == 13
    # Managers come from members plus any team owners not in members.
    guids = {m.guid for m in bundle.managers}
    assert guids == {"{SWID-A}", "{SWID-B}"}
    alpha = next(t for t in bundle.teams if t.team_name == "Alpha")
    assert alpha.wins == 9
    assert alpha.owner_guids == ["{SWID-A}"]


def test_normalize_box_scores_maps_slots_and_scores() -> None:
    home = _fake_team(1, "Alpha", "{SWID-A}")
    away = _fake_team(2, "Bravo", "{SWID-B}")
    box = SimpleNamespace(
        home_team=home,
        away_team=away,
        home_score=120.5,
        away_score=99.0,
        home_lineup=[
            _fake_boxplayer(10, "QB1", "QB", "QB", 25.0),
            _fake_boxplayer(11, "RB1", "RB", "RB/WR/TE", 18.0),  # FLEX label
            _fake_boxplayer(12, "WR2", "WR", "BE", 4.0),  # bench
        ],
        away_lineup=[_fake_boxplayer(20, "QB2", "QB", "QB", 15.0)],
    )
    matchups, lineups = normalize_week_box_scores([box], week=3)

    assert len(matchups) == 1
    assert matchups[0].home_score == 120.5
    assert matchups[0].away_espn_id == 2
    slots = {lp.player.espn_player_id: lp.slot for lp in lineups}
    assert slots[10] == "QB"
    assert slots[11] == "FLEX"
    assert slots[12] == "BE"


def test_lineups_available_reflects_era() -> None:
    league = SimpleNamespace(
        year=2016,
        settings=SimpleNamespace(name="Old", reg_season_count=13, playoff_team_count=6),
        members=[],
        teams=[],
        draft=[],
    )
    caps = capabilities_for_year(2016)
    bundle = normalize_season(league, caps, week_box_scores=None)
    assert bundle.lineups_available is False
