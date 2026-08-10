"""Public NFL context models (nflverse + ADP).

These are league-agnostic reference data used to add context and compute
retrospective draft value. Sourced per docs/DATA_SOURCES.md.
"""

from __future__ import annotations

from django.db import models

from league.models.core import Player


class PlayerWeekStat(models.Model):
    """A player's weekly NFL production from nflverse (keyed on gsis_id)."""

    gsis_id = models.CharField(max_length=32, db_index=True)
    player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name="week_stats",
        null=True,
        blank=True,
    )
    season = models.PositiveIntegerField()
    week = models.PositiveSmallIntegerField()
    position = models.CharField(max_length=8, blank=True)
    team = models.CharField(max_length=8, blank=True)
    fantasy_points = models.FloatField(default=0.0)
    fantasy_points_ppr = models.FloatField(default=0.0)
    # Raw stat line kept as JSON so we don't model every nflverse column.
    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["gsis_id", "season", "week"], name="uniq_player_week"),
        ]
        indexes = [models.Index(fields=["season", "gsis_id"])]

    def __str__(self) -> str:
        return f"{self.gsis_id} {self.season} W{self.week}"


class PlayerADP(models.Model):
    """Average draft position for a season/format (FantasyFootballCalculator)."""

    season = models.PositiveIntegerField()
    player_name = models.CharField(max_length=200)
    position = models.CharField(max_length=8, blank=True)
    adp = models.FloatField()
    source = models.CharField(max_length=64, default="ffc")
    fmt = models.CharField(max_length=16, default="standard")

    class Meta:
        indexes = [models.Index(fields=["season", "position"])]

    def __str__(self) -> str:
        return f"{self.season} {self.player_name} ADP {self.adp}"


class PlayerProjection(models.Model):
    """A player's draft-time (week=0) or weekly projection from one source.

    Season-long rows are frozen preseason expectations (Sleeper serves them
    unrevised for past years — see docs/autonomous/RESEARCH.md R-3). The ESPN
    id crosswalk comes from the source's player dump; ``player`` resolves when
    that id matches a synced Player, but rows are kept regardless so the
    projection universe is complete.
    """

    season = models.PositiveIntegerField()
    week = models.PositiveSmallIntegerField(default=0)  # 0 = season-long
    source = models.CharField(max_length=32, default="sleeper")
    external_id = models.CharField(max_length=32)
    player_name = models.CharField(max_length=200)
    position = models.CharField(max_length=8, blank=True)
    espn_player_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        related_name="projections",
        null=True,
        blank=True,
    )
    games = models.FloatField(null=True, blank=True)
    pts_ppr = models.FloatField(null=True, blank=True)
    pts_half_ppr = models.FloatField(null=True, blank=True)
    pts_std = models.FloatField(null=True, blank=True)
    adp = models.FloatField(null=True, blank=True)
    # Raw component stat line (pass_yd, rush_att, rec, ...) for re-scoring.
    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "season", "week", "external_id"],
                name="uniq_projection_row",
            ),
        ]
        indexes = [models.Index(fields=["season", "position"])]

    def __str__(self) -> str:
        return f"{self.season} {self.player_name} proj ({self.source})"


class ExpertRanking(models.Model):
    """One player row from an operator-supplied expert cheat sheet.

    Loaded from JSON fixtures (parsed from PDFs) by ``load_expert_ranks``;
    replaced wholesale per (source, season). Bigga-style sheets carry tier /
    risk / upside per position; Flock-style sheets carry overall rank +
    consensus ADP. The suggester joins by normalized player name.
    """

    source = models.CharField(max_length=32)
    season = models.PositiveIntegerField()
    player_name = models.CharField(max_length=200)
    position = models.CharField(max_length=8, blank=True)
    team = models.CharField(max_length=8, blank=True)
    rank_overall = models.PositiveIntegerField(null=True, blank=True)
    rank_pos = models.PositiveIntegerField(null=True, blank=True)
    tier = models.CharField(max_length=8, blank=True)
    adp_overall = models.FloatField(null=True, blank=True)
    espn_rank = models.PositiveIntegerField(null=True, blank=True)
    risk = models.FloatField(null=True, blank=True)
    upside = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "season", "position", "player_name"],
                name="uniq_expert_rank_row",
            ),
        ]
        indexes = [models.Index(fields=["season", "source"])]

    def __str__(self) -> str:
        return f"{self.season} {self.player_name} ({self.source})"


class SimulationSnapshot(models.Model):
    """Imported nflsim analysis artifact, kept off the request-time compute path."""

    source = models.CharField(max_length=32, default="nflsim")
    schema_version = models.PositiveSmallIntegerField()
    season = models.PositiveIntegerField()
    scoring = models.CharField(max_length=64)
    league_teams = models.PositiveSmallIntegerField()
    simulations = models.PositiveIntegerField()
    generated_at = models.DateTimeField()
    imported_at = models.DateTimeField(auto_now=True)
    checksum = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "season", "scoring", "league_teams"],
                name="uniq_simulation_snapshot",
            ),
        ]
        indexes = [
            models.Index(
                fields=["season", "league_teams"], name="league_simu_season_37699e_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.source} {self.season} {self.scoring} ({self.simulations:,} sims)"
