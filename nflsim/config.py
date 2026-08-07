"""Configuration: fantasy scoring, league setup, simulation parameters."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

# The season being projected, and the history window feeding the priors.
TARGET_SEASON = 2026

# Play-by-play window used to fit tendencies. Deep enough to be stable, recent
# enough that the rules and the offensive environment still resemble today's.
PBP_SEASONS = tuple(range(2016, TARGET_SEASON))

# Wider window for injury hazards, where events are rare and stationary.
INJURY_SEASONS = tuple(range(2015, TARGET_SEASON))

# Rookie priors are fit on every drafted skill player since 1999.
DRAFT_SEASONS = tuple(range(1999, TARGET_SEASON))

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True)
class Scoring:
    """Fantasy point values. Defaults are Full PPR, 1QB."""

    pass_yards: float = 0.04          # 1 per 25
    pass_td: float = 4.0
    interception: float = -2.0
    pass_2pt: float = 2.0

    rush_yards: float = 0.1           # 1 per 10
    rush_td: float = 6.0
    rush_2pt: float = 2.0

    reception: float = 1.0            # full PPR
    rec_yards: float = 0.1
    rec_td: float = 6.0
    rec_2pt: float = 2.0

    fumble_lost: float = -2.0

    # Milestone bonuses (0 disables). Applied per game.
    bonus_100_rush: float = 0.0
    bonus_100_rec: float = 0.0
    bonus_300_pass: float = 0.0

    name: str = "Full PPR"

    def to_dict(self) -> dict:
        return asdict(self)


PPR = Scoring()
HALF_PPR = Scoring(reception=0.5, name="Half PPR")
STANDARD = Scoring(reception=0.0, name="Standard")

SCORING_PRESETS = {"ppr": PPR, "half": HALF_PPR, "standard": STANDARD}


@dataclass(frozen=True)
class League:
    """League shape, which sets replacement level for VOR."""

    teams: int = 12
    qb: int = 1
    rb: int = 2
    wr: int = 3
    te: int = 1
    flex: int = 1           # RB/WR/TE
    superflex: int = 0      # QB/RB/WR/TE
    bench: int = 6

    def starters(self) -> dict[str, int]:
        return {"QB": self.qb, "RB": self.rb, "WR": self.wr, "TE": self.te}

    def replacement_ranks(self) -> dict[str, int]:
        """Roughly where replacement level sits for each position.

        Base starters plus a share of the flex spots, allocated the way real
        drafts actually consume them, plus a shallow bench allowance. These are
        ranks in the overall positional ordering, per league.
        """
        n = self.teams
        # Flex is overwhelmingly RB/WR in practice; TE only occasionally.
        flex_split = {"RB": 0.45, "WR": 0.45, "TE": 0.10}
        sflex_split = {"QB": 0.85, "RB": 0.05, "WR": 0.08, "TE": 0.02}
        out: dict[str, int] = {}
        for pos, base in self.starters().items():
            count = base * n
            count += self.flex * n * flex_split.get(pos, 0.0)
            count += self.superflex * n * sflex_split.get(pos, 0.0)
            out[pos] = int(round(count))
        return out


@dataclass
class SimConfig:
    """Simulation controls."""

    n_sims: int = 10_000
    seed: int = 20260807
    season: int = TARGET_SEASON

    # Injury modelling
    injuries: bool = True

    # Home field, expressed as points of scoring margin, converted internally
    # into small efficiency and pace nudges.
    home_field: float = 1.6

    # How hard to regress team and player priors toward league mean. These are
    # the shrinkage sample sizes (in plays / games) fit from history.
    chunk_games: int = 8      # games simulated per vectorised batch

    def replace(self, **kw) -> "SimConfig":
        d = asdict(self)
        d.update(kw)
        return SimConfig(**d)
