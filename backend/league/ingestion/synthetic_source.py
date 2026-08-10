"""A ``LeagueDataSource`` backed by the deterministic synthetic generator.

Lets the real ``sync_espn`` orchestration run end-to-end (skip logic, SyncLog,
persistence) with no ESPN credentials — used in dev and tests.
"""

from __future__ import annotations

from league.ingestion.ports import SeasonRef
from league.ingestion.schemas import SeasonBundle
from league.ingestion.synthetic import DEFAULT_SEASONS, generate_season


class SyntheticSource:
    def __init__(self, years: list[int] | None = None) -> None:
        self._years = sorted(years or DEFAULT_SEASONS)

    def available_years(self) -> list[int]:
        return list(self._years)

    def fetch_season(self, ref: SeasonRef) -> SeasonBundle:
        return generate_season(ref.year)
