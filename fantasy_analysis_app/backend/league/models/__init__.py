"""Model package aggregator.

Django discovers models by importing ``league.models``; re-export every model
here so ``from league.models import X`` works and migrations see them all.
"""

from league.models.computed import (
    Award,
    DraftPickValue,
    HeadToHeadRecord,
    ManagerCareerStats,
    ManagerSeasonStats,
    PlayerManagerSeasonValue,
    PlayerSeasonValue,
    SeasonTrend,
)
from league.models.context import (
    ExpertRanking,
    PlayerADP,
    PlayerProjection,
    PlayerWeekStat,
    SimulationSnapshot,
)
from league.models.core import League, Manager, Player, Season, TeamSeason
from league.models.events import DraftPick, LineupSlot, Matchup, Transaction
from league.models.provenance import RawSourcePayload, SyncLog

__all__ = [
    "Award",
    "DraftPick",
    "DraftPickValue",
    "HeadToHeadRecord",
    "League",
    "LineupSlot",
    "Manager",
    "ManagerCareerStats",
    "ManagerSeasonStats",
    "Matchup",
    "Player",
    "ExpertRanking",
    "PlayerADP",
    "PlayerProjection",
    "PlayerManagerSeasonValue",
    "PlayerSeasonValue",
    "PlayerWeekStat",
    "SimulationSnapshot",
    "RawSourcePayload",
    "Season",
    "SeasonTrend",
    "SyncLog",
    "TeamSeason",
    "Transaction",
]
