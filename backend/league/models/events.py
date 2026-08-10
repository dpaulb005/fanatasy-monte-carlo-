"""Event models: the raw record of what happened in each season.

Matchups, draft picks, weekly lineup slots, and transactions. ``LineupSlot`` is
the high-volume workhorse table behind bench/optimal-lineup analytics.
"""

from __future__ import annotations

from django.db import models

from league.models.core import Player, Season, TeamSeason


class Matchup(models.Model):
    """One head-to-head game in a week. Typed so playoff/consolation games are
    distinguishable from regular-season ones."""

    class Kind(models.TextChoices):
        REGULAR = "REG", "Regular season"
        PLAYOFF = "PLAYOFF", "Playoff"
        CONSOLATION = "CONSOLATION", "Consolation"
        CHAMPIONSHIP = "CHAMPIONSHIP", "Championship"
        TOILET_BOWL = "TOILET_BOWL", "Toilet bowl"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="matchups")
    week = models.PositiveSmallIntegerField()
    home = models.ForeignKey(TeamSeason, on_delete=models.CASCADE, related_name="home_matchups")
    away = models.ForeignKey(
        TeamSeason,
        on_delete=models.CASCADE,
        related_name="away_matchups",
        null=True,
        blank=True,
    )
    home_score = models.FloatField(default=0.0)
    away_score = models.FloatField(default=0.0)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.REGULAR)
    is_bye = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["season", "week", "home"], name="uniq_matchup_home_week"
            ),
        ]
        indexes = [models.Index(fields=["season", "week"])]

    def __str__(self) -> str:
        return f"W{self.week} {self.season.year}: {self.home_score}-{self.away_score}"


class DraftPick(models.Model):
    """One selection in a season's draft."""

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="draft_picks")
    team_season = models.ForeignKey(
        TeamSeason, on_delete=models.CASCADE, related_name="draft_picks"
    )
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="draft_picks")
    round = models.PositiveSmallIntegerField()
    round_pick = models.PositiveSmallIntegerField()
    overall_pick = models.PositiveSmallIntegerField()
    is_keeper = models.BooleanField(default=False)
    auction_price = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["season", "overall_pick"], name="uniq_draft_overall"),
        ]
        ordering = ["season", "overall_pick"]

    def __str__(self) -> str:
        return f"{self.season.year} R{self.round}.{self.round_pick} {self.player.name}"


class LineupSlot(models.Model):
    """A player's weekly slot on a team (started or benched) with points.

    High-volume: team × week × roster-size rows. The source of truth for bench
    points, optimal lineup, and coaching efficiency. Only populated for seasons
    with ``lineups_available`` (2019+).
    """

    class Slot(models.TextChoices):
        QB = "QB", "QB"
        RB = "RB", "RB"
        WR = "WR", "WR"
        TE = "TE", "TE"
        FLEX = "FLEX", "FLEX"
        DST = "DST", "D/ST"
        K = "K", "K"
        BENCH = "BE", "Bench"
        IR = "IR", "IR"
        OTHER = "OTHER", "Other"

    team_season = models.ForeignKey(
        TeamSeason, on_delete=models.CASCADE, related_name="lineup_slots"
    )
    week = models.PositiveSmallIntegerField()
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="lineup_slots")
    slot = models.CharField(max_length=8, choices=Slot.choices, default=Slot.OTHER)
    points = models.FloatField(default=0.0)
    projected_points = models.FloatField(default=0.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_season", "week", "player"], name="uniq_lineup_slot"
            ),
        ]
        indexes = [models.Index(fields=["week", "slot"])]

    @property
    def started(self) -> bool:
        return self.slot not in {self.Slot.BENCH, self.Slot.IR}

    def __str__(self) -> str:
        return f"W{self.week} {self.player.name} [{self.slot}] {self.points}"


class Transaction(models.Model):
    """A roster move (best-effort; sparse or unavailable for pre-2019 seasons)."""

    class Kind(models.TextChoices):
        ADD = "ADD", "Add"
        DROP = "DROP", "Drop"
        TRADE = "TRADE", "Trade"
        WAIVER = "WAIVER", "Waiver"
        OTHER = "OTHER", "Other"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="transactions")
    team_season = models.ForeignKey(
        TeamSeason,
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    week = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OTHER)
    bid_amount = models.PositiveIntegerField(null=True, blank=True)
    # Players involved, stored as a small JSON list of {espn_player_id, name}.
    players = models.JSONField(default=list, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["season", "week"])]

    def __str__(self) -> str:
        return f"{self.season.year} W{self.week} {self.kind}"
