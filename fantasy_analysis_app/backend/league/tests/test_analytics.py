"""Analytics tests: hand-computed formula checks + engine invariants."""

from __future__ import annotations

import pytest

from league.analytics.engine import compute_league
from league.analytics.frames import RosterPlayerFrame
from league.analytics.lineups import optimal_points, week_efficiency
from league.analytics.luck import all_play_for_team, points_against_percentile
from league.analytics.records import longest_streaks, stddev
from league.models import ManagerCareerStats, ManagerSeasonStats

# --- Pure formula tests (hand-computed) ---


def test_all_play_expected_wins() -> None:
    # 3 teams, 2 weeks. Team 1 scores highest both weeks.
    scores = {
        1: [(1, 100.0), (2, 90.0), (3, 80.0)],
        2: [(1, 100.0), (2, 95.0), (3, 99.0)],
    }
    result = all_play_for_team(scores, team_season_id=1)
    # Team 1 beats 2 others each week => 4 all-play wins / 4 games.
    assert result.all_play_wins == 4.0
    assert result.all_play_games == 4.0
    # Won 100% of all-play over 2 weeks played => expected 2.0 wins.
    assert result.expected_wins == pytest.approx(2.0)


def test_all_play_handles_ties() -> None:
    scores = {1: [(1, 100.0), (2, 100.0), (3, 50.0)]}
    result = all_play_for_team(scores, team_season_id=1)
    # Beats team 3, ties team 2 => 1 + 0.5 = 1.5 all-play wins of 2 games.
    assert result.all_play_wins == 1.5
    assert result.expected_wins == pytest.approx(0.75)


def test_points_against_percentile() -> None:
    pa = {1: 100.0, 2: 200.0, 3: 300.0}
    assert points_against_percentile(1, pa) == 0.0  # lowest PA
    assert points_against_percentile(3, pa) == 1.0  # highest PA (unluckiest)
    assert points_against_percentile(2, pa) == 0.5


def test_optimal_lineup_uses_flex_for_best_extra() -> None:
    roster = [
        RosterPlayerFrame("QB", 30.0, "QB", True),
        RosterPlayerFrame("RB", 20.0, "RB", True),
        RosterPlayerFrame("RB", 18.0, "RB", True),
        RosterPlayerFrame("RB", 15.0, "BE", False),  # best FLEX option
        RosterPlayerFrame("WR", 12.0, "WR", True),
        RosterPlayerFrame("WR", 10.0, "WR", True),
        RosterPlayerFrame("WR", 5.0, "BE", False),
        RosterPlayerFrame("TE", 8.0, "TE", True),
        RosterPlayerFrame("DST", 7.0, "DST", True),
        RosterPlayerFrame("K", 6.0, "K", True),
    ]
    # QB30 + RB20 + RB18 + WR12 + WR10 + TE8 + FLEX(RB15) + DST7 + K6 = 126
    assert optimal_points(roster) == pytest.approx(126.0)


def test_optimal_handles_missing_positions() -> None:
    # No K, no DST -> those slots stay empty (contribute 0), still legal.
    roster = [
        RosterPlayerFrame("QB", 30.0, "QB", True),
        RosterPlayerFrame("RB", 20.0, "RB", True),
        RosterPlayerFrame("RB", 18.0, "RB", True),
        RosterPlayerFrame("WR", 12.0, "WR", True),
        RosterPlayerFrame("WR", 10.0, "WR", True),
        RosterPlayerFrame("TE", 8.0, "TE", True),
    ]
    # Dedicated slots take all RB/WR/TE, so FLEX is empty (no eligible left).
    # Total = 30 + 20 + 18 + 12 + 10 + 8 = 98
    assert optimal_points(roster) == pytest.approx(98.0)


def test_week_efficiency_never_exceeds_one() -> None:
    roster = [
        RosterPlayerFrame("QB", 30.0, "QB", True),
        RosterPlayerFrame("RB", 20.0, "BE", False),  # benched a good player
        RosterPlayerFrame("RB", 10.0, "RB", True),
        RosterPlayerFrame("RB", 8.0, "RB", True),
    ]
    actual, optimal, bench = week_efficiency(roster)
    assert actual <= optimal
    assert bench == pytest.approx(optimal - actual)


