import numpy as np
import pandas as pd
import pytest

from nflsim import adp as adp_mod
from nflsim.config import League
from nflsim.draft import (DraftConfig, marginal_values, optimal_lineup,
                          replacement_vectors, run_draft, snake_order)


LEAGUE = League(teams=4, qb=1, rb=1, wr=1, te=1, flex=1, bench=2)


def _pool(n_per_pos=6):
    rows = []
    for pos in ("QB", "RB", "WR", "TE"):
        for i in range(n_per_pos):
            rows.append({"name": f"{pos}{i}", "pos": pos, "team": "AAA",
                         "adp": len(rows) + 1.0, "adp_sd": 2.0})
    return pd.DataFrame(rows, index=range(len(rows) * 0, len(rows)))


# --------------------------------------------------------------------------
# Snake order
# --------------------------------------------------------------------------

def test_snake_order_reverses_every_other_round():
    order = snake_order(4, 3)
    assert list(order[:4]) == [0, 1, 2, 3]
    assert list(order[4:8]) == [3, 2, 1, 0]
    assert list(order[8:]) == [0, 1, 2, 3]
    # Every seat gets exactly one pick per round.
    assert sorted(np.bincount(order)) == [3, 3, 3, 3]


# --------------------------------------------------------------------------
# Lineup optimisation
# --------------------------------------------------------------------------

def test_optimal_lineup_starts_the_best_players_not_the_first_ones():
    # Two running backs, one starting slot and no flex: the better one plays.
    lg = League(teams=1, qb=0, rb=1, wr=0, te=0, flex=0)
    fp = np.array([[10.0, 30.0], [40.0, 5.0]], dtype=np.float32)
    pos = np.array(["RB", "RB"])
    starters, bench = optimal_lineup(fp, pos, lg)
    assert list(starters) == [30.0, 40.0]
    assert list(bench) == [10.0, 5.0]


def test_flex_takes_the_best_leftover_across_eligible_positions():
    lg = League(teams=1, qb=0, rb=1, wr=1, te=0, flex=1)
    # RB0 and WR0 start; the flex should take RB1 (20) over WR1 (12).
    fp = np.array([[50.0, 20.0, 40.0, 12.0]], dtype=np.float32)
    pos = np.array(["RB", "RB", "WR", "WR"])
    starters, bench = optimal_lineup(fp, pos, lg)
    assert starters[0] == pytest.approx(110.0)
    assert bench[0] == pytest.approx(12.0)


def test_lineup_survives_a_roster_too_thin_to_fill_every_slot():
    lg = League(teams=1, qb=1, rb=1, wr=1, te=1, flex=1)
    fp = np.array([[25.0]], dtype=np.float32)
    starters, bench = optimal_lineup(fp, np.array(["QB"]), lg)
    # The one player starts; nothing is invented, and he is not also benched.
    assert starters[0] == pytest.approx(25.0)
    assert bench[0] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Marginal value: the reason the draft bot does not take six running backs
# --------------------------------------------------------------------------

def test_marginal_value_falls_once_the_starting_slots_are_full():
    lg = League(teams=1, qb=0, rb=1, wr=1, te=0, flex=0)
    # Four identical players, two at each position.
    fp = np.tile(np.array([[100.0, 100.0, 100.0, 100.0]], dtype=np.float32), (5, 1))
    pos = np.array(["RB", "RB", "WR", "WR"])
    repl = {"RB": np.full(5, 10.0, np.float32), "WR": np.full(5, 10.0, np.float32)}

    empty = marginal_values(np.array([0]), fp, pos, np.array([], dtype=int), repl, lg)
    with_rb = marginal_values(np.array([1]), fp, pos, np.array([0]), repl, lg)

    # First running back replaces a replacement-level filler: worth 90.
    assert empty[0] == pytest.approx(90.0, abs=1e-3)
    # Second one cannot get into the lineup at all.
    assert with_rb[0] == pytest.approx(0.0, abs=1e-3)


