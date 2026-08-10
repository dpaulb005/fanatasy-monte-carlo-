import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from nflsim.config import League, PPR
from nflsim.integration import SCHEMA, application_snapshot, write_application_snapshot


def _fixture():
    player_table = pd.DataFrame({
        "name": ["Alpha Back", "Beta Back"],
        "pos": ["RB", "RB"],
        "team": ["AAA", "AAA"],
        "age": [25, 23],
        "depth_rank": [1, 2],
        "is_rookie": [False, True],
    })
    team = SimpleNamespace(gidx=np.array([0, 1]))
    bundle = SimpleNamespace(
        season=2026, player_table=player_table, teams={"AAA": team},
    )
    # Keep enough replications for contingent/ceiling analysis thresholds.
    sims = 1000
    totals = np.zeros((14, sims, 2), dtype=np.float32)
    totals[5, :, 0] = np.linspace(100, 300, sims)  # rush attempts
    totals[6, :, 0] = np.linspace(400, 1400, sims)
    totals[7, :, 0] = np.arange(sims) % 14
    totals[5, :, 1] = np.linspace(50, 180, sims)
    totals[6, :, 1] = np.linspace(200, 900, sims)
    totals[7, :, 1] = np.arange(sims) % 8
    games = np.full((sims, 2), 17, dtype=np.float32)
    games[:250, 0] = 10
    result = {
        "totals": totals, "games_played": games, "n_sims": sims,
        "team_points": {"AAA": np.zeros(sims)},
        "team_wins": {"AAA": np.zeros(sims)},
    }
    return bundle, result


def test_application_snapshot_is_strict_versioned_json(tmp_path):
    bundle, result = _fixture()
    payload = application_snapshot(bundle, result, PPR, League(teams=2), pair_horizon=2)
    assert payload["schema"] == SCHEMA
    assert payload["schema_version"] == 1
    assert payload["model"]["simulations"] == 1000
    assert payload["players"][0]["p_pos1"] is not None
    assert "contingent_gain" in payload["players"][1]

    path = write_application_snapshot(
        bundle, result, PPR, League(teams=2), tmp_path / "snapshot.json", pair_horizon=2,
    )
    assert json.loads(path.read_text())["players"]