def test_longest_streaks() -> None:
    outcomes = ["W", "W", "W", "L", "L", "W", "T", "W", "W"]
    result = longest_streaks(outcomes)
    assert result.longest_win_streak == 3
    assert result.longest_lose_streak == 2


def test_stddev() -> None:
    assert stddev([10.0]) == 0.0
    assert stddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.138, abs=0.01)


# --- Engine integration tests on the synthetic league ---


@pytest.mark.django_db
def test_compute_league_produces_stats(synthetic_league) -> None:
    counts = compute_league(999999)
    assert counts["careers"] == 10
    assert counts["h2h_pairs"] == 45  # C(10,2)
    assert ManagerSeasonStats.objects.count() == 30  # 10 managers * 3 seasons


@pytest.mark.django_db
def test_all_play_is_zero_sum_per_season(synthetic_league) -> None:
    # Across a season, total actual wins must equal total expected wins:
    # all-play is symmetric, so schedule luck nets to zero league-wide.
    compute_league(999999)
    from django.db.models import Sum

    for year in (2021, 2022, 2023):
        agg = ManagerSeasonStats.objects.filter(season__year=year).aggregate(
            w=Sum("wins"), e=Sum("expected_wins")
        )
        assert agg["w"] == pytest.approx(agg["e"], abs=0.05)


@pytest.mark.django_db
def test_lineup_efficiency_within_bounds(synthetic_league) -> None:
    compute_league(999999)
    for s in ManagerSeasonStats.objects.all():
        assert 0.0 <= s.lineup_efficiency <= 1.0001
        assert s.bench_points_lost >= 0.0


@pytest.mark.django_db
def test_career_aggregates_match_seasons(synthetic_league) -> None:
    compute_league(999999)
    for career in ManagerCareerStats.objects.all():
        season_wins = sum(s.wins for s in ManagerSeasonStats.objects.filter(manager=career.manager))
        assert career.wins == season_wins
        assert career.seasons_played == 3


@pytest.mark.django_db
def test_trends_are_computed(synthetic_league) -> None:
    from league.analytics.frames import load_frames
    from league.analytics.trends import compute_trends

    trends = compute_trends(load_frames(999999))
    assert set(trends) == {"scoring_evolution", "weekly_distribution", "positional_share"}
    # Positional shares sum to ~100% each season.
    ps = trends["positional_share"]
    for i in range(len(ps["labels"])):
        total = sum(s["data"][i] for s in ps["series"])
        # Six positions each rounded to 1 decimal -> up to ~0.3 accumulated error.
        assert total == pytest.approx(100.0, abs=0.4)
    # Boxplot quartiles are ordered min <= q1 <= median <= q3 <= max.
    for box in trends["weekly_distribution"]["boxes"]:
        assert box == sorted(box)


# --- Bench losses ("games lost on the bench", P-3) ---


def _bench_loss_frames():
    from league.analytics.frames import (
        LeagueFrames,
        RosterPlayerFrame,
        TeamSeasonFrame,
        TeamWeekFrame,
    )

    def roster(bench_rb_points: float) -> list[RosterPlayerFrame]:
        return [
            RosterPlayerFrame("QB", 30.0, "QB", True),
            RosterPlayerFrame("RB", 10.0, "RB", True),
            RosterPlayerFrame("RB", bench_rb_points, "BE", False),
            RosterPlayerFrame("WR", 40.0, "WR", True),
        ]

    team = TeamSeasonFrame(
        id=1,
        season_year=2023,
        manager_ids=[100],
        manager_labels={100: "A"},
        wins=0,
        losses=2,
        ties=0,
        points_for=150.0,
        points_against=210.0,
        final_standing=2,
        made_playoffs=False,
        # Week 1: benched RB(25) would lift optimal to 105 > opp 90 -> bench loss.
        # Week 2: benched RB(5) caps optimal at 85 < opp 120 -> honest loss.
        roster_by_week={1: roster(25.0), 2: roster(5.0)},
    )
    weeks = [
        TeamWeekFrame(2023, 1, 1, 80.0, 2, 90.0, "REG", False, True, False),
        TeamWeekFrame(2023, 2, 1, 70.0, 2, 120.0, "REG", False, True, False),
    ]
    return LeagueFrames(
        league_id=1,
        team_count_by_year={2023: 2},
        team_seasons={1: team},
        team_weeks=weeks,
        scores_by_week={2023: {1: [(1, 80.0), (2, 90.0)], 2: [(1, 70.0), (2, 120.0)]}},
        draft_picks=[],
        player_season_points={},
        player_position={},
    )


