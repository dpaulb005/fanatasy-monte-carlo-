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
parametric model — with 350k plays the bins are dense enough to be stable, and an
empirical bin cannot be wrong about a shape the way a misspecified link function can.

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
   percentage, yards per carry, touchdowns, interceptions, sack rate.
2. **Positional cohorts** — do the top 12 QBs / 24 RBs / 36 WRs / 12 TEs score what those
   cohorts actually score?
3. **Market** — where 2026 lines exist, do simulated totals agree? Advisory only. The
   model never sees betting lines, so disagreement is the point — but a *large*
   disagreement usually means the model is wrong, not the market.

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
