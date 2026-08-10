"""Computed analytics tables.

These are pure derivations of the source tables, rebuilt in full by the
``compute_analytics`` command (truncate-and-rebuild). They exist so API reads
are indexed lookups rather than per-request aggregation. Never written by the
ingestion path. See docs/METRICS_CATALOG.md for every formula.
"""

from __future__ import annotations

from django.db import models

from league.models.core import Manager, Player, Season, TeamSeason
from league.models.events import DraftPick


class ManagerSeasonStats(models.Model):
    """Per-manager, per-season computed metrics."""

    manager = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name="season_stats")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="manager_stats")
    team_season = models.ForeignKey(
        TeamSeason, on_delete=models.CASCADE, related_name="manager_stats"
    )

    wins = models.PositiveSmallIntegerField(default=0)
    losses = models.PositiveSmallIntegerField(default=0)
    ties = models.PositiveSmallIntegerField(default=0)
    points_for = models.FloatField(default=0.0)
    points_against = models.FloatField(default=0.0)

    all_play_wins = models.FloatField(default=0.0)
    all_play_games = models.FloatField(default=0.0)
    expected_wins = models.FloatField(default=0.0)
    luck_delta = models.FloatField(default=0.0)
    points_against_percentile = models.FloatField(default=0.0)

    weekly_score_stddev = models.FloatField(default=0.0)
    optimal_points = models.FloatField(default=0.0)
    bench_points_lost = models.FloatField(default=0.0)
    lineup_efficiency = models.FloatField(default=0.0)
    # Losses where a legal alternate lineup from that week's roster would have
    # beaten the opponent's actual score (0 for eras without lineup data).
    bench_losses = models.PositiveSmallIntegerField(default=0)

    final_standing = models.PositiveSmallIntegerField(default=0)
    made_playoffs = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["manager", "season"], name="uniq_manager_season_stats"),
        ]

    def __str__(self) -> str:
        return f"{self.manager.label} {self.season.year}"


class ManagerCareerStats(models.Model):
    """One row per manager: career aggregates + one-off records in ``extras``."""

    manager = models.OneToOneField(Manager, on_delete=models.CASCADE, related_name="career_stats")
    seasons_played = models.PositiveSmallIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    ties = models.PositiveIntegerField(default=0)
    championships = models.PositiveSmallIntegerField(default=0)
    playoff_appearances = models.PositiveSmallIntegerField(default=0)
    sackos = models.PositiveSmallIntegerField(default=0)
    total_points_for = models.FloatField(default=0.0)
    total_luck_delta = models.FloatField(default=0.0)
    longest_win_streak = models.PositiveSmallIntegerField(default=0)
    longest_lose_streak = models.PositiveSmallIntegerField(default=0)
    extras = models.JSONField(default=dict, blank=True)

    @property
    def win_pct(self) -> float:
        games = self.wins + self.losses + self.ties
        return (self.wins + 0.5 * self.ties) / games if games else 0.0

    def __str__(self) -> str:
        return f"{self.manager.label} career"


class HeadToHeadRecord(models.Model):
    """Ordered manager pair (a_id < b_id) with both directions of the record."""

    manager_a = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name="h2h_as_a")
    manager_b = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name="h2h_as_b")
    a_wins = models.PositiveSmallIntegerField(default=0)
    b_wins = models.PositiveSmallIntegerField(default=0)
    ties = models.PositiveSmallIntegerField(default=0)
    a_points = models.FloatField(default=0.0)
    b_points = models.FloatField(default=0.0)
    playoff_meetings = models.PositiveSmallIntegerField(default=0)
    largest_margin = models.FloatField(default=0.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["manager_a", "manager_b"], name="uniq_h2h_pair"),
        ]

    def __str__(self) -> str:
        return f"{self.manager_a.label} vs {self.manager_b.label}"


class DraftPickValue(models.Model):
    """Retrospective value grade for a single draft pick."""

    draft_pick = models.OneToOneField(DraftPick, on_delete=models.CASCADE, related_name="value")
    season_points = models.FloatField(default=0.0)
    points_over_replacement = models.FloatField(default=0.0)
    adp = models.FloatField(null=True, blank=True)
    adp_delta = models.FloatField(null=True, blank=True)
    round_expectation_delta = models.FloatField(default=0.0)

    def __str__(self) -> str:
        return f"value({self.draft_pick})"


class PlayerSeasonValue(models.Model):
    """Per-player, per-season fantasy value while rostered in this league.

    Derived from LineupSlot only, so it covers started AND benched weeks but
    never free agents ("points while rostered", not NFL totals). Replacement
    level and the rostered-player pool match the draft-value definition in
    ``analytics/drafts.py`` so the league has one replacement concept.
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="season_values")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="player_values")
    position = models.CharField(max_length=16, blank=True, default="")

    total_points = models.FloatField(default=0.0)
    started_points = models.FloatField(default=0.0)
    bench_points = models.FloatField(default=0.0)
    weeks_rostered = models.PositiveSmallIntegerField(default=0)
    weeks_started = models.PositiveSmallIntegerField(default=0)
    points_over_replacement = models.FloatField(default=0.0)
    # 1 = highest total_points within (season, position) among rostered players.
    position_rank = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["player", "season"], name="uniq_player_season_value"),
        ]
        indexes = [models.Index(fields=["season", "position"])]

    def __str__(self) -> str:
        return f"{self.player.name} {self.season.year}"


class PlayerManagerSeasonValue(models.Model):
    """A player's production attributed to one manager for one season.

    Weekly attribution: a manager is credited only for weeks the player sat on
    a team they manage, so mid-season moves split cleanly and per-manager rows
    sum to the player's PlayerSeasonValue totals. Co-managed teams credit each
    listed manager with the same team-weeks (consistent with career stats).
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="manager_values")
    manager = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name="player_values")
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="player_manager_values"
    )

    total_points = models.FloatField(default=0.0)
    started_points = models.FloatField(default=0.0)
    bench_points = models.FloatField(default=0.0)
    weeks_rostered = models.PositiveSmallIntegerField(default=0)
    weeks_started = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["player", "manager", "season"],
                name="uniq_player_manager_season_value",
            ),
        ]
        indexes = [models.Index(fields=["manager", "season"])]

    def __str__(self) -> str:
        return f"{self.player.name} → {self.manager.label} {self.season.year}"


class SeasonTrend(models.Model):
    """Chart-shaped JSON blob for one metric of one season (or all-time)."""

    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="trends",
        null=True,
        blank=True,
    )
    key = models.CharField(max_length=64)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "key"], name="uniq_season_trend"),
        ]

    def __str__(self) -> str:
        return f"{self.key} ({self.season.year if self.season else 'all-time'})"


class Award(models.Model):
    """A superlative/award for a season (or ALL_TIME), with the data behind it."""

    season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="awards",
        null=True,
        blank=True,
    )
    slug = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    winner = models.ForeignKey(
        Manager,
        on_delete=models.CASCADE,
        related_name="awards",
        null=True,
        blank=True,
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name="awards",
        null=True,
        blank=True,
    )
    value = models.FloatField(default=0.0)
    # The matchup/pick/week behind the award, so narratives cite real data.
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "slug"], name="uniq_award"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.season.year if self.season else 'all-time'})"
