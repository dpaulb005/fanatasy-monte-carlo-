import numpy as np
import pandas as pd
import pytest

from nflsim.explain import recency_blend


def _hist(ppg_by_season):
    return pd.DataFrame({"tgt_share": list(ppg_by_season.values())},
                        index=pd.Index(list(ppg_by_season), name="season"))


def test_weights_favour_the_most_recent_season():
    hist = _hist({2022: 0.10, 2023: 0.10, 2024: 0.10, 2025: 0.10})
    blend, w = recency_blend(hist, "tgt_share", target=2026, halflife=1.1)
    assert blend == pytest.approx(0.10)
    assert w.sum() == pytest.approx(1.0)
    assert (np.diff(w) > 0).all(), "weights must rise toward the present"
    assert w[-1] > 0.5


def test_a_declining_player_is_blended_above_his_last_season():
    """The arithmetic behind the Kelce case: a weighted mean of levels always
    sits between the observations, so four straight declines produce a figure
    higher than the most recent one. Not a judgement, just the mean."""
    hist = _hist({2022: 0.249, 2023: 0.227, 2024: 0.241, 2025: 0.197})
    blend, _ = recency_blend(hist, "tgt_share", target=2026, halflife=1.1)
    assert blend > hist.tgt_share.iloc[-1]
    assert blend < hist.tgt_share.max()


def test_a_rising_player_is_blended_below_his_last_season():
    hist = _hist({2023: 0.240, 2024: 0.254, 2025: 0.290})
    blend, _ = recency_blend(hist, "tgt_share", target=2026, halflife=1.1)
    assert blend < hist.tgt_share.iloc[-1]


def test_a_step_change_is_diluted_toward_the_old_level():
    """Stevenson: one season at 0.319 after three near 0.50 does not move the
    blend anywhere near 0.319."""
    hist = _hist({2022: 0.494, 2023: 0.506, 2024: 0.531, 2025: 0.319})
    blend, _ = recency_blend(hist, "tgt_share", target=2026, halflife=1.1)
    assert blend == pytest.approx(0.417, abs=0.005)
    assert blend > 0.40


def test_a_shorter_halflife_tracks_the_last_season_more_closely():
    hist = _hist({2022: 0.50, 2023: 0.50, 2024: 0.50, 2025: 0.30})
    slow, _ = recency_blend(hist, "tgt_share", target=2026, halflife=3.0)
    fast, _ = recency_blend(hist, "tgt_share", target=2026, halflife=0.4)
    # Even at a 0.4-season half-life the last season only carries ~82% of the
    # weight, so the blend lands near 0.335 rather than at 0.30. Shortening the
    # half-life moves toward the most recent value; it never reaches it.
    assert fast < slow
    assert abs(fast - 0.30) < abs(slow - 0.30)
    assert fast == pytest.approx(0.335, abs=0.01)


def test_missing_history_is_not_an_error():
    blend, w = recency_blend(pd.DataFrame(), "tgt_share")
    assert np.isnan(blend) and len(w) == 0
    hist = _hist({2024: np.nan, 2025: np.nan})
    blend, w = recency_blend(hist, "tgt_share")
    assert np.isnan(blend)


def test_seasons_with_no_record_are_skipped_not_zero_filled():
    """A player who missed 2024 entirely should not have a zero averaged in --
    that would halve his projected role for being hurt once."""
    hist = _hist({2023: 0.30, 2024: np.nan, 2025: 0.30})
    blend, w = recency_blend(hist, "tgt_share", target=2026, halflife=1.1)
    assert blend == pytest.approx(0.30)
    assert len(w) == 2
