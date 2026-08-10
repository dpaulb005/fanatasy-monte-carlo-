"""Ingestion port: the interface every league data source implements.

Isolating ESPN specifics behind this Protocol means an upstream API change (or
the choice of source — live ESPN vs fixtures vs synthetic) is contained to one
implementation. See docs/ARCHITECTURE.md and docs/DECISIONS.md (ADR-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from league.ingestion.schemas import SeasonBundle

# Structural boundaries in ESPN's backend (docs/DATA_SOURCES.md):
#   - the leagueHistory endpoint serves seasons <= 2017
#   - per-player weekly box scores and the activity/transaction feed are only
#     reliably available from 2019 onward.
HISTORY_ENDPOINT_MAX_YEAR = 2017
DETAILED_WEEKLY_MIN_YEAR = 2019


@dataclass(frozen=True)
class SeasonRef:
    league_id: int
    year: int


@dataclass(frozen=True)
class EraCapabilities:
    """What a given season can actually provide, per ESPN's era boundaries."""

    endpoint: str  # "current" (>=2018) or "history" (<=2017)
    box_scores: bool
    activity: bool
    transactions: bool


def capabilities_for_year(year: int) -> EraCapabilities:
    detailed = year >= DETAILED_WEEKLY_MIN_YEAR
    return EraCapabilities(
        endpoint="history" if year <= HISTORY_ENDPOINT_MAX_YEAR else "current",
        box_scores=detailed,
        activity=detailed,
        # Transactions are spotty in 2018 and unavailable earlier; treat the
        # 2019 boundary as the reliable line.
        transactions=detailed,
    )


@runtime_checkable
class LeagueDataSource(Protocol):
    """A source of normalized season data for one league."""

    def available_years(self) -> list[int]:
        """Years this source can provide, ascending."""
        ...

    def fetch_season(self, ref: SeasonRef) -> SeasonBundle:
        """Return one fully-normalized season bundle."""
        ...
