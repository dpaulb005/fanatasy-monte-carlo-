"""A snake draft against opponents who draft the way the market drafts.

Eleven bots take players off an ADP board; you take the twelfth seat. When the
draft ends every roster is scored against the *same* simulated seasons the rest
of the project produces, so the answer is not "you got 1,940 projected points"
but "you win this league 14.8% of the time" -- which is the only number a draft
is actually trying to move.

Two things make that different from adding up projections:

*Lineups are chosen after the season happens.* A team starting two running
backs starts its best two in each simulated year, not the two it drafted
highest. That is worth real points, and it is why depth has value that a sum
of means cannot see.

*Rosters are scored jointly.* The same replication that has a quarterback
throwing for 5,000 yards has his receiver catching them. Teams stacked on one
offence therefore swing together, which widens their distribution without
changing their mean -- visible in title odds, invisible in projected points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .analysis import fantasy_points
from .config import League, Scoring

# Roster construction the bots respect. Caps stop a bot from drafting five
# quarterbacks when the noise happens to favour them; the starter deadline
# stops it from reaching round 15 without one.
POS_CAP = {"QB": 3, "RB": 7, "WR": 8, "TE": 3}


@dataclass
class DraftConfig:
    """Everything about the room, as opposed to the players in it."""

    league: League = field(default_factory=League)
    rounds: int = 15
    seat: int = 1                 # your draft slot, 1..teams
    # How far a real drafter strays from the consensus board, in picks. The
    # early rounds are close to chalk and the late rounds are nearly random,
    # so the deviation grows with pick number rather than being a constant.
    sigma0: float = 4.0
    sigma_growth: float = 0.13
    # Weight on a source's own disagreement measure, when it publishes one.
    sigma_disagree: float = 1.0
    # How hard a bot leans toward a position it still has to fill. Expressed in
    # picks of ADP: a need worth 10 means the bot will reach ten spots for it.
    need_bonus: float = 10.0
    # Positional run: after a position goes several times in a row, the next
    # bot is a little more likely to follow. Small, but it is real and it is
    # why tiers empty faster than ADP suggests.
    run_bonus: float = 2.5
    run_window: int = 6
    seed: int = 20260807

    def picks(self) -> int:
        return self.league.teams * self.rounds

    def starters(self) -> dict[str, int]:
        return self.league.starters()

    def flex(self) -> int:
        return self.league.flex + self.league.superflex


def snake_order(teams: int, rounds: int) -> np.ndarray:
    """Pick number -> team index, serpentine."""
    fwd = np.arange(teams)
    order = [fwd if r % 2 == 0 else fwd[::-1] for r in range(rounds)]
    return np.concatenate(order)


# --------------------------------------------------------------------------
# The bots
# --------------------------------------------------------------------------

def _shortfall(counts: dict[str, int], cfg: DraftConfig) -> dict[str, int]:
    """Starting slots this roster has not filled yet, by position."""
    return {p: max(w - counts.get(p, 0), 0) for p, w in cfg.starters().items()}


def _need(counts: dict[str, int], cfg: DraftConfig, picks_left: int) -> dict[str, float]:
    """Per-position bonus, in picks of ADP, for a roster in this state.

    Two separate pressures. A bot that has not filled a starting slot wants
    that position; a bot that is running out of picks to fill it with wants it
    urgently. The second term is what produces the late run on quarterbacks and
    tight ends that any real draft has.
    """
    short = _shortfall(counts, cfg)
    total_short = sum(short.values())
    pressure = min(total_short / max(picks_left, 1), 1.0)
    return {p: cfg.need_bonus * s * (1.0 + 3.0 * pressure) if s else 0.0
            for p, s in short.items()}


def _run_counts(recent: list[str], window: int) -> dict[str, int]:
    tail = recent[-window:]
    return {p: tail.count(p) for p in set(tail)}


def bot_pick(avail: np.ndarray, board: np.ndarray, pos: np.ndarray,
             counts: dict[str, int], cfg: DraftConfig, picks_left: int,
             recent: list[str]) -> int:
    """Which player this bot takes, as an index into the player arrays.

    The model is the standard one for simulating a draft room: each drafter
    carries his own noisy read of the consensus board and takes the best player
    on it, adjusted for what his roster still needs. `board` is that drafter's
    perceived ADP -- drawn once, at the start, and kept for the whole draft,
    because a manager who is high on somebody in round two is still high on him
    in round nine. Re-rolling every pick would make each bot a different person
    each time it is on the clock, and would wash out exactly the persistent
    preferences that make players go off-board.

    It reproduces the two features that matter for practice: players go near
    ADP but not at it, and positions empty in bursts.
    """
    if not avail.any():
        raise RuntimeError("no players left to draft")

    perceived = board.copy()

    for p, b in _need(counts, cfg, picks_left).items():
        perceived[pos == p] -= b
    for p, n in _run_counts(recent, cfg.run_window).items():
        if n >= 2:
            perceived[pos == p] -= cfg.run_bonus * (n - 1)

    # Hard caps: a bot never drafts a fourth quarterback, however the noise
    # falls. Applied by exclusion rather than penalty so it cannot be overcome.
    blocked = np.zeros(len(board), dtype=bool)
    for p, cap in POS_CAP.items():
        if counts.get(p, 0) >= cap:
            blocked |= (pos == p)

    # When picks remaining exactly equal starting slots still empty, need stops
    # being a preference and becomes a constraint. Without this a bot that got
    # unlucky with the noise can finish the draft without a tight end, which no
    # real drafter does and which would hand the other rosters free points.
    short = _shortfall(counts, cfg)
    if sum(short.values()) >= picks_left:
        forced = np.isin(pos, [p for p, s in short.items() if s > 0])
        if (avail & forced).any():
            blocked |= ~forced

    ok = avail & ~blocked
    if not ok.any():
        ok = avail
    return int(np.argmin(np.where(ok, perceived, np.inf)))


def pick_sigma(adp: np.ndarray, adp_sd: np.ndarray, cfg: DraftConfig) -> np.ndarray:
    """Per-player pick noise, in picks.

    Deviation from consensus is small at the top of the board and large at the
    bottom, so the floor grows linearly with ADP. Where the source publishes
    expert disagreement, that is added on top: players the market cannot agree
    on are exactly the players whose draft position is unpredictable, and a
    single league-wide constant throws that information away.
    """
    base = cfg.sigma0 + cfg.sigma_growth * adp
    extra = np.nan_to_num(adp_sd, nan=0.0) * cfg.sigma_disagree
    return np.sqrt(base ** 2 + extra ** 2)


# --------------------------------------------------------------------------
# Running the draft
# --------------------------------------------------------------------------

def run_draft(pool: pd.DataFrame, cfg: DraftConfig,
              on_clock=None) -> pd.DataFrame:
    """Play out the whole draft and return one row per pick.

    `pool` needs `name`, `pos`, `team`, `adp`, `adp_sd` and is indexed the same
    way as the player table, so picks can be joined straight back to the
    simulation. `on_clock(state)` is called when it is the human seat's turn
    and returns a pool index; leaving it None makes the seat draft by ADP like
    everyone else, which is the right control when measuring a strategy.
    """
    rng = np.random.default_rng(cfg.seed)
    n_teams = cfg.league.teams
    order = snake_order(n_teams, cfg.rounds)

    idx = pool.index.to_numpy()
    adp = pool.adp.to_numpy(dtype=float)
    sd = pool.adp_sd.to_numpy(dtype=float)
    pos = pool.pos.to_numpy()
    sigma = pick_sigma(adp, sd, cfg)

    # One perceived board per drafter, drawn once and kept: see `bot_pick`.
    boards = adp[None, :] + rng.normal(0.0, 1.0, (n_teams, len(pool))) * sigma[None, :]

    avail = np.ones(len(pool), dtype=bool)
    counts = [{} for _ in range(n_teams)]
    rosters: list[list[int]] = [[] for _ in range(n_teams)]
    recent: list[str] = []
    rows = []

    for pick_no, team in enumerate(order, start=1):
        rnd = (pick_no - 1) // n_teams + 1
        picks_left = cfg.rounds - rnd + 1
        human = (team == cfg.seat - 1) and on_clock is not None

        if human:
            state = DraftState(pick_no=pick_no, rnd=rnd, cfg=cfg, pool=pool,
                               avail=avail.copy(), roster=list(rosters[team]),
                               counts=dict(counts[team]), rows=rows)
            j = on_clock(state)
            if j is None or not avail[j]:
                j = bot_pick(avail, boards[team], pos, counts[team], cfg,
                             picks_left, recent)
        else:
            j = bot_pick(avail, boards[team], pos, counts[team], cfg,
                         picks_left, recent)

        avail[j] = False
        p = pos[j]
        counts[team][p] = counts[team].get(p, 0) + 1
        rosters[team].append(j)
        recent.append(p)

        rows.append({
            "pick": pick_no, "round": rnd,
            "team_idx": int(team), "gindex": int(idx[j]),
            "player": pool.name.iloc[j], "pos": p, "nfl": pool.team.iloc[j],
            "adp": float(adp[j]),
            # Negative means the pick was a reach, positive a fall. This is the
            # single most useful column in the sheet: it is the market's
            # opinion of the pick, priced in picks.
            "adp_delta": float(adp[j] - pick_no),
            "by_you": bool(team == cfg.seat - 1),
        })

    return pd.DataFrame(rows)


@dataclass
class DraftState:
    """What the human seat sees when it is on the clock."""

    pick_no: int
    rnd: int
    cfg: DraftConfig
    pool: pd.DataFrame
    avail: np.ndarray
    roster: list[int]
    counts: dict[str, int]
    rows: list[dict]

    def available(self) -> pd.DataFrame:
        return self.pool[self.avail]

    def next_pick(self) -> int:
        """The pick number this seat is next up after the current one.

        The gap between your picks is the whole game in a snake draft: it
        decides which of two players you can still expect to be there.
        """
        n = self.cfg.league.teams
        order = snake_order(n, self.cfg.rounds)
        mine = np.flatnonzero(order == self.cfg.seat - 1) + 1
        later = mine[mine > self.pick_no]
        return int(later[0]) if len(later) else -1


# --------------------------------------------------------------------------
# Scoring the finished rosters against the simulation
# --------------------------------------------------------------------------

def optimal_lineup(fp: np.ndarray, pos: np.ndarray, league: League
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Best legal starting lineup per replication, for one roster.

    `fp` is (S, roster_size) fantasy points in each simulated season. Because
    the lineup is chosen after the season is known, this is a best-ball total:
    it overstates what a manager sitting down each Sunday would actually score.
    The overstatement is roughly constant across teams, so comparisons between
    rosters in the same league survive it; the absolute number should not be
    read as a projection.

    Returned as (starter points, bench points).
    """
    S = fp.shape[0]
    total = np.zeros(S, dtype=np.float32)
    used = np.zeros_like(fp, dtype=bool)
    leftovers = []

    for p, want in league.starters().items():
        cols = np.flatnonzero(pos == p)
        if want <= 0:
            continue
        if len(cols) == 0:
            continue
        sub = fp[:, cols]
        order = np.argsort(-sub, axis=1)
        take = min(want, len(cols))
        chosen = order[:, :take]
        total += np.take_along_axis(sub, chosen, axis=1).sum(axis=1)
        # Map back to global columns before marking. `used[:, cols]` is a
        # fancy-index *copy*, so writing through it marks a temporary and
        # silently loses every starter -- which then shows up as a bench that
        # includes the starting lineup and a flex that re-picks a player who
        # is already in it.
        np.put_along_axis(used, cols[chosen], True, axis=1)

    # Flex is filled greedily from what is left, which is optimal for a single
    # flex slot and near-optimal for two.
    n_flex = league.flex + league.superflex
    if n_flex > 0:
        elig = np.isin(pos, ("RB", "WR", "TE", FLEX_SLOT))
        if league.superflex:
            elig |= (pos == "QB")
        pool = np.where(used | ~elig[None, :], -np.inf, fp)
        order = np.argsort(-pool, axis=1)[:, :n_flex]
        take = np.take_along_axis(pool, order, axis=1)
        live = np.isfinite(take)
        total += np.where(live, take, 0.0).sum(axis=1)
        # Mark them used so the bench figure below is honest. Written into a
        # blank plane and OR-ed in: a flex slot that could not be filled points
        # at an already-used column, and assigning into `used` directly would
        # clear it.
        mark = np.zeros_like(used)
        np.put_along_axis(mark, order, live, axis=1)
        used |= mark

    bench = np.where(used, 0.0, fp).sum(axis=1)
    return total, bench


