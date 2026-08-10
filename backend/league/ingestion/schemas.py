"""Normalized ingestion schema.

Every data source (ESPN, fixtures, synthetic) emits one ``SeasonBundle`` per
season in this shape. The persister consumes only this — it never sees a
source's raw payload. This is the contract that keeps ESPN specifics isolated
(docs/ARCHITECTURE.md, ADR-005).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlayerRef:
    espn_player_id: int
    name: str
    position: str = ""
    gsis_id: str | None = None


@dataclass(frozen=True)
class ManagerRef:
    guid: str
    display_name: str = ""


@dataclass(frozen=True)
class TeamRow:
    espn_team_id: int
    team_name: str
    owner_guids: list[str]
    abbrev: str = ""
    division: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    final_standing: int = 0
    made_playoffs: bool = False


@dataclass(frozen=True)
class DraftRow:
    overall_pick: int
    round: int
    round_pick: int
    team_espn_id: int
    player: PlayerRef
    is_keeper: bool = False
    auction_price: int | None = None


@dataclass(frozen=True)
class MatchupRow:
    week: int
    home_espn_id: int
    away_espn_id: int | None
    home_score: float
    away_score: float
    kind: str = "REG"
    is_bye: bool = False


@dataclass(frozen=True)
class LineupRow:
    team_espn_id: int
    week: int
    player: PlayerRef
    slot: str
    points: float
    projected_points: float = 0.0


@dataclass(frozen=True)
class SeasonBundle:
    """Everything the persister needs for one season."""

    year: int
    scoring_settings: dict = field(default_factory=dict)
    roster_slots: dict = field(default_factory=dict)
    regular_season_weeks: int = 0
    playoff_team_count: int = 0
    is_complete: bool = True
    lineups_available: bool = True

    managers: list[ManagerRef] = field(default_factory=list)
    teams: list[TeamRow] = field(default_factory=list)
    draft: list[DraftRow] = field(default_factory=list)
    matchups: list[MatchupRow] = field(default_factory=list)
    lineups: list[LineupRow] = field(default_factory=list)
