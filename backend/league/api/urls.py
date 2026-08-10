"""API v1 URL routing."""

from __future__ import annotations

from django.urls import path

from league.api import views

app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("league/", views.league_overview, name="league-overview"),
    path("managers/", views.managers, name="managers"),
    path("managers/<int:manager_id>/", views.manager_detail, name="manager-detail"),
    path(
        "managers/<int:manager_id>/scouting/",
        views.manager_scouting,
        name="manager-scouting",
    ),
    path("seasons/<int:year>/", views.season_detail, name="season-detail"),
    path("seasons/<int:year>/draft/", views.season_draft, name="season-draft"),
    path("drafts/patterns/", views.draft_patterns, name="draft-patterns"),
    path("drafts/suggest/", views.draft_suggest, name="draft-suggest"),
    path("setup/managers/", views.setup_managers, name="setup-managers"),
    path("players/", views.players, name="players"),
    path("players/<int:espn_player_id>/", views.player_detail, name="player-detail"),
    path("trends/", views.trends, name="trends"),
    path("awards/", views.awards, name="awards"),
    path("records/", views.record_book, name="records"),
    path("museum/", views.museum, name="museum"),
    path("h2h/matrix/", views.h2h_matrix, name="h2h-matrix"),
    path("h2h/<int:a_id>/<int:b_id>/", views.h2h_pair, name="h2h-pair"),
]
