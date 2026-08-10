"""Player projection ingestion (draft-time season-long), behind a source interface.

Two sources implement the same contract (mirrors ``nfl_context.py``):

- ``SyntheticProjectionSource`` derives projections from the league's own
  realized player seasons (actual points + deterministic noise), so the
  projection analytics have data with no network — and realistic residuals.
- ``fetch_sleeper_projections`` pulls real frozen preseason projections from
  Sleeper's keyless API (verified 2019-2025, see docs/autonomous/RESEARCH.md
  R-3). Undocumented endpoint → fetch once and persist (ADR persist-first);
  the app never depends on it at request time.

The Sleeper player dump maps sleeper ids to ESPN ids for a native join to
``Player`` — no name matching. Season-long rows use ``week=0``.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from league.models import DraftPick, LineupSlot, Player, PlayerProjection

SLEEPER_BASE = "https://api.sleeper.app"
SLEEPER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
# Sleeper position labels that differ from the league's canonical ones.
_SLEEPER_POS = {"DEF": "DST"}

_USER_AGENT = "fantasy-analysis-app/1.0 (personal, non-commercial)"


@dataclass(frozen=True)
class ProjectionRow:
    season: int
    week: int  # 0 = season-long draft-time projection
    source: str
    external_id: str
    player_name: str
    position: str
    espn_player_id: int | None
    games: float | None
    pts_ppr: float | None
    pts_half_ppr: float | None
    pts_std: float | None
    adp: float | None
    stats: dict = field(default_factory=dict)


class SyntheticProjectionSource:
    """Deterministic projections derived from realized league seasons.

    projection = actual season points + additive noise, so residuals are
    non-degenerate but centered — the shape the analytics expect from real
    projections (and additive noise keeps the PPR column the best scale fit,
    which multiplicative noise would not guarantee).
    """

    def __init__(self, seed: int = 7) -> None:
        self._seed = seed

    def fetch(self, league_id: int) -> list[ProjectionRow]:
        actual: dict[tuple[int, int], float] = defaultdict(float)
        for slot in LineupSlot.objects.filter(
            team_season__season__league__espn_league_id=league_id
        ).select_related("team_season__season", "player"):
            actual[(slot.team_season.season.year, slot.player.espn_player_id)] += slot.points

        rows: list[ProjectionRow] = []
        picks = (
            DraftPick.objects.filter(season__league__espn_league_id=league_id)
            .select_related("player", "season")
            .order_by("season__year", "overall_pick")
        )
        for pick in picks:
            year = pick.season.year
            pid = pick.player.espn_player_id
            rng = random.Random(self._seed + pick.id)
            points = max(0.0, actual.get((year, pid), 0.0) + rng.gauss(0.0, 25.0))
            rows.append(
                ProjectionRow(
                    season=year,
                    week=0,
                    source="synthetic",
                    external_id=str(pid),
                    player_name=pick.player.name,
                    position=pick.player.position,
                    espn_player_id=pid,
                    games=14.0,
                    pts_ppr=round(points, 1),
                    pts_half_ppr=round(points * 0.93, 1),
                    pts_std=round(points * 0.86, 1),
                    adp=float(pick.overall_pick),
                    stats={},
                )
            )
        return rows


def _http_json(url: str) -> object:
    import json
    import urllib.request  # local import: only needed for the live path

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 - fixed host
        return json.loads(resp.read().decode())


def fetch_sleeper_player_map() -> dict[str, dict]:
    """sleeper_id -> {espn_id, name, position} from the (large) players dump."""
    payload = _http_json(f"{SLEEPER_BASE}/v1/players/nfl")
    mapping: dict[str, dict] = {}
    if not isinstance(payload, dict):
        return mapping
    for sleeper_id, p in payload.items():
        if not isinstance(p, dict):
            continue
        mapping[str(sleeper_id)] = {
            "espn_id": p.get("espn_id"),
            "name": p.get("full_name")
            or " ".join(filter(None, [p.get("first_name"), p.get("last_name")])),
            "position": p.get("position") or "",
        }
    return mapping


def fetch_sleeper_projections(
    year: int, player_map: dict[str, dict] | None = None
) -> list[ProjectionRow]:
    """Frozen preseason season-long projections for one year (network)."""
    player_map = player_map or {}
    positions = "&".join(f"position[]={p}" for p in SLEEPER_POSITIONS)
    url = f"{SLEEPER_BASE}/projections/nfl/{year}?season_type=regular&{positions}&order_by=pts_ppr"
    payload = _http_json(url)
    rows: list[ProjectionRow] = []
    if not isinstance(payload, list):
        return rows
    for entry in payload:
        stats = entry.get("stats") or {}
        player = entry.get("player") or {}
        sleeper_id = str(entry.get("player_id") or "")
        if not sleeper_id or not stats.get("pts_ppr"):
            continue
        mapped = player_map.get(sleeper_id, {})
        espn_id = mapped.get("espn_id")
        position = _SLEEPER_POS.get(
            player.get("position") or mapped.get("position") or "",
            player.get("position") or mapped.get("position") or "",
        )
        name = (
            " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            or mapped.get("name")
            or sleeper_id
        )
        # Sleeper serves ADP placeholders (999) in years without real ADP.
        adp = stats.get("adp_ppr")
        if adp is not None and adp >= 900:
            adp = None
        rows.append(
            ProjectionRow(
                season=year,
                week=0,
                source="sleeper",
                external_id=sleeper_id,
                player_name=name,
                position=position,
                espn_player_id=int(espn_id) if espn_id else None,
                games=stats.get("gp"),
                pts_ppr=stats.get("pts_ppr"),
                pts_half_ppr=stats.get("pts_half_ppr"),
                pts_std=stats.get("pts_std"),
                adp=adp,
                stats={k: v for k, v in stats.items() if not k.startswith("adp_")},
            )
        )
    return rows


def persist_projections(rows: list[ProjectionRow]) -> int:
    """Idempotently replace projections per (source, season). Returns count."""
    if not rows:
        return 0
    seasons = {r.season for r in rows}
    sources = {r.source for r in rows}
    PlayerProjection.objects.filter(season__in=seasons, source__in=sources).delete()

    espn_ids = {r.espn_player_id for r in rows if r.espn_player_id}
    player_by_espn = dict(
        Player.objects.filter(espn_player_id__in=espn_ids).values_list("espn_player_id", "id")
    )
    PlayerProjection.objects.bulk_create(
        [
            PlayerProjection(
                season=r.season,
                week=r.week,
                source=r.source,
                external_id=r.external_id,
                player_name=r.player_name,
                position=r.position,
                espn_player_id=r.espn_player_id,
                player_id=player_by_espn.get(r.espn_player_id) if r.espn_player_id else None,
                games=r.games,
                pts_ppr=r.pts_ppr,
                pts_half_ppr=r.pts_half_ppr,
                pts_std=r.pts_std,
                adp=r.adp,
                stats=r.stats,
            )
            for r in rows
        ]
    )
    return len(rows)