def test_marginal_value_prefers_the_unfilled_position():
    lg = League(teams=1, qb=0, rb=1, wr=1, te=0, flex=0)
    fp = np.tile(np.array([[100.0, 100.0, 80.0]], dtype=np.float32), (5, 1))
    pos = np.array(["RB", "RB", "WR"])
    repl = {"RB": np.full(5, 10.0, np.float32), "WR": np.full(5, 10.0, np.float32)}
    gains = marginal_values(np.array([1, 2]), fp, pos, np.array([0]), repl, lg)
    # The worse receiver is worth more than the better second running back,
    # which is the entire point of the statistic.
    assert gains[1] > gains[0]


def test_marginal_value_pads_the_flex_slot_too():
    """Regression: an unpadded flex made every gain equal to raw projection.

    With one RB slot, one flex and nothing drafted, adding a running back
    should be worth his points less the replacement he displaces. Leave the
    flex empty and he instead pushes a replacement into a vacant flex slot
    scoring nothing, and his gain comes out as his whole projection -- which
    made the statistic identical to projected points for every player.
    """
    lg = League(teams=1, qb=0, rb=1, wr=0, te=0, flex=1)
    fp = np.tile(np.array([[300.0]], dtype=np.float32), (4, 1))
    pos = np.array(["RB"])
    repl = {p: np.full(4, 100.0, np.float32) for p in ("QB", "RB", "WR", "TE")}
    gain = marginal_values(np.array([0]), fp, pos, np.array([], dtype=int),
                           repl, lg)[0]
    # Base lineup is two replacement players (200); with him it is 400.
    assert gain == pytest.approx(200.0, abs=1e-3)
    assert gain != pytest.approx(300.0)


def test_flex_filler_cannot_claim_a_dedicated_positional_slot():
    lg = League(teams=1, qb=1, rb=0, wr=0, te=0, flex=1)
    repl = {p: np.full(3, 50.0, np.float32) for p in ("QB", "RB", "WR", "TE")}
    # A quarterback candidate takes the QB slot; the flex filler is not
    # eligible there and must not be counted twice.
    fp = np.tile(np.array([[80.0]], dtype=np.float32), (3, 1))
    gain = marginal_values(np.array([0]), fp, np.array(["QB"]),
                           np.array([], dtype=int), repl, lg)[0]
    assert gain == pytest.approx(30.0, abs=1e-3)


def test_replacement_vector_is_the_nth_best_player_not_an_average():
    lg = League(teams=1, qb=0, rb=2, wr=0, te=0, flex=0)   # replacement RB = 2nd
    fp = np.array([[30.0, 20.0, 5.0], [30.0, 20.0, 5.0]], dtype=np.float32)
    pos = np.array(["RB", "RB", "RB"])
    repl = replacement_vectors(fp, pos, lg)
    assert list(repl["RB"]) == [20.0, 20.0]


# --------------------------------------------------------------------------
# The draft room
# --------------------------------------------------------------------------

def test_every_seat_fills_its_starting_slots():
    pool = _pool()
    cfg = DraftConfig(league=LEAGUE, rounds=5, seed=1)
    picks = run_draft(pool, cfg)
    assert len(picks) == LEAGUE.teams * 5
    assert picks.gindex.is_unique
    for t in range(LEAGUE.teams):
        got = picks[picks.team_idx == t].pos.value_counts().to_dict()
        for pos, want in LEAGUE.starters().items():
            assert got.get(pos, 0) >= want, f"team {t} short at {pos}: {got}"


def test_positional_caps_are_never_exceeded():
    pool = _pool(n_per_pos=20)
    cfg = DraftConfig(league=League(teams=2, qb=1, rb=1, wr=1, te=1, flex=0),
                      rounds=12, seed=3, sigma0=50.0)   # huge noise, caps must hold
    picks = run_draft(pool, cfg)
    for t in picks.team_idx.unique():
        counts = picks[picks.team_idx == t].pos.value_counts().to_dict()
        assert counts.get("QB", 0) <= 3
        assert counts.get("TE", 0) <= 3