def replacement_vectors(fp_all: np.ndarray, pos: np.ndarray,
                        league: League) -> dict[str, np.ndarray]:
    """The (S,) points of the last startable player at each position.

    Not the mean of that player -- his whole distribution, replication by
    replication. It is what an empty roster slot is worth, and it has to be
    joint with everything else or the marginal value below would compare a
    candidate's good season to replacement's average one.
    """
    out = {}
    for p, rank in league.replacement_ranks().items():
        cols = np.flatnonzero(pos == p)
        if len(cols) == 0:
            out[p] = np.zeros(fp_all.shape[0], dtype=np.float32)
            continue
        means = fp_all[:, cols].mean(axis=0)
        order = cols[np.argsort(-means)]
        out[p] = fp_all[:, order[min(rank, len(order)) - 1]]
    return out


# What fills a flex slot when nobody has been drafted for it. These mirror the
# splits `League.replacement_ranks` already uses to fold flex demand back into
# the positional replacement ranks, so the two definitions of replacement level
# stay consistent with each other.
FLEX_MIX = {"RB": 0.45, "WR": 0.45, "TE": 0.10}
SUPERFLEX_MIX = {"QB": 0.85, "RB": 0.05, "WR": 0.08, "TE": 0.02}

# Pseudo-position for those fillers: flex-eligible, and unable to claim any
# dedicated positional slot because `League.starters()` has no such key.
FLEX_SLOT = "FLEX"


