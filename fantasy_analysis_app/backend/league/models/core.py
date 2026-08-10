"""Core identity models.

The ``Manager`` is the first-class cross-season entity (keyed on the stable
ESPN SWID GUID); ``TeamSeason`` is its per-year instantiation. Everything else
hangs off these. See docs/ARCHITECTURE.md and docs/DECISIONS.md (ADR-009).
"""

from __future__ import annotations

from django.db import models


class League(models.Model):
    """A single ESPN league. Usually one row; modelled to allow more later."""

    espn_league_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name or f"League {self.espn_league_id}"


class Season(models.Model):
    """One year of a league. Scoring/roster settings vary by year, so they are
    stored per season as JSON blobs alongside a few hot columns."""

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="seasons")
    year = models.PositiveIntegerField()

    scoring_settings = models.JSONField(default=dict, blank=True)
    roster_slots = models.JSONField(default=dict, blank=True)
    regular_season_weeks = models.PositiveSmallIntegerField(default=0)
    playoff_team_count = models.PositiveSmallIntegerField(default=0)

    is_complete = models.BooleanField(default=False)
    # Per-player weekly detail (box scores) is only reliably available from
    # 2019 onward; older seasons degrade to summary analytics.
    lineups_available = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["league", "year"], name="uniq_league_year"),
        ]
        ordering = ["-year"]

    def __str__(self) -> str:
        return f"{self.year} season"


class Manager(models.Model):
    """A human league member, tracked across every season they played.

    Keyed on the ESPN SWID GUID, which is stable across team renames and
    display-name changes. ``real_name`` is an admin-editable alias used to
    merge/relabel accounts.
    """

    guid = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    real_name = models.CharField(max_length=200, blank=True)
    # Operator-entered: ESPN never exposes member emails, so this is filled in
    # on the Setup page (or admin), never by sync.
    email = models.EmailField(blank=True)
    # Identity continuity: a human with a second ESPN account is merged into
    # their canonical Manager row via the merge_managers command (operator-run,
    # never automatic). Analytics resolve through this link at compute time;
    # source data (TeamSeason.managers) is never rewritten. One level only —
    # the command refuses chains.
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_from",
    )

    def __str__(self) -> str:
        return self.real_name or self.display_name or self.guid

    @property
    def label(self) -> str:
        return self.real_name or self.display_name or self.guid

    @property
    def canonical(self) -> Manager:
        """The manager analytics should attribute to (self unless merged)."""
        return self.merged_into or self


class Player(models.Model):
    """An NFL player as seen by ESPN, with an optional crosswalk to nflverse."""

    espn_player_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=200)
    position = models.CharField(max_length=8, blank=True)
    # Canonical nflverse key (gsis_id); nullable until the crosswalk resolves it.
    gsis_id = models.CharField(max_length=32, blank=True, null=True, db_index=True)

    def __str__(self) -> str:
        return self.name


class TeamSeason(models.Model):
    """A team as it existed in one season, owned by one or more managers."""

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="team_seasons")
    espn_team_id = models.PositiveIntegerField()
    team_name = models.CharField(max_length=200, blank=True)
    abbrev = models.CharField(max_length=16, blank=True)
    division = models.CharField(max_length=100, blank=True)

    managers = models.ManyToManyField(Manager, related_name="team_seasons")

    wins = models.PositiveSmallIntegerField(default=0)
    losses = models.PositiveSmallIntegerField(default=0)
    ties = models.PositiveSmallIntegerField(default=0)
    points_for = models.FloatField(default=0.0)
    points_against = models.FloatField(default=0.0)
    final_standing = models.PositiveSmallIntegerField(default=0)
    made_playoffs = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "espn_team_id"], name="uniq_season_team"),
        ]

    def __str__(self) -> str:
        return f"{self.team_name} ({self.season.year})"
