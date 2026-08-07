# Handoff — project state

Written so a fresh session can pick this up without re-deriving anything. Read
`README.md` first for what the model is; this file is what a *continuing*
session needs: where the bodies are buried, what has been tried and rejected,
and what to do next.

Branch: `claude/nfl-monte-carlo-fantasy-73qqvf`.

## 2026-08-07 dev continuation

The `dev` branch adds joint-distribution draft metrics to the self-contained
HTML report: positional top-one/top-three equity, starter probability,
season-specific value-over-replacement ranges, and a two-to-four-player draft
decision matrix. The matrix compares value above position-specific replacement
inside the same simulation replication; it does not compare cross-position raw
points. Tests live in `tests/test_report_html.py`, and the research/design notes
are in `docs/RESEARCH.md`.

The next continuation adds `python -m nflsim factors`, a controlled scenario
comparison for injuries, role variance, team-efficiency uncertainty, coaching
scheme and neutral team context. It also fixes two backtest/model inputs:
`build._age()` now uses the projected season, and roster continuity now requires
the player to remain on the same team. `backtest` reports a symmetric, exact
split of total error into games-played and points-per-game components. See
`docs/RESEARCH_LOOP.md` for researched candidates and promotion gates.
The first results and the corrected RB/QB error diagnosis are recorded in
`docs/FACTOR_FINDINGS.md`.

---

## Run it

```bash
pip install -r requirements.txt
python -m nflsim build                    # ~6 min, fits everything
python -m nflsim simulate --sims 10000    # ~6 min, writes artifacts/result.npz (351 MB)
python -m nflsim board --top 60
python -m nflsim html --out report.html
python -m nflsim validate
python -m nflsim backtest --season 2025 --sims 3000
python -m nflsim calibrate --fit-season 2024 --test-season 2025
```

`build` and `simulate` are separate on purpose: the bundle is small and cheap to
inspect, the result file is large. Anything that changes a *prior* needs both;
anything that changes only reporting needs neither.

---

## Where the model actually stands

Validated against the recency-weighted 2021–25 league: plays, points, completion
percentage, pass attempts and interceptions all within ~2.5%. Pass yards run
+5–6% high and sack rate +7%, which are the two known rate biases.

Out-of-sample 2025 backtest, on the cohort the public benchmark uses (top 20
QB/TE, top 40 RB/WR, scored within position):

| pos | n | R² | published best | MAE | published best |
|---|---|---|---|---|---|
| QB | 20 | 13.8% | 8.9% | 65.6 | 61.0 |
| TE | 20 | 18.1% | 9.0% | 40.6 | — |
| RB | 40 | 28.4% | 19.1% | **68.2** | **52.2** |
| WR | 40 | 11.6% | 8.9% | 63.1 | — |

Read that honestly: **R² is ahead at every position on a matched cohort, and MAE
is behind, badly at RB.** Published R² is one season's best source and published
MAE is an eleven-season average, so neither is a clean target — but the RB error
gap is real and unexplained. There is also a **+16.9 point upward bias on the top
40 receivers** that has not been diagnosed.

Pooled top-200: correlation .599, rank correlation .595, MAE 60.7. By position
RB .653, TE .611, WR .498, QB .337.

The MAE gap is the most important open problem in the project.

---

## Things tried and rejected — do not re-add these

Each of these looked reasonable and was removed after measurement. They are
listed so the next session does not reinvent them.

1. **Depth-chart rank penalty.** Divided a player's confidence when his usage
   history implied a better job than his listed depth slot. Premise: the chart
   is current, the share is stale. Measured: prior season beats depth rank at
   predicting realised usage in four of six position-seasons, decisively for
   receivers, *and* still wins in the exact disagreement case the penalty fired
   on (WR .804 vs .700). RB had four such cases in two seasons. Cost WR backtest
   correlation .581 → .464. Removed in `build.py` with the table in a comment.

2. **Receiver drop rate and running back broken tackles** as efficiency inputs.
   Both are staples of fantasy analysis. Year-over-year persistence is r = 0.156
   and r = 0.091 respectively — noise. Rejected in `players.fit_contact_splits`
   docstring.

3. **Inflating variance to fix interval coverage.** Two rounds of it (role
   volatility, team efficiency shocks). Both were fit from data and both
   improved the point projections, but coverage moved ~1 point. Do not tune a
   variance parameter against a single backtest season — that is the overfitting
   this project refuses elsewhere. Conformal calibration is the right tool and
   is implemented.

4. **Comparing projected means to a realised leader.** The cohort check
   originally scored each position's highest projected mean against that
   position's actual best finisher, and the model looked 43% pessimistic at
   tight end. A season's leader is the maximum of thirty-odd draws; the maximum
   of a sample exceeds the largest mean. Ranking must happen *within* each
   simulated season. Fixed in `validate._sim_positional`.

