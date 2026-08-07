from types import SimpleNamespace

import numpy as np
import pandas as pd

from nflsim import analysis
from nflsim.config import League, PPR
from nflsim.engine import STATS, SIDX
from nflsim.report_html import (_decision_metrics, _pairwise_value_probability,
                                _payload, generate)


def _fixture():
    players = pd.DataFrame({
        "name": ["QB Alpha", "QB Beta", "RB Alpha", "RB Beta"],
        "pos": ["QB", "QB", "RB", "RB"],
        "team": ["AAA", "BBB", "AAA", "BBB"],
        "age": [25, 26, 23, 24],
        "depth_rank": [1, 1, 1, 1],
        "is_rookie": [False, False, True, False],
    })
    coaches = pd.DataFrame({
        "team": ["AAA", "BBB"], "coach": ["A Coach", "B Coach"],
        "proe": [0.01, -0.01], "pace": [28.0, 29.0],
    })
    bundle = SimpleNamespace(player_table=players, coach_table=coaches, season=2026)
    totals = np.zeros((len(STATS), 4, 4))
    # PPR fantasy points are rush yards / 10 here, which keeps the fixture clear.
    totals[SIDX["rush_yds"]] = np.array([
        [1000, 900, 800, 700],
        [100, 900, 1200, 700],
        [1000, 900, 800, 700],
        [100, 900, 1200, 700],
    ])
    result = {
        "totals": totals,
        "games_played": np.full((4, 4), 17.0),
        "team_points": {"AAA": np.array([350, 360]), "BBB": np.array([330, 340])},
        "team_wins": {"AAA": np.array([10, 11]), "BBB": np.array([8, 9])},
        "n_sims": 4,
    }
    league = League(teams=1, qb=1, rb=1, wr=0, te=0, flex=0)
    frame = analysis.add_value(
        analysis.summarise(result, bundle, PPR), result, bundle, PPR, league,
    )
    return bundle, result, frame, league


def test_decision_metrics_recalculate_replacement_each_season():
    bundle, result, _, league = _fixture()
    metrics, value = _decision_metrics(bundle, result, PPR, league)

    assert metrics[0]["eq1"] == 0.5
    assert metrics[1]["start"] == 0.5
    # The best QB is replacement itself in a one-QB player pool; bad seasons
    # finish 80 points below that season's replacement player.
    assert np.array_equal(value[:, 0], [0, -80, 0, -80])


def test_pairwise_probability_counts_ties_as_half():
    value = np.array([[2, 1], [1, 2], [1, 1], [4, 0]], dtype=float)
    matrix = _pairwise_value_probability(value, [0, 1])
    assert matrix == [[0.5, 0.625], [0.375, 0.5]]


def test_payload_and_html_include_draft_lab(tmp_path):
    bundle, result, frame, league = _fixture()
    payload = _payload(bundle, result, frame, PPR, league=league, min_points=0)
    assert payload["lab"]["limit"] == 4
    assert len(payload["lab"]["win"]) == 4
    assert {"eq1", "eq3", "start", "beat", "v10", "v90"} <= payload["players"][0].keys()

    out = generate(bundle, result, frame, PPR, tmp_path / "dashboard.html", league=league)
    html = out.read_text()
    assert "Draft decision lab" in html
    assert "position-specific replacement" in html
    assert "__DATA__" not in html
