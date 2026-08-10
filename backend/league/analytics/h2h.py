"""Head-to-head records between managers, accumulated over all matchups."""

from __future__ import annotations

from dataclasses import dataclass, field

from league.analytics.frames import LeagueFrames


@dataclass
class PairRecord:
    a_wins: int = 0
    b_wins: int = 0
    ties: int = 0
    a_points: float = 0.0
    b_points: float = 0.0
    playoff_meetings: int = 0
    largest_margin: float = 0.0


@dataclass
class H2HResult:
    # keyed by ordered (min_id, max_id) manager pair
    pairs: dict[tuple[int, int], PairRecord] = field(default_factory=dict)


def _iter_unique_games(frames: LeagueFrames):
    """Yield each matchup once (team_weeks stores both directions)."""
    for tw in frames.team_weeks:
        if tw.opponent_team_season_id is None:
            continue
        if tw.team_season_id < tw.opponent_team_season_id:
            yield tw


def compute_h2h(frames: LeagueFrames) -> H2HResult:
    result = H2HResult()
    for tw in _iter_unique_games(frames):
        home = frames.team_seasons.get(tw.team_season_id)
        away = frames.team_seasons.get(tw.opponent_team_season_id)
        if not home or not away:
            continue
        is_playoff = tw.kind != "REG"
        # Expand co-owned teams to every owner pair.
        for a_mgr in home.manager_ids:
            for b_mgr in away.manager_ids:
                if a_mgr == b_mgr:
                    continue
                key = (min(a_mgr, b_mgr), max(a_mgr, b_mgr))
                rec = result.pairs.setdefault(key, PairRecord())
                # Orient scores so a_* refers to key[0].
                if a_mgr == key[0]:
                    a_score, b_score = tw.score, tw.opponent_score
                else:
                    a_score, b_score = tw.opponent_score, tw.score
                rec.a_points += a_score
                rec.b_points += b_score
                if a_score > b_score:
                    rec.a_wins += 1
                elif a_score < b_score:
                    rec.b_wins += 1
                else:
                    rec.ties += 1
                if is_playoff:
                    rec.playoff_meetings += 1
                rec.largest_margin = max(rec.largest_margin, abs(a_score - b_score))
    return result
