"""Normalize ``espn-api`` objects into our ``SeasonBundle`` schema.

Pure functions (no network) so the brittle field-mapping is unit-testable with
lightweight fakes. The exact attribute names should be re-verified against the
pinned ``espn-api`` version on the first real sync — this is the one place ESPN
API drift bites, and it is deliberately isolated here (ADR-005).
"""

from __future__ import annotations

from typing import Any

from league.ingestion.ports import EraCapabilities
from league.ingestion.schemas import (
    DraftRow,
    LineupRow,
    ManagerRef,
    MatchupRow,
    PlayerRef,
    SeasonBundle,
    TeamRow,
)

# espn-api slot_position label -> our LineupSlot.Slot value.
_SLOT_MAP = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "RB/WR": "FLEX",
    "WR/TE": "FLEX",
    "RB/WR/TE": "FLEX",
    "FLEX": "FLEX",
    "OP": "FLEX",
    "D/ST": "DST",
    "DST": "DST",
    "K": "K",
    "BE": "BE",
    "Bench": "BE",
    "IR": "IR",
}


def _slot(label: str | None) -> str:
    return _SLOT_MAP.get(label or "", "OTHER")


def _owner_guid(owner: Any) -> str | None:
    """espn-api owners come as either a SWID string or a dict with an 'id'."""
    if isinstance(owner, str):
        return owner
    if isinstance(owner, dict):
        return owner.get("id") or owner.get("swid")
    return None


def _owner_display(owner: Any) -> str:
    if isinstance(owner, dict):
        # Prefer the member's real name; ESPN displayName is often an
        # auto-generated handle like "espnfan6721714153".
        name = " ".join(filter(None, [owner.get("firstName"), owner.get("lastName")])).strip()
        return name or owner.get("displayName") or ""
    return ""


def normalize_managers(espn_league: Any) -> list[ManagerRef]:
    managers: dict[str, ManagerRef] = {}
    for member in getattr(espn_league, "members", []) or []:
        guid = _owner_guid(member)
        if not guid:
            continue
        managers[guid] = ManagerRef(guid=guid, display_name=_owner_display(member))
    # Fall back to team owners if members isn't populated for old seasons.
    for team in getattr(espn_league, "teams", []) or []:
        for owner in getattr(team, "owners", []) or []:
            guid = _owner_guid(owner)
            if guid and guid not in managers:
                managers[guid] = ManagerRef(guid=guid, display_name=_owner_display(owner))
    return list(managers.values())


def normalize_teams(espn_league: Any) -> list[TeamRow]:
    rows: list[TeamRow] = []
    for team in getattr(espn_league, "teams", []) or []:
        owner_guids = [g for g in (_owner_guid(o) for o in getattr(team, "owners", []) or []) if g]
        rows.append(
            TeamRow(
                espn_team_id=int(getattr(team, "team_id", 0)),
                team_name=str(getattr(team, "team_name", "")).strip(),
                owner_guids=owner_guids,
                abbrev=str(getattr(team, "team_abbrev", "")),
                division=str(getattr(team, "division_name", "") or ""),
                wins=int(getattr(team, "wins", 0)),
                losses=int(getattr(team, "losses", 0)),
                ties=int(getattr(team, "ties", 0)),
                points_for=float(getattr(team, "points_for", 0.0)),
                points_against=float(getattr(team, "points_against", 0.0)),
                final_standing=int(
                    getattr(team, "final_standing", 0) or getattr(team, "standing", 0)
                ),
                made_playoffs=bool(getattr(team, "final_standing", 0)),
            )
        )
    return rows


def _player_ref(obj: Any) -> PlayerRef:
    return PlayerRef(
        espn_player_id=int(getattr(obj, "playerId", 0) or getattr(obj, "playerId", 0)),
        name=str(getattr(obj, "name", "") or getattr(obj, "playerName", "")),
        position=str(getattr(obj, "position", "") or ""),
    )


def normalize_draft(espn_league: Any) -> list[DraftRow]:
    rows: list[DraftRow] = []
    for i, pick in enumerate(getattr(espn_league, "draft", []) or [], start=1):
        team = getattr(pick, "team", None)
        rows.append(
            DraftRow(
                overall_pick=int(getattr(pick, "overall_pick", i) or i),
                round=int(getattr(pick, "round_num", 0)),
                round_pick=int(getattr(pick, "round_pick", 0)),
                team_espn_id=int(getattr(team, "team_id", 0)) if team else 0,
                player=PlayerRef(
                    espn_player_id=int(getattr(pick, "playerId", 0)),
                    name=str(getattr(pick, "playerName", "")),
                    position="",
                ),
                is_keeper=bool(getattr(pick, "keeper_status", False)),
                auction_price=(
                    int(getattr(pick, "bid_amount", 0))
                    if getattr(pick, "bid_amount", None)
                    else None
                ),
            )
        )
    return rows


def normalize_week_box_scores(
    box_scores: list[Any], week: int
) -> tuple[list[MatchupRow], list[LineupRow]]:
    """Convert one week's espn-api BoxScore list into matchups + lineup rows."""
    matchups: list[MatchupRow] = []
    lineups: list[LineupRow] = []
    for box in box_scores:
        home = getattr(box, "home_team", None)
        away = getattr(box, "away_team", None)
        home_id = int(getattr(home, "team_id", 0)) if home else 0
        away_id = int(getattr(away, "team_id", 0)) if away else None
        matchups.append(
            MatchupRow(
                week=week,
                home_espn_id=home_id,
                away_espn_id=away_id,
                home_score=float(getattr(box, "home_score", 0.0)),
                away_score=float(getattr(box, "away_score", 0.0)),
                kind="REG",
                is_bye=away is None,
            )
        )
        for team_id, lineup_attr in ((home_id, "home_lineup"), (away_id, "away_lineup")):
            if not team_id:
                continue
            for bp in getattr(box, lineup_attr, []) or []:
                lineups.append(
                    LineupRow(
                        team_espn_id=team_id,
                        week=week,
                        player=_player_ref(bp),
                        slot=_slot(getattr(bp, "slot_position", None)),
                        points=float(getattr(bp, "points", 0.0)),
                        projected_points=float(getattr(bp, "projected_points", 0.0)),
                    )
                )
    return matchups, lineups


def normalize_season(
    espn_league: Any,
    caps: EraCapabilities,
    week_box_scores: dict[int, list[Any]] | None = None,
) -> SeasonBundle:
    """Assemble a full season bundle. ``week_box_scores`` is a {week: [BoxScore]}
    map the caller fetches only when ``caps.box_scores`` is True."""
    settings = getattr(espn_league, "settings", None)
    reg_weeks = int(getattr(settings, "reg_season_count", 0) or 0)
    playoff_count = int(getattr(settings, "playoff_team_count", 0) or 0)

    matchups: list[MatchupRow] = []
    lineups: list[LineupRow] = []
    if caps.box_scores and week_box_scores:
        for week, boxes in sorted(week_box_scores.items()):
            wk_matchups, wk_lineups = normalize_week_box_scores(boxes, week)
            matchups.extend(wk_matchups)
            lineups.extend(wk_lineups)

    return SeasonBundle(
        year=int(getattr(espn_league, "year", 0)),
        scoring_settings={"name": str(getattr(settings, "name", ""))} if settings else {},
        roster_slots={},
        regular_season_weeks=reg_weeks,
        playoff_team_count=playoff_count,
        is_complete=True,
        lineups_available=caps.box_scores,
        managers=normalize_managers(espn_league),
        teams=normalize_teams(espn_league),
        draft=normalize_draft(espn_league),
        matchups=matchups,
        lineups=lineups,
    )