def test_the_human_seat_gets_its_requested_player():
    pool = _pool()
    cfg = DraftConfig(league=LEAGUE, rounds=4, seat=3, seed=7)
    # Ask for the worst player left every time: a bot would never take these
    # early, so the seat's roster is unmistakably its own choices.
    def on_clock(state):
        return int(np.flatnonzero(state.avail)[-1])

    picks = run_draft(pool, cfg, on_clock=on_clock)
    mine = picks[picks.team_idx == 2]
    # The last player in the pool has the worst ADP; the seat asked for him
    # first and must have got him.
    assert mine.player.iloc[0] == pool.name.iloc[-1]
    assert len(mine) == 4


def test_a_request_for_an_already_drafted_player_falls_back_to_the_bot():
    pool = _pool()
    cfg = DraftConfig(league=LEAGUE, rounds=3, seat=1, seed=11)
    picks = run_draft(pool, cfg, on_clock=lambda state: 0 if state.pick_no > 1 else 0)
    # Seat 1 takes index 0 with the first pick; every later request for it is
    # stale and must not resurrect a drafted player.
    assert picks.gindex.is_unique


def test_next_pick_is_the_seats_own_next_turn():
    pool = _pool()
    cfg = DraftConfig(league=LEAGUE, rounds=4, seat=1, seed=5)
    seen = []
    run_draft(pool, cfg, on_clock=lambda s: seen.append((s.pick_no, s.next_pick())) or None)
    # Seat 1 in a 4-team snake picks 1, 8, 9, 16.
    assert [p for p, _ in seen] == [1, 8, 9, 16]
    assert [n for _, n in seen] == [8, 9, 16, -1]


def test_the_draft_is_reproducible_from_its_seed():
    pool = _pool()
    a = run_draft(pool, DraftConfig(league=LEAGUE, rounds=4, seed=99))
    b = run_draft(pool, DraftConfig(league=LEAGUE, rounds=4, seed=99))
    c = run_draft(pool, DraftConfig(league=LEAGUE, rounds=4, seed=100))
    assert list(a.gindex) == list(b.gindex)
    assert list(a.gindex) != list(c.gindex)


# --------------------------------------------------------------------------
# ADP plumbing
# --------------------------------------------------------------------------

def test_name_normalisation_ignores_what_sources_disagree_about():
    assert adp_mod.norm_name("Ja'Marr Chase") == adp_mod.norm_name("JaMarr Chase")
    assert adp_mod.norm_name("Marvin Harrison Jr.") == adp_mod.norm_name("Marvin Harrison")
    assert adp_mod.norm_name("D.K. Metcalf") == adp_mod.norm_name("DK Metcalf")
    assert adp_mod.norm_name("Michael Pittman Jr.") != adp_mod.norm_name("Michael Thomas")


def test_attach_matches_on_position_before_name_alone():
    board = pd.DataFrame({
        "player": ["Mike Williams", "Mike Williams"],
        "pos": ["WR", "TE"], "team": ["LAC", "LAC"],
        "adp": [30.0, 200.0], "adp_sd": [3.0, 20.0],
        "key": ["mike williams", "mike williams"],
    })
    pt = pd.DataFrame({"name": ["Mike Williams"], "pos": ["TE"], "team": ["LAC"]},
                      index=[0])
    aligned, _ = adp_mod.attach(board, pt)
    assert aligned.adp.iloc[0] == 200.0