---

## Open problems, in priority order

1. **RB mean absolute error, 68.2 vs a published 52.2.** High RB correlation
   (.533 matched, .653 pooled) with high RB error means the ordering is right and
   the scale is wrong.
   Suspect the interaction of role volatility (σ = 0.571 for RB, the largest of
   any position) with the injury model. Start by decomposing the error into
   games-played error versus per-game error.

2. **+16.9 upward bias on top-40 receivers.** Undiagnosed. Check whether the
   rank baselines pull low-usage WRs up: the WR baseline ladder is fairly flat
   (.230/.151/.098/.058/...) and a WR5 blended toward .032 may be too generous.

3. **Touchdown dispersion is 56% closed, and the rest is diagnosed.** The
   engine's scoring was near-Poisson given volume (dispersion ratio 0.976)
   where real receiving touchdowns sit at 1.122. A red zone scoring shock
   (sigma 0.31, fit from data and scaled by the 71% of touchdowns that
   originate inside the twenty) brought it to 1.058 with mean scoring
   unchanged. The remaining gap has two known causes, neither yet addressed:
   shares are renormalised within a team, so one player's red zone gain is
   another's loss and *team* red zone efficiency cannot vary; and the 29% of
   touchdowns scored from outside the twenty carry no extra variance at all.
   **But closing it did not improve interval coverage**, which was the reason
   for doing it: the 80% band went 71.0% -> 70.0% and the 50% band 36.5% ->
   39.5%. So a team-level red zone shock, the obvious next extension, is
   probably not worth building either -- it is the same class of effect and
   the evidence says this class does not move the tails. Do not simply raise
   sigma to hit 1.122; the mechanism is incomplete, not mis-sized, and the
   payoff is not there.

4. **Interval calibration overshoots.** Conformal fitted on 2024 and applied to
   2025 takes the 80% band from 71.0% coverage to 90.0% — it removes the
   overconfidence but overcorrects into conservatism, widening mean interval
   width 161 → 250. The cause is that the *degree* of miscalibration varies year
   to year. Fix: pool 2021–24 as the calibration set (see `DATA_WANTED.md` §5).

5. **Quarterbacks are the weakest position** (backtest r = .342–.416). Their
   scoring is almost entirely downstream of how well the offence plays, and the
   model has less independent signal there than it has on usage share.

6. **College data for rookies.** Blocked here. See `DATA_WANTED.md` §3.

---

## Architecture notes that are not obvious

- **The engine is vectorised across replications, not plays.** One game advances
  one play at a time, but all N simulated universes take that step together as a
  single numpy operation. This is the reason 10,000 sims is tractable where
  comparable public projects default to 50–1,000. Stat tensors are laid out
  `(channel, replication, roster slot)` so a channel is a contiguous 2-D view,
  and because exactly one replication row appears per play, attribution is a
  flat fancy-index add — not `np.add.at`, which is ~10× slower.

- **Weekly capture reuses one buffer.** Holding every week's full distribution
  would be `(weeks, stats, sims, players)` — gigabytes. The schedule is walked in
  week order, one week's buffer accumulated and summarised, then cleared.

- **Three short-field corrections** ride as residuals by distance to the end
  zone: completion probability, play-call, and *which position gets targeted*.
  All three are large and all three are in the region where points are scored.
  Removing any of them breaks the touchdown mix.

- **Everything is a recency-weighted sum**, with half-lives per layer (physics 4
  seasons, coaching 2.5, team 1.15, usage 1.1). Shrinkage uses the *effective*
  (weight-summed) sample size, not a raw count.

- **`analysis.summarise` returns rows sorted by points** while `player_table` is
  in global-index order. Any join between them must be on the index. Doing it
  positionally silently pairs each player with someone else's data and produces
  a result that looks like a model with no predictive power — this cost a full
  backtest cycle once.

---

## Advanced statistics layer

`nflsim/advanced.py` holds metrics that require the joint distribution — things
a projection system storing only means and standard deviations cannot compute at
all, because they are conditional expectations over shared events:

- `contingent_value` — a backup's worth *in the seasons where the starter got
  hurt*. The injury cascade is already in the engine, so nothing is imputed.
- `championship_equity` — replacement level computed inside each simulated
  season, plus P(finish as positional #1).
- `coboom` — joint boom rate against the independence baseline. Stacking
  analysis exists in daily fantasy and essentially nowhere in season-long.
- `ceiling_anatomy` — whether a player's ceiling is bought with health, volume,
  efficiency or touchdown rate. The last of those does not repeat.
- `startability` — weekly reliability and December schedule, from the weekly
  capture.
- `head_to_head` — P(A outscores B) *in the same season*, which matters whenever
  two players share a defence or a game script.

These are the strongest differentiator the project has and the least explored.