def _blend(repl: dict[str, np.ndarray], mix: dict[str, float]) -> np.ndarray:
    total = sum(mix.values())
    out = None
    for p, w in mix.items():
        v = repl.get(p)
        if v is None:
            continue
        out = v * (w / total) if out is None else out + v * (w / total)
    return out


def marginal_values(cand: np.ndarray, fp_all: np.ndarray, pos: np.ndarray,
                    roster: np.ndarray, repl: dict[str, np.ndarray],
                    league: League) -> np.ndarray:
    """How much each candidate adds to this roster's expected starting lineup.

    Value over replacement answers "how good is this player", which is the
    wrong question once you already have two running backs: the third one only
    plays when the flex wants him or the first two are hurt, and no positional
    ranking knows that. Marginal lineup value asks the question a pick actually
    poses -- how many points does adding him put in my starting lineup -- and
    the diminishing return falls out rather than being asserted.

    The roster is first padded with replacement-level players in every unfilled
    starting slot. Without that, a candidate is measured against a lineup with
    holes in it, and every early pick looks enormous because anything beats
    nothing. Padding says what is true: the slot will get filled by somebody,
    and the question is how much better than that somebody this is.

    The flex slots have to be padded too, and forgetting them is subtle rather
    than obvious. Leave the flex empty and adding any running back to a roster
    with two replacement backs pushes one of them down into the vacant flex,
    where he scores against nothing -- so the candidate's gain comes out as his
    entire projection rather than the ~150 points he is actually worth over the
    man he displaces. Every player then looks equally good and the statistic
    silently degenerates into raw projected points.
    """
    have = {p: int((pos[roster] == p).sum()) for p in league.starters()}
    fill = []
    for p, want in league.starters().items():
        for _ in range(max(want - have.get(p, 0), 0)):
            fill.append((p, repl[p]))

    # Flex fillers carry the pseudo-position FLEX: eligible for a flex slot,
    # unable to claim a dedicated one. How many are needed is the flex count
    # less the players already drafted beyond their positional requirements,
    # since those are the ones a flex slot would otherwise take.
    overflow = sum(max(have.get(p, 0) - want, 0)
                   for p, want in league.starters().items())
    for mix, count in ((FLEX_MIX, league.flex), (SUPERFLEX_MIX, league.superflex)):
        for _ in range(count):
            if overflow > 0:
                overflow -= 1
                continue
            fill.append((FLEX_SLOT, _blend(repl, mix)))

    base_fp = np.concatenate(
        [fp_all[:, roster]] + [v[:, None] for _, v in fill], axis=1
    ) if fill else fp_all[:, roster]
    base_pos = np.concatenate([pos[roster], np.array([p for p, _ in fill])])
    base, _ = optimal_lineup(base_fp, base_pos, league)

    out = np.empty(len(cand), dtype=np.float32)
    for i, c in enumerate(cand):
        fp = np.concatenate([base_fp, fp_all[:, c][:, None]], axis=1)
        ps = np.append(base_pos, pos[c])
        tot, _ = optimal_lineup(fp, ps, league)
        out[i] = float((tot - base).mean())
    return out


