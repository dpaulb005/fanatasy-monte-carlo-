"""``LeagueDataSource`` backed by the ``espn-api`` package.

Wraps the unofficial ESPN client. All ESPN-specific behaviour (auth, endpoint
era split, box-score fetching, politeness) lives here so the rest of the app
never imports ``espn-api``. Requires the user's own ESPN_S2 + SWID cookies.

``espn-api`` is an optional dependency: importing this module does not import
it; the package is only imported when a fetch actually runs, so the rest of the
app (and the fixture/synthetic path) works without it installed.
"""

from __future__ import annotations

from typing import Any

from league.ingestion.espn_normalize import normalize_season
from league.ingestion.politeness import Politeness
from league.ingestion.ports import SeasonRef, capabilities_for_year
from league.ingestion.schemas import SeasonBundle


class EspnApiSource:
    def __init__(
        self,
        league_id: int,
        espn_s2: str = "",
        swid: str = "",
        years: list[int] | None = None,
        politeness: Politeness | None = None,
    ) -> None:
        # Cookies are optional: public leagues read without them. A private
        # league with no cookies surfaces ESPNAccessDenied at fetch time, which
        # run_sync records on the SyncLog. One of ESPN_S2/SWID without the other
        # is almost always a copy/paste mistake, so reject that early.
        if bool(espn_s2) != bool(swid):
            raise ValueError(
                "Provide BOTH ESPN_S2 and SWID cookies (or neither, for a public "
                "league). See docs/DATA_SOURCES.md#authentication-cookies."
            )
        self.league_id = league_id
        self._espn_s2 = espn_s2
        self._swid = swid
        self._years = sorted(years or [])
        self._politeness = politeness or Politeness()

    def available_years(self) -> list[int]:
        return list(self._years)

    def _build_league(self, year: int) -> Any:
        # Lazy import so the package is only needed when a real sync runs.
        from espn_api.football import League  # type: ignore[import-not-found]

        return League(
            league_id=self.league_id,
            year=year,
            espn_s2=self._espn_s2 or None,
            swid=self._swid or None,
        )

    def fetch_season(self, ref: SeasonRef) -> SeasonBundle:
        caps = capabilities_for_year(ref.year)
        espn_league = self._politeness.call(lambda: self._build_league(ref.year))

        week_box_scores: dict[int, list[Any]] = {}
        if caps.box_scores:
            settings = getattr(espn_league, "settings", None)
            reg_weeks = int(getattr(settings, "reg_season_count", 0) or 0)
            for week in range(1, reg_weeks + 1):
                self._politeness.pause()

                def fetch_week(w: int = week) -> list[Any]:
                    return list(espn_league.box_scores(w))

                week_box_scores[week] = self._politeness.call(fetch_week)

        return normalize_season(espn_league, caps, week_box_scores)
