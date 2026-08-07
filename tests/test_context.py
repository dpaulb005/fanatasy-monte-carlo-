import pandas as pd
import pytest

from nflsim.build import _age
from nflsim.backtest import _actual_games_from_snaps, add_error_decomposition
from nflsim.priors import _roster_continuity_from_frames


def test_age_uses_the_projected_season_not_global_target():
    age_2024 = _age("2000-09-01", season=2024)
    age_2026 = _age("2000-09-01", season=2026)
    assert age_2024 == pytest.approx(24.0, abs=0.01)
    assert age_2026 == pytest.approx(26.0, abs=0.01)


def test_roster_continuity_does_not_credit_players_who_changed_teams():
    snaps = pd.DataFrame({
        "pfr_player_id": ["stay", "moved", "other"],
        "team": ["AAA", "AAA", "BBB"],
        "offense_snaps": [60, 40, 100],
    })
    previous = pd.DataFrame({
        "pfr_id": ["stay", "moved", "other"],
        "gsis_id": ["g1", "g2", "g3"],
        "team": ["AAA", "AAA", "BBB"],
    })
    current = pd.DataFrame({
        "gsis_id": ["g1", "g2", "g3"],
        "team": ["AAA", "CCC", "BBB"],
    })

    result = _roster_continuity_from_frames(snaps, previous, current)
    assert result == {"AAA": 0.6, "BBB": 1.0}


def test_error_decomposition_sums_exactly_to_total_error():
    frame = pd.DataFrame({
        "games": [17.0, 12.0], "actual_games": [12.0, 17.0],
        "points": [255.0, 120.0], "actual": [144.0, 204.0],
    })
    out = add_error_decomposition(frame)
    combined = out.health_error + out.rate_error
    assert (combined - (out.points - out.actual)).abs().max() < 1e-10


def test_actual_games_include_zero_touch_snap_appearances():
    snaps = pd.DataFrame({
        "pfr_player_id": ["wr", "wr", "wr"],
        "game_id": ["g1", "g2", "g3"],
        "offense_snaps": [40, 22, 0],
    })
    roster = pd.DataFrame({"pfr_id": ["wr"], "gsis_id": ["nfl-wr"]})
    games = _actual_games_from_snaps(snaps, roster).set_index("gsis_id")
    assert games.loc["nfl-wr", "games"] == 2
