"""Public NFL context ingestion (ADP), behind a source interface.

Two sources implement the same contract:

- ``SyntheticADPSource`` derives ADP from the league's own drafts (adp ≈ overall
  pick + deterministic noise) so the draft steal/reach analytics have data with
  no network. Used in dev and tests.
- ``FfcADPSource`` pulls real historical ADP from FantasyFootballCalculator
  (free JSON API, 2014+, see docs/DATA_SOURCES.md). It requires network access
  and is an operator step; it is intentionally not exercised in CI.

Player weekly stats via nflverse/`nflreadpy` are a further optional enrichment
(gsis_id crosswalk); the league-only draft-value analytics do not require them,
so that loader is deferred until a demonstrated need.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from league.models import DraftPick, PlayerADP


@dataclass(frozen=True)
class ADPRow:
    season: int
    player_name: str
    position: str
    adp: float
    source: str
    fmt: str


class SyntheticADPSource:
    """Deterministic ADP derived from the league's persisted drafts."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def fetch(self, league_id: int) -> list[ADPRow]:
        rows: list[ADPRow] = []
        picks = (
            DraftPick.objects.filter(season__league__espn_league_id=league_id)
            .select_related("player", "season")
            .order_by("season__year", "overall_pick")
        )
        for pick in picks:
            # Deterministic per-pick jitter around the actual draft slot.
            rng = random.Random(self._seed + pick.id)
            noise = rng.gauss(0, 4)
            adp = max(1.0, round(pick.overall_pick + noise, 1))
            rows.append(
                ADPRow(
                    season=pick.season.year,
                    player_name=pick.player.name,
                    position=pick.player.position,
                    adp=adp,
                    source="synthetic",
                    fmt="standard",
                )
            )
        return rows


def fetch_ffc_adp(year: int, fmt: str = "standard", teams: int = 12) -> list[ADPRow]:
    """Fetch real historical ADP from FantasyFootballCalculator.

    Operator step (network required). Behind a function so the HTTP dependency
    is isolated; not called in CI. See docs/DATA_SOURCES.md for the endpoint and
    terms. Returns the same ADPRow shape as the synthetic source.
    """
    import json
    import urllib.request  # local import: only needed for the live path

    url = f"https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={year}"
    # FFC (Cloudflare) rejects urllib's default Python User-Agent with a 403.
    request = urllib.request.Request(
        url, headers={"User-Agent": "fantasy-analysis-app/1.0 (personal, non-commercial)"}
    )
    with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310 - fixed host
        payload = json.loads(resp.read().decode())
    rows: list[ADPRow] = []
    for p in payload.get("players", []):
        rows.append(
            ADPRow(
                season=year,
                player_name=str(p.get("name", "")),
                position=str(p.get("position", "")),
                adp=float(p.get("adp", 0.0)),
                source="ffc",
                fmt=fmt,
            )
        )
    return rows


def persist_adp(rows: list[ADPRow]) -> int:
    """Idempotently upsert ADP rows. Returns the count written."""
    seasons = {r.season for r in rows}
    PlayerADP.objects.filter(season__in=seasons, source__in={r.source for r in rows}).delete()
    PlayerADP.objects.bulk_create(
        [
            PlayerADP(
                season=r.season,
                player_name=r.player_name,
                position=r.position,
                adp=r.adp,
                source=r.source,
                fmt=r.fmt,
            )
            for r in rows
        ]
    )
    return len(rows)