def test_bench_loss_requires_legal_lineup_that_flips_result() -> None:
    from league.analytics.engine import _team_manager_season_rows

    rows = _team_manager_season_rows(_bench_loss_frames())
    assert len(rows) == 1
    row = rows[0]
    assert row["losses"] == 2
    assert row["bench_losses"] == 1  # only week 1 was winnable with a legal swap
    assert row["bench_loss_weeks"] == [
        {"week": 1, "score": 80.0, "optimal": 105.0, "opponent_score": 90.0}
    ]


@pytest.mark.django_db
def test_bench_losses_bounded_by_losses(synthetic_league) -> None:
    compute_league(999999)
    for s in ManagerSeasonStats.objects.all():
        assert s.bench_losses <= s.losses


# --- Museum of Pain (V-5) ---


def test_museum_exhibits_from_hand_frames() -> None:
    from league.analytics.museum import compute_museum

    frames = _bench_loss_frames()
    careers = {100: {"longest_lose_streak": 2}}
    museum = compute_museum(frames, careers)
    by_slug = {e["slug"]: e for e in museum["exhibits"]}

    # Closest loss is the week-1 ten-point game, from the loser's side.
    closest = by_slug["closest-loss"]["entries"][0]
    assert closest["week"] == 1
    assert closest["value"] == 10.0
    assert closest["manager"] == "A"
    # Worst bench week is week 1: the second RB slot sat EMPTY while a 25-point
    # RB rode the bench, so the whole 25 was left on the table (not a swap).
    bench = by_slug["worst-bench-week"]["entries"][0]
    assert bench["week"] == 1
    assert bench["value"] == 25.0
    # Streak exhibit carries the career number with no fake game context.
    streak = by_slug["longest-losing-streak"]["entries"][0]
    assert streak["value"] == 2
    assert streak["year"] is None


@pytest.mark.django_db
def test_museum_endpoint_serves_exhibits(synthetic_league) -> None:
    from rest_framework.test import APIClient

    compute_league(999999)
    data = APIClient().get("/api/v1/museum/").json()
    slugs = {e["slug"] for e in data["exhibits"]}
    assert {"closest-loss", "highest-score-loss", "lowest-score-win", "biggest-blowout"} <= slugs
    for exhibit in data["exhibits"]:
        assert exhibit["entries"], exhibit["slug"]
        assert len(exhibit["entries"]) <= 5
        assert exhibit["formula"]
    # And the trends endpoint does NOT leak the museum blob.
    trends = APIClient().get("/api/v1/trends/").json()
    assert "museum_of_pain" not in trends


# --- Weekly fingerprints (V-3) ---


@pytest.mark.django_db
def test_season_fingerprints_blob(synthetic_league) -> None:
    from statistics import median

    from league.analytics.frames import load_frames
    from league.analytics.trends import compute_season_fingerprints

    frames = load_frames(999999)
    fingerprints = compute_season_fingerprints(frames)
    assert set(fingerprints) == {2021, 2022, 2023}
    blob = fingerprints[2022]
    assert blob["teams"], "every season has team fingerprints"
    # Standings-ordered, one entry per team, weeks subset of season weeks.
    standings = [t["final_standing"] for t in blob["teams"]]
    assert standings == sorted(standings)
    all_scores = [w["score"] for t in blob["teams"] for w in t["weeks"]]
    assert blob["max_score"] == max(all_scores)
    assert blob["league_median"] == round(median(all_scores), 1)
    for team in blob["teams"]:
        for w in team["weeks"]:
            assert w["week"] in blob["weeks"]


@pytest.mark.django_db
def test_season_detail_includes_fingerprints(computed_league) -> None:
    from rest_framework.test import APIClient

    data = APIClient().get("/api/v1/seasons/2022/").json()
    assert data["fingerprints"] is not None
    assert data["fingerprints"]["teams"]
