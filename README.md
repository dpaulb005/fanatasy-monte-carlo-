# nflsim

Monte Carlo simulation of NFL seasons, play by play, for fantasy football projection.

Ten thousand simulated 2026 seasons — every game, every drive, every snap — using real
players, real depth charts, real coaching staffs and real historical rates. The output is
not a projected point total but a *distribution*: what each player's season looks like
across ten thousand versions of the year.

Nothing here is scraped from anyone else's projections. Every number is fit from primary
data.

---

## Why simulate plays instead of projecting box scores

Fantasy scoring is a function of usage, and usage is a function of game script. A team
that falls behind throws more and its receivers eat; a team that leads runs the clock out
and its back eats. Those correlations cannot be bolted onto a box-score sampler after the
fact — they have to *emerge* from the same state machine that produced the score.

So the engine simulates the actual game. Down, distance, field position, clock and score
drive a play call; the play call resolves against real efficiency distributions; the ball
goes to a specific player; the clock advances; the score changes; and that new state
drives the next play call. Ten thousand times, for all 272 games.

The consequence is that correlations you would otherwise have to *assume* come out for
free, and correctly: a quarterback and his top receiver come out positively correlated,
two backs in the same committee negatively, and a receiver's ceiling games are the ones
where his team was behind — because that is what actually happened in the simulation.

---

## Quick start

```bash
pip install -r requirements.txt

python -m nflsim build                  # fit the model from source data (~6 min)
python -m nflsim simulate --sims 10000  # run 10,000 seasons (~7 min)

python -m nflsim board --top 80         # the draft board
python -m nflsim projections --pos WR   # per-position stat projections
python -m nflsim teams                  # team wins, scoring, coaching profiles
python -m nflsim validate               # check the engine against reality
python -m nflsim export --out out/      # CSV + parquet
```

Scoring and league shape are flags, so any format is one argument away:

```bash
python -m nflsim board --scoring half --teams 10
python -m nflsim board --superflex 1 --qb 1        # superflex changes replacement level
python -m nflsim compare "Puka Nacua" "Ja'Marr Chase"
```

---

## Where the numbers come from