def test_unranked_players_land_below_the_board_in_model_order():
    aligned = pd.DataFrame({"adp": [10.0, np.nan, np.nan], "adp_sd": [2.0, np.nan, np.nan]},
                           index=[0, 1, 2])
    model_rank = pd.Series([1, 5, 3], index=[0, 1, 2])
    out = adp_mod.fill_undrafted(aligned, model_rank, gap=8.0)
    assert out.adp.iloc[0] == 10.0
    # Player 2 is better by the model, so he sits ahead of player 1.
    assert out.adp.iloc[2] < out.adp.iloc[1]
    assert out.adp.min() == 10.0
    assert out.adp.iloc[2] == pytest.approx(18.0)
    # An unpriced player inherits the widest disagreement, not zero.
    assert out.adp_sd.iloc[1] == 2.0


def test_finish_reranks_into_dense_pick_numbers_and_keeps_the_source_value():
    raw = pd.DataFrame({
        "player": ["A", "B", "C"], "pos": ["WR", "K", "RB"],
        "team": ["SF", "SF", "SF"], "adp": [1.0, 2.0, 3.0],
    })
    out = adp_mod._finish(raw, "test")
    # The kicker is dropped, and the running back moves up to pick 2.
    assert list(out.player) == ["A", "C"]
    assert list(out.adp) == [1.0, 2.0]
    assert list(out.adp_raw) == [1.0, 3.0]


def test_espn_payload_is_flattened_into_a_board():
    # The shape ESPN's kona_player_info view returns, trimmed to the fields
    # this project reads.
    batch = [
        {"player": {"fullName": "Ja'Marr Chase", "defaultPositionId": 3,
                    "proTeamId": 4,
                    "ownership": {"averageDraftPosition": 2.4, "percentOwned": 99.9},
                    "draftRanksByRankType": {"PPR": {"rank": 2, "auctionValue": 61}}}},
        {"player": {"fullName": "Deep Sleeper", "defaultPositionId": 2,
                    "proTeamId": 14,
                    "ownership": {"averageDraftPosition": 0.0, "percentOwned": 0.1},
                    "draftRanksByRankType": {}}},
        {"player": {"fullName": "Brandon Aubrey", "defaultPositionId": 5,
                    "proTeamId": 6, "ownership": {"averageDraftPosition": 130.2}}},
    ]
    rows = adp_mod.espn_rows(batch, "PPR")
    assert rows[0]["pos"] == "WR" and rows[0]["team"] == "CIN"
    assert rows[0]["adp"] == pytest.approx(2.4)
    # An undrafted player is missing, not pick zero.
    assert np.isnan(rows[1]["adp"])
    assert rows[1]["team"] == "LA"

    board = adp_mod._finish(pd.DataFrame(rows), "espn")
    # The kicker and the undrafted player both drop out, leaving one row at
    # pick 1 with ESPN's own number kept alongside.
    assert list(board.player) == ["Ja'Marr Chase"]
    assert board.adp.iloc[0] == 1.0
    assert board.adp_raw.iloc[0] == pytest.approx(2.4)


def test_espn_team_and_position_maps_cover_the_league():
    assert set(ESPN_TEAMS_EXPECTED) <= set(adp_mod.ESPN_TEAM.values())
    assert adp_mod.ESPN_TEAM[28] == "WAS"    # ESPN says WSH
    assert adp_mod.ESPN_TEAM[14] == "LA"     # ESPN says LAR
    assert set(adp_mod.ESPN_POS.values()) >= {"QB", "RB", "WR", "TE"}


ESPN_TEAMS_EXPECTED = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN",
    "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]


def test_csv_reader_accepts_the_usual_export_headers():
    import io
    text = "Overall,Player Name,Position,Team\n1,Ja'Marr Chase,WR1,CIN\n2,Bijan Robinson,RB2,ATL\n"
    out = adp_mod.read_csv(io.StringIO(text))
    assert list(out.player) == ["Ja'Marr Chase", "Bijan Robinson"]
    assert list(out.pos) == ["WR", "RB"]
    assert list(out.adp) == [1.0, 2.0]
