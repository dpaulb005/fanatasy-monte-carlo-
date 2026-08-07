from types import SimpleNamespace

import numpy as np
import pandas as pd

from nflsim.experiments import Scenario, context_features, scenario_bundle


def _team():
    return SimpleNamespace(
        gidx=np.array([0, 1]), pos_code=np.array([1, 1]),
        target_share=np.array([0.2, 0.1]), rush_share=np.array([0.6, 0.3]),
        gl_share=np.array([0.7, 0.2]), proe=0.04, pace_mult=0.94,
        go_oe=0.03, rz_pass_oe=-0.05,
        off_pass_epa=0.1, off_rush_epa=0.2, off_comp_oe=0.03,
        off_ypc_oe=0.4, off_sack_oe=-0.01, def_pass_epa=-0.1,
        def_rush_epa=-0.2, def_comp_oe=-0.02, def_ypc_oe=-0.3,
        def_sack_oe=0.02,
    )


def test_scenario_bundle_neutralises_a_copy_only():
    original = SimpleNamespace(teams={"AAA": _team()})
    changed = scenario_bundle(
        original, Scenario("neutral", neutral_coach=True, neutral_strength=True),
    )
    assert original.teams["AAA"].proe == 0.04
    assert original.teams["AAA"].off_pass_epa == 0.1
    assert changed.teams["AAA"].proe == 0.0
    assert changed.teams["AAA"].pace_mult == 1.0
    assert changed.teams["AAA"].off_pass_epa == 0.0


def test_context_features_measure_teammate_pressure_and_concentration():
    bundle = SimpleNamespace(
        teams={"AAA": _team()},
        coach_table=pd.DataFrame({
            "team": ["AAA"], "new": [True], "continuity": [0.75],
        }),
    )
    frame = context_features(bundle)
    assert np.isclose(frame.loc[0, "role_margin"], 0.3)
    assert np.isclose(frame.loc[1, "role_margin"], -0.3)
    assert frame.loc[0, "rush_hhi"] == frame.loc[1, "rush_hhi"]
    assert bool(frame.loc[0, "new_coach"])

