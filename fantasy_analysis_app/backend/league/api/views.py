"""Read-only API views over precomputed analytics tables.

Views are thin readers: all shaping lives in ``selectors`` and all analytics are
precomputed at sync time. Every endpoint is a cheap indexed lookup.
"""

from __future__ import annotations

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from league.api import selectors, setup, suggester


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request: Request) -> Response:
    """Liveness + DB connectivity probe for local dev and CI."""
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - report degraded rather than 500
        db_ok = False

    return Response(
        {
            "status": "ok" if db_ok else "degraded",
            "service": "fantasy-analysis-api",
            "version": "v1",
            "database": "ok" if db_ok else "unavailable",
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def league_overview(_request: Request) -> Response:
    return Response(selectors.league_overview())


@api_view(["GET"])
@permission_classes([AllowAny])
def managers(_request: Request) -> Response:
    return Response(selectors.manager_career_table())


@api_view(["GET"])
@permission_classes([AllowAny])
def manager_detail(_request: Request, manager_id: int) -> Response:
    return Response(selectors.manager_profile(manager_id))


@api_view(["GET"])
@permission_classes([AllowAny])
def season_detail(_request: Request, year: int) -> Response:
    return Response(selectors.season_detail(year))


@api_view(["GET"])
@permission_classes([AllowAny])
def season_draft(_request: Request, year: int) -> Response:
    return Response(selectors.season_draft(year))


@api_view(["GET"])
@permission_classes([AllowAny])
def trends(_request: Request) -> Response:
    return Response(selectors.league_trends())


@api_view(["GET"])
@permission_classes([AllowAny])
def awards(_request: Request) -> Response:
    return Response(selectors.awards())


@api_view(["GET"])
@permission_classes([AllowAny])
def record_book(_request: Request) -> Response:
    return Response(selectors.record_book())


@api_view(["GET"])
@permission_classes([AllowAny])
def h2h_matrix(_request: Request) -> Response:
    return Response(selectors.h2h_matrix())


@api_view(["GET"])
@permission_classes([AllowAny])
def h2h_pair(_request: Request, a_id: int, b_id: int) -> Response:
    return Response(selectors.h2h_pair(a_id, b_id))


def _int_param(request: Request, name: str, default: int | None) -> int | None:
    """Parse an optional integer query param; malformed input is a 400, not a 500."""
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError({name: "must be an integer"}) from exc


@api_view(["GET"])
@permission_classes([AllowAny])
def players(request: Request) -> Response:
    limit = _int_param(request, "limit", 100)
    return Response(
        selectors.players_index(
            season=_int_param(request, "season", None),
            position=request.query_params.get("position", ""),
            sort=request.query_params.get("sort", "por"),
            query=request.query_params.get("q", ""),
            limit=limit if limit is not None else 100,
        )
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def player_detail(_request: Request, espn_player_id: int) -> Response:
    return Response(selectors.player_detail(espn_player_id))


@api_view(["GET"])
@permission_classes([AllowAny])
def draft_patterns(_request: Request) -> Response:
    return Response(selectors.draft_patterns())


@api_view(["GET"])
@permission_classes([AllowAny])
def museum(_request: Request) -> Response:
    return Response(selectors.museum_of_pain())


@api_view(["GET"])
@permission_classes([AllowAny])
def manager_scouting(_request: Request, manager_id: int) -> Response:
    return Response(selectors.manager_scouting(manager_id))


@api_view(["GET"])
@permission_classes([AllowAny])
def draft_suggest(request: Request) -> Response:
    pick = _int_param(request, "pick", 1)
    limit = _int_param(request, "limit", None)
    return Response(
        suggester.draft_suggestions(
            pick=pick if pick is not None else 1,
            teams=_int_param(request, "teams", None),
            slot=_int_param(request, "slot", None),
            position=request.query_params.get("position") or None,
            limit=limit if limit is not None else suggester.DEFAULT_LIMIT,
            simulate=request.query_params.get("simulate") in ("1", "true"),
            roster=request.query_params.getlist("roster"),
        )
    )


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def setup_managers(request: Request) -> Response:
    """Manager setup: GET the inventory + predictions, POST corrections.

    The API's one write surface (ADR-011) — operator-only identity fields
    (real_name, email, merge pointer), same trust model as the Django admin
    on this private, self-hosted app."""
    if request.method == "POST":
        return Response(setup.apply_manager_setup(request.data))
    return Response(setup.setup_managers())
