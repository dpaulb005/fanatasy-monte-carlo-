"""Django admin registrations.

Admin is the operator's write surface for data fixups — merging managers,
editing aliases, correcting the player crosswalk. Analytics tables are
registered read-only since they are rebuilt by ``compute_analytics``.
"""

from __future__ import annotations

from django.contrib import admin

from league import models


@admin.register(models.Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ("label", "display_name", "real_name", "guid")
    search_fields = ("display_name", "real_name", "guid")


@admin.register(models.Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "espn_player_id", "gsis_id")
    search_fields = ("name", "gsis_id")
    list_filter = ("position",)


@admin.register(models.Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("year", "league", "is_complete", "lineups_available")
    list_filter = ("is_complete", "lineups_available")


@admin.register(models.TeamSeason)
class TeamSeasonAdmin(admin.ModelAdmin):
    list_display = ("team_name", "season", "wins", "losses", "final_standing")
    list_filter = ("season",)
    search_fields = ("team_name", "abbrev")


@admin.register(models.SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("command", "years", "status", "started_at", "finished_at")
    list_filter = ("status", "command")
    readonly_fields = ("started_at",)


admin.site.register(models.League)
admin.site.register(models.Matchup)
admin.site.register(models.DraftPick)
admin.site.register(models.Transaction)