class ValueEngine:
    """Marginal lineup value for a seat, reused by the bot and the display.

    Holds the joint distribution once. Scoring a candidate means re-optimising
    a lineup over a twenty-column array, which is cheap; scoring all six
    hundred at every pick is not, so callers pass a shortlist.
    """

    def __init__(self, result: dict, bundle, scoring: Scoring, league: League):
        self.fp = fantasy_points(result["totals"], scoring)
        self.pos = bundle.player_table.pos.to_numpy()
        self.league = league
        self.repl = replacement_vectors(self.fp, self.pos, league)
        # The simulation's columns are the player table's row order. That is an
        # assumption the whole project makes; check it once here rather than
        # producing quietly wrong values if it ever stops being true.
        idx = bundle.player_table.index.to_numpy()
        if not np.array_equal(idx, np.arange(len(idx))):
            raise RuntimeError("player table is not indexed by simulation column")

    def gains(self, state: "DraftState", proj: pd.DataFrame,
              shortlist: int = 40) -> pd.Series:
        """Points added to the expected starting lineup, per candidate.

        Indexed by gindex, ordered best first. The shortlist is taken on value
        over replacement, which is a good enough filter -- a player outside the
        top forty by VOR is not the marginal-value pick either.
        """
        avail = state.available()
        head = proj.reindex(avail.index).nlargest(shortlist, "vor")
        roster = np.asarray([state.pool.index[j] for j in state.roster], dtype=int)
        vals = marginal_values(head.index.to_numpy(), self.fp, self.pos,
                               roster, self.repl, self.league)
        return pd.Series(vals, index=head.index).sort_values(ascending=False)


