import numpy as np
import pandas as pd
import pytest

from nflsim.room import flags, league_table, recency_weights, room_health


def _roster(members):
    """members: list of (player_id, pct) in depth order."""
    return pd.DataFrame([
        {"season": 2025, "team": "NYG", "position": "RB",
         "player_id": pid, "pct": pct, "depth": i + 1}
        for i, (pid, pct) in enumerate(members)
    ])


def _played(weeks):
    return pd.DataFrame({"season": 2025, "team": "NYG", "week": list(weeks)})


def _active(rows):
    return pd.DataFrame([{"season": 2025, "week": w, "gsis_id": p}
                         for w, p in rows])


def _get(grid, week, pid, col):
    m = (grid.week == week) & (grid.player_id == pid)
    return float(grid.loc[m, col].iloc[0])


def test_a_player_who_did_not_dress_counts_as_absent():
    """Regression: the first version left-joined availability onto games that
    happened, so a player with no snap row simply vanished from his room and
    every room read as fully healthy (98.9% of player-weeks)."""
    roster = _roster([("starter", 0.7), ("backup", 0.3)])
    # Week 2 has no row for the starter at all -- he was inactive.
    active = _active([(1, "starter"), (1, "backup"), (2, "backup")])
    grid = room_health(roster, _played([1, 2]), active)

    assert _get(grid, 1, "backup", "ahead_ok") == pytest.approx(1.0)
    assert _get(grid, 2, "backup", "ahead_ok") == pytest.approx(0.0)
    assert _get(grid, 2, "backup", "room_ok") == pytest.approx(0.0)


def test_the_starter_sees_the_room_behind_him_empty():
    """The case an upward-only measure cannot see: a lead back with nobody
    ahead of him absorbs the committee's work when the committee is out."""
    roster = _roster([("lead", 0.7), ("second", 0.2), ("third", 0.1)])
    active = _active([(1, "lead"), (1, "second"), (1, "third"),
                      (2, "lead"), (2, "third")])
    grid = room_health(roster, _played([1, 2]), active)

    assert _get(grid, 1, "lead", "behind_ok") == pytest.approx(1.0)
    # Week 2 loses the second back: 0.1 of 0.3 behind him is still on the field.
    assert _get(grid, 2, "lead", "behind_ok") == pytest.approx(1 / 3)
    # Nobody is ahead of the lead back, which is healthy by definition, not zero.
    assert _get(grid, 2, "lead", "ahead_ok") == pytest.approx(1.0)


def test_room_health_is_weighted_by_snap_rate_not_headcount():
    """Losing a team's second back is not the same event as losing its fifth."""
    roster = _roster([("lead", 0.6), ("second", 0.35), ("scrub", 0.05)])
    lose_second = room_health(roster, _played([1]),
                              _active([(1, "lead"), (1, "scrub")]))
    lose_scrub = room_health(roster, _played([1]),
                             _active([(1, "lead"), (1, "second")]))
    a = _get(lose_second, 1, "lead", "behind_ok")
    b = _get(lose_scrub, 1, "lead", "behind_ok")
    assert a == pytest.approx(0.05 / 0.40)
    assert b == pytest.approx(0.35 / 0.40)
    assert a < b


def test_bye_weeks_are_not_injuries():
    """A team that did not play is not a team whose players were hurt -- the
    same mistake that once pinned every injury hazard at its clip ceiling."""
    roster = _roster([("lead", 0.7), ("backup", 0.3)])
    # Weeks 1 and 3 played; week 2 is the bye and appears nowhere.
    grid = room_health(roster, _played([1, 3]),
                       _active([(1, "lead"), (1, "backup"),
                                (3, "lead"), (3, "backup")]))
    assert sorted(grid.week.unique()) == [1, 3]
    assert (grid.room_ok == 1.0).all()


def test_a_one_man_room_is_healthy_not_undefined():
    roster = _roster([("solo", 0.8)])
    grid = room_health(roster, _played([1]), _active([(1, "solo")]))
    assert _get(grid, 1, "solo", "room_ok") == pytest.approx(1.0)
    assert _get(grid, 1, "solo", "behind_ok") == pytest.approx(1.0)


def test_recency_weights_match_fit_usage():
    w = recency_weights([2022, 2023, 2024, 2025], target=2026, halflife=1.1)
    assert w[-1] == pytest.approx(1.0)          # the season just finished
    assert w[-2] / w[-1] == pytest.approx(0.5 ** (1 / 1.1))
    assert (np.diff(w) > 0).all()


# --------------------------------------------------------------------------
# Flagging
# --------------------------------------------------------------------------

def _split(**kw):
    base = {"name": ["A"], "pos": ["RB"], "team": ["NYG"], "depth": [1.0],
            "games": [16], "healthy_games": [8], "pooled": [0.30],
            "healthy_share": [0.20], "depleted_share": [0.40],
            "inflation": [0.10]}
    base.update(kw)
    return pd.DataFrame(base)


def test_flags_require_enough_games_with_a_whole_room():
    """Without the healthy-games floor, `inflation` is computed against a
    number that rests on one or two games and means nothing."""
    assert len(flags(_split())) == 1
    assert len(flags(_split(healthy_games=[1]))) == 0
    assert len(flags(_split(games=[4], healthy_games=[3]))) == 0
    assert len(flags(_split(inflation=[0.001]))) == 0


def test_flags_drop_players_never_seen_with_a_whole_room():
    assert len(flags(_split(healthy_share=[np.nan], inflation=[np.nan]))) == 0


def test_league_table_needs_games_both_ways():
    # 16 games, 15 of them healthy: only one depleted game, so the depleted
    # mean is a single observation and the row is excluded.
    assert len(league_table(_split(healthy_games=[15]))) == 0
    assert len(league_table(_split(healthy_games=[8]))) == 1