All data is public and pulled live from [nflverse](https://github.com/nflverse), cached
locally after first download.

| Input | Source | What it drives |
|---|---|---|
| Play-by-play, 2016–2025 | `nflverse` pbp (~350k plays) | Every outcome distribution in the engine |
| 2026 rosters & depth charts | `nflverse` rosters, depth_charts | Who is on which team, and in what order |
| 2026 schedule | `nfldata` games.csv | Opponents, venue, roof, surface |
| Weekly player stats, 2023–2025 | `nflverse` stats_player | Target shares, carry shares, efficiency |
| Snap counts, 2018–2025 | `nflverse` snap_counts | Injury hazards, availability history, roster continuity |
| Head coaches | `nfldata` games.csv | Pass rate over expected, pace, fourth-down aggression |
| Draft picks & combine | `nflverse` draft_picks, combine | Rookie priors |
| Betting lines | `nfldata` games.csv | **Sanity check only** — never an input |

### Everything is a weighted sum over past seasons

No estimate in this model comes from a single season. A year of NFL data is a
small, noisy sample — one injury, one coordinator change, six weeks of bad game
script — and projecting off it alone over-reacts to whatever happened most
recently. But pooling many seasons with *equal* weight is also wrong, because the
league genuinely drifts: kickers have gotten better, coaches have gotten more
aggressive on fourth down, backfields have committee-ised.

So every layer is an exponentially recency-weighted sum across several past
seasons, with the half-life set by how fast that particular quantity actually
moves:

| Layer | Window | Half-life | Why |
|---|---|---|---|
| League physics | 2016–2025 | 4 seasons | Rules and efficiency drift over years, so keep a decade of signal but let the modern game lead |
| Coaching | full career | 2.5 seasons | A staff's identity persists but evolves with personnel and the league |
| Team strength | 3 seasons | 1.15 seasons | Rosters turn over hard; two-year-old form says little |
| Player usage | 4 seasons | 1.1 seasons | Roles change on a one-year timescale |
| Rank baselines | 6 seasons | 3 seasons | Needs to be stable — it's the fallback for thin history — but offence concentration drifts |
| Rookie curves | 2006–2025 | 5 seasons | Only 32 first-rounders a year across four positions, so a large sample is required |

Measurably, this matters. Weighted versus unweighted fits of the same decade:
field goal accuracy from 55 yards comes out at 66.6% rather than 64.6%; the
fourth-down go rate at 18.9% rather than 17.7%. Those are real changes in how the
game is played, and an unweighted mean would project a league that no longer
exists.

Shrinkage uses the *effective* sample size — the sum of recency weights — rather
than a raw count. Fourteen games two seasons ago is genuinely weaker evidence
than fourteen games last year, and a raw game count cannot express that.

### The four model layers

**1. League physics.** How a play resolves, league-wide: completion probability by air
yards, the yards-after-catch distribution, rushing yardage, sack and interception and
fumble rates, field goal accuracy by distance, punt distance, clock runoff. Estimated as
binned empirical frequencies with empirical-Bayes shrinkage rather than a fitted
parametric model — with 480k plays the bins are dense enough to be stable, and an
empirical bin cannot be wrong about a shape the way a misspecified link function can.

**The short field is its own game.** Three separate corrections are carried by distance to
the end zone, each fit as a residual so it composes with the main model rather than
replacing it. They matter more than their size suggests, because everything they affect
happens where points are scored.

- *Completion.* A defence with no grass behind it covers far better. Completion rates
  inside the ten fall to the high forties where the league-wide air-yards curve predicts
  the low seventies. Correction: −12.6 points at the 5, decaying to zero by the 25, and
  slightly *positive* backed up near your own goal line.
- *Play-calling.* Inside the two, offences pass 33.8% of the time; down and distance alone
  predict 46.9%. Field position is kept out of the main play-call grid — a fifth axis
  would quarter the plays per cell — so it rides as a separate residual.
- *Who gets targeted.* Offences do not just compress their normal passing game near the
  goal line, they change who they throw to. Tight ends take 29.3% of targets inside the 5
  against 21.4% over the whole field; running backs fall from 19.2% to 12.0%. Modelling
  one target share for the whole field starves tight ends of exactly the throws that score
  and hands running backs receiving touchdowns they do not get.

Without these, red zone passes complete far too often, passing touchdowns run 16–23% above
the real rate, and the touchdown mix skews away from the running game.

**2. Coaching.** Pass rate over expected, neutral-situation pace, fourth-down aggression
and red zone tendency, attributed to the *coach* rather than the team. A staff that
changed jobs carries its identity to the new building; a team that changed staffs inherits
the new one. Tendencies are shrunk toward league average by how many plays back them.

**3. Team strength.** Offensive and defensive efficiency, split by pass and rush, weighted
by recency and regressed toward the mean. Teams that changed head coach, or that returned
little of last year's snap volume, are pulled harder toward average — last season is a
weaker guide to a team that is substantially a different team.

**4. Players.** The load-bearing idea: a player's *share* of his offence is not a property
he carries between buildings. A receiver who commanded a quarter of the targets on a bad
team does not command a quarter of them after signing somewhere with two better receivers
already there. So four seasons of history are converted into a role-independent usage
weight, combined with a depth-chart baseline according to how much history actually backs
it, and only then normalised into shares inside his 2026 offence. That single mechanism
handles team changes, the draft and injuries consistently.

### Rookies

Rookies have no NFL snaps, so their prior is built from draft capital — empirically the
strongest public signal there is — calibrated against what every comparable draft slot has
actually produced in year one since 1999, kernel-smoothed in log-pick space because draft
value is multiplicative rather than linear. Combine testing then separates players taken
at the same slot. Draft capital is a real signal but a noisy one, so it never fully
overrides where the staff has actually listed the player.

*Not included:* college production statistics. The college play-by-play repository was not
reachable from this environment. Draft capital already prices in most of what college
production tells you — NFL teams watched the same tape — so the loss is real but second
order. `players.fit_rookie_curves` is where a college-stats provider would slot in.

### Season-to-season role uncertainty

A model that fixes every player's usage share at its expected value across all ten thousand
seasons is not simulating the season — it is simulating the *average* of all seasons. Real
years contain breakouts, benchings, scheme changes and jobs won in camp, and a model
without that variance produces ceilings far too low and a top of the board far too flat.

So each simulated season draws a role multiplier per player, once for the year (a player
who wins a bigger role in camp keeps it). The size of that draw is fit, not assumed:
regress log usage share on the prior year's, and take the residual spread. The regression
slope comes out around 0.63 — that *is* mean reversion, and the prior already encodes it
through shrinkage — so what's left is the genuinely unforecastable part. It is large:
σ ≈ 0.57 for running backs, 0.44 for receivers and tight ends. The share-sampling noise the
engine already generates through its own target draws is removed in quadrature so it isn't
counted twice.

### Injuries

Every player carries a weekly hazard of a new absence, with a duration drawn from a
geometric distribution. When a player goes down, his usage is redistributed through the
depth chart — most of it to his direct backup, the remainder across the rest of the
offence, because coordinators genuinely do redistribute across positions when a starter is
out. Absences persist across weeks rather than being redrawn each Sunday.

Hazards are fit from actual snap participation, not roster status — roster status
conflates injury with practice-squad churn and healthy scratches. Bye weeks are excluded
(otherwise every player in the league picks up one fake injury a year, which pins the
fitted hazard to its ceiling). The rate is then calibrated so the model's steady-state
absence fraction reproduces the observed one, and adjusted per player by age and by his
own durability record.

---

## Validation

`python -m nflsim validate` runs three checks. The first is the one that matters: a
simulation that produces beautiful distributions from broken physics is worse than
useless, because it is confidently wrong.

1. **League rates** — do simulated games look like NFL games? Plays, points, completion
   percentage, yards per carry, touchdowns, interceptions, sack rate. Scored against the
   recency-weighted span the engine was fit to, with last season shown alongside.
2. **Positional cohorts** — does the Nth-best finisher at each position score what those
   finishers actually score? Ranked *within* each simulated season, then averaged.
3. **Market** — where 2026 lines exist, do simulated totals agree? Advisory only. The
   model never sees betting lines, so disagreement is the point — but a *large*
   disagreement usually means the model is wrong, not the market.

### Backtesting

`python -m nflsim backtest --season 2025` is the stronger test. League rates only prove
the engine makes NFL-shaped games; they say nothing about whether the model can tell
*players* apart, which is the entire job. The backtest rebuilds the model knowing nothing
after 2024 — play-by-play truncated, depth chart capped at a preseason date — projects the
season, and scores it against what actually happened: correlation, rank correlation, mean
absolute error and bias, overall and by position.

It also reports **interval calibration**: how often the stated p10–p90 band actually
contained the outcome. A distribution nobody has checked for overconfidence is a point
estimate with decoration.

Two caveats are reported rather than hidden: rosters are read at end-of-season state, so a
player traded in October is credited to his final team; and production by players never
carried on a depth chart is out of scope, which is why a coverage percentage is printed.

### Measured results

Ten thousand simulated 2026 seasons, against the recency-weighted 2021–25 league:

| metric | simulated | 2021–25 weighted | error |
|---|---|---|---|
| plays / team-game | 62.25 | 61.73 | +0.8% |
| points / team-game | 22.98 | 22.56 | +1.9% |
| pass attempts / team-game | 33.14 | 33.23 | −0.3% |
| completion % | 64.58 | 64.28 | +0.5% |
| pass yards / team-game | 245.5 | 233.5 | **+5.2%** |
| yards / carry | 4.35 | 4.51 | −3.5% |
| sack rate % | 6.96 | 6.46 | **+7.8%** |
| pass TD / team-game | 1.51 | 1.46 | +3.7% |
| rush TD / team-game | 0.98 | 0.92 | +6.9% |
| INT / team-game | 0.75 | 0.75 | +0.6% |

Market sanity check: across the 52 games with published 2026 lines, mean simulated total
47.1 against a posted 45.6 — a 1.6-point disagreement from a model that never sees a line.

**Out-of-sample backtest, 2025** (built on data through 2024, depth chart capped at
preseason, 3,000 sims, top 200 projected):

| cohort | n | correlation | rank corr | MAE | bias |
|---|---|---|---|---|---|
| all positions | 200 | **0.599** | 0.583 | 61.3 | −4.7 |
| RB | 59 | 0.635 | 0.611 | 70.2 | −3.6 |
| WR | 80 | 0.581 | 0.571 | 59.3 | +2.0 |
| TE | 29 | 0.485 | 0.248 | 40.5 | −22.3 |
| QB | 32 | 0.342 | 0.254 | 68.7 | −7.3 |

96.6% of actual league-wide fantasy production was on a modelled depth chart. The largest
misses are the ones you'd expect and could not have known: James Conner and Tyreek Hill
over-projected (both got hurt); McCaffrey, Puka Nacua and Drake Maye under-projected (all
broke out).

**Intervals are overconfident.** The stated p10–p90 band contained the actual 2025 outcome
67.5% of the time against a nominal 80%; p25–p75 caught 36.5% against 50%. Real floors and
ceilings are wider than the ones printed. Two rounds of added variance — season-level role
volatility and team efficiency shocks, both fit from data rather than assumed — closed most
of the gap in the *point* projections but only ~1 point of the coverage gap. Closing the
rest by inflating variance until the number hit 80% would be fitting a distribution
parameter to a single backtest season, so it is reported rather than tuned away. Treat the
percentile columns as ordering information, not as calibrated probabilities.

### One correction worth naming

An earlier version of the cohort check compared each position's *highest projected mean*
against that position's *realised leader*, and the model looked badly pessimistic —
tight ends came out 43% low. That was an artefact of the comparison, not the model. A
season's leading tight end is the maximum of thirty-odd draws from thirty-odd different
distributions, and the maximum of a sample is systematically larger than the largest mean.
The check now ranks within each simulated season and then averages, which is the
like-for-like quantity.

---

## Reading the output

- **Proj** — mean season points across all simulations.
- **Floor / Ceil** — 10th and 90th percentile seasons. The gap is the real information:
  240 points means something very different when the floor is 210 than when it is 95.
- **VOR** — points above replacement level, where replacement is the last player at that
  position who would realistically start in your league. Raw totals compare a quarterback
  to a tight end and conclude the quarterback is better; VOR asks the question that
  actually decides drafts.
- **Tier** — one-dimensional k-means over VOR. A tier is a set of players close enough
  together that which one you get does not much matter. Tier breaks tell you whether
  waiting costs you anything.
- **Boom / Bust** — share of seasons finishing above the 75th / below the 25th percentile
  of that position's starters.

---

## Known limitations

Stated plainly, because a projection you cannot audit is worth less than one you can.

- **Intervals are too narrow** — see the measured coverage above. The biggest known gap.
- **Quarterbacks are the weakest position** (backtest r = 0.342, and the top-12 cohort
  projects ~10% light). QB scoring is almost entirely a function of how well an offence
  plays, and the model has less independent signal there than it does on usage share.
- **Tight end rank correlation is poor** (0.248) even though the level is close. The
  position is thin and volatile; small share differences swing the ordering.
- **Pass yards run ~5% high and sack rate ~8% high** against the fitted era.

- **Two-point conversions** are simulated for team scoring but not attributed to
  individual players. Worth roughly 2 points a season to an elite scorer.
- **Kickers and team defence** are not projected. The engine models field goals for game
  state but does not produce K or DST fantasy output.
- **Overtime** is settled as a coin flip on the winning drive rather than simulated, which
  is immaterial for season-long fantasy and avoids a second engine.
- **Return touchdowns** are not modelled.
- **Offensive line quality** is captured only implicitly, through team rushing efficiency
  and sack rates, not as a separate unit that can be tracked across free agency.
- **Holdouts, suspensions and training-camp news** are not modelled. The depth charts are
  as of build time and no more current than that.
- **Coaching profiles are head-coach-attributed.** Where a coordinator calls plays and the
  head coach does not, the profile blends both. Public coordinator history is not reliably
  available in the source data.
- **Overtime, byes and playoff seeding** do not feed back into late-season game script;
  every regular season game is simulated as if both teams are playing it straight.

---

## Layout

```
nflsim/
  data.py       cached loaders for every source
  config.py     scoring, league shape, simulation settings
  priors.py     league physics, coaching profiles, team strength
  players.py    usage priors, rookie curves, injury hazards, depth charts
  build.py      assembles everything into per-team simulation inputs
  engine.py     the play-by-play engine
  season.py     availability draws and the season loop
  analysis.py   scoring, projections, VOR, tiers
  board.py      terminal rendering
  validate.py   checks against reality and the market
  cli.py        command line interface
```

### Performance

The engine is vectorised *across replications* rather than across plays: one game advances
one play at a time, but all ten thousand simulated universes take that step together as a
single numpy operation. A season is therefore ~160 sequential steps per game rather than
160 × 10,000. Stat tensors are laid out `(channel, replication, roster slot)` so a channel
is a contiguous 2-D view, and because exactly one replication row appears once per play,
attribution is a flat fancy-index add — no scratch allocation and no `np.add.at`.

Ten thousand seasons — 2.72 million simulated games — takes about seven minutes on four
cores.