def grade(picks: pd.DataFrame, result: dict, bundle, scoring: Scoring,
          cfg: DraftConfig) -> pd.DataFrame:
    """League table: what each drafted roster is worth, jointly.

    Every team is scored on the same replications, so the ranking within a
    season is a real head-to-head and the finish probabilities mean something.
    """
    fp_all = fantasy_points(result["totals"], scoring)      # (S, P)
    gpos = bundle.player_table.pos.to_numpy()
    S = fp_all.shape[0]
    n = cfg.league.teams

    starters = np.zeros((n, S), dtype=np.float32)
    benches = np.zeros((n, S), dtype=np.float32)
    for t in range(n):
        gi = picks.loc[picks.team_idx == t, "gindex"].to_numpy()
        st, bn = optimal_lineup(fp_all[:, gi], gpos[gi], cfg.league)
        starters[t], benches[t] = st, bn

    # Rank inside each replication: in the season where everyone's players
    # boomed, finishing first still takes more than a good mean.
    order = np.argsort(-starters, axis=0)
    rank = np.empty_like(order)
    np.put_along_axis(rank, order,
                      np.broadcast_to(np.arange(n)[:, None], order.shape), axis=0)
    rank = rank + 1

    playoff_cut = max(n // 2, 1)
    rows = []
    for t in range(n):
        rows.append({
            "team": f"Team {t + 1}" + ("  (you)" if t == cfg.seat - 1 else ""),
            "team_idx": t,
            "points": float(starters[t].mean()),
            "p10": float(np.percentile(starters[t], 10)),
            "p90": float(np.percentile(starters[t], 90)),
            "sd": float(starters[t].std()),
            "bench": float(benches[t].mean()),
            "p_title": float((rank[t] == 1).mean()),
            "p_playoff": float((rank[t] <= playoff_cut).mean()),
            "p_last": float((rank[t] == n).mean()),
            "mean_finish": float(rank[t].mean()),
        })
    out = pd.DataFrame(rows).sort_values("p_title", ascending=False)
    out["seed"] = np.arange(1, len(out) + 1)
    return out


def pick_value(picks: pd.DataFrame, board: pd.DataFrame) -> pd.DataFrame:
    """Each pick priced against the board that was on the table when it was made.

    Two different questions, and drafters routinely confuse them. `adp_delta`
    is whether the market would have let you wait -- it says nothing about
    whether the player is good. `vor_lost` is the model's answer: how much
    value over replacement was still available and went to somebody else. A
    pick can be a reach on ADP and still be the best pick on the board.
    """
    if "vor" not in board:
        return picks
    vor = board["vor"]
    out = picks.copy()
    taken: set[int] = set()
    best_left = []
    for gi in out.gindex:
        remaining = vor.drop(index=list(taken), errors="ignore")
        best_left.append(float(remaining.max()) if len(remaining) else 0.0)
        taken.add(gi)
    out["vor"] = vor.reindex(out.gindex).to_numpy()
    out["best_available_vor"] = best_left
    out["vor_lost"] = out.best_available_vor - out.vor
    return out
