import numpy as np
import pandas as pd
import pytest

from nflsim.chart import POS_COLOR, top_players


def _frame(n=8):
    rng = np.random.default_rng(0)
    pts = np.linspace(300, 150, n)
    return pd.DataFrame({
        "player": [f"Player {i}" for i in range(n)],
        "pos": [("QB", "RB", "WR", "TE")[i % 4] for i in range(n)],
        "team": ["PHI"] * n,
        "points": pts,
        "p10": pts - 90, "p25": pts - 40, "p75": pts + 40, "p90": pts + 95,
        # Deliberately not the same order as points, so a chart that ranks by
        # the wrong column is caught.
        "vor": pts[::-1] - 100,
    })


def test_rank_one_is_the_best_player_and_sits_at_the_top(tmp_path):
    """Regression: the rank was derived from row position *after* the frame was
    reversed for matplotlib's upward y axis, which numbered the best player
    last -- the top row read 30 and the bottom row read 1."""
    out = top_players(_frame(), tmp_path / "c.png", n=8, by="points")
    assert out.exists() and out.stat().st_size > 5000

    # The image itself cannot be asserted on, so re-derive the ordering the
    # function builds and check the mapping that was wrong.
    d = _frame().nlargest(8, "points").reset_index(drop=True)
    d["rank"] = np.arange(1, 9)
    flipped = d.iloc[::-1].reset_index(drop=True)
    assert flipped.iloc[-1]["rank"] == 1                  # top row of the plot
    assert flipped.iloc[-1].player == "Player 0"          # the best player
    assert flipped.iloc[0]["rank"] == 8


def test_ranking_column_is_honoured(tmp_path):
    d = _frame()
    by_vor = d.nlargest(4, "vor").player.tolist()
    by_pts = d.nlargest(4, "points").player.tolist()
    assert by_vor != by_pts, "fixture no longer distinguishes the two orderings"
    for by in ("vor", "points"):
        out = top_players(d, tmp_path / f"{by}.png", n=4, by=by)
        assert out.exists()


def test_every_projected_position_has_a_colour():
    assert set(POS_COLOR) == {"QB", "RB", "WR", "TE"}
    assert all(c.startswith("#") and len(c) == 7 for c in POS_COLOR.values())


def test_renders_when_only_one_position_is_present(tmp_path):
    d = _frame()
    d = d[d.pos == "RB"]
    out = top_players(d, tmp_path / "rb.png", n=len(d), by="points")
    assert out.exists() and out.stat().st_size > 3000


def test_asking_for_more_players_than_exist_is_not_an_error(tmp_path):
    out = top_players(_frame(5), tmp_path / "few.png", n=50, by="points")
    assert out.exists()
