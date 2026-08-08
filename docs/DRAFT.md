# The draft room

`python -m nflsim draft` runs a snake draft against eleven bots that take
players off a market board, then scores every finished roster against the same
simulated seasons the rest of the project produces.

The design decisions worth recording are below, followed by what was measured.

---

## The bots

Each drafter carries **his own perceived board**, drawn once at the start of the
draft and kept for the whole thing:

    perceived_i = adp_i + N(0, sigma_i)

Re-rolling that noise at every pick would make each bot a different person each
time it came on the clock, and would wash out exactly the persistent preferences
that make players go off-board. A manager who is high on somebody in round two
is still high on him in round nine.

`sigma` grows with ADP — the first round is near chalk and round twelve is
nearly random — and where the source publishes expert disagreement, that is
added in quadrature. Players the market cannot agree on are exactly the ones
whose draft slot is unpredictable, and one league-wide constant throws that
information away.

On top of the perceived board sit four adjustments:

| Mechanism | Effect |
|---|---|
| **Need bonus** | Unfilled starting slots pull a position forward, scaled by how few picks remain to fill them |
| **Positional run** | After a position goes 2+ times in the last six picks, the next bot leans that way |
| **Position caps** | Hard exclusion at 3 QB / 7 RB / 8 WR / 3 TE, so noise can never produce five quarterbacks |
| **Closing constraint** | When picks remaining equal starting slots still empty, need stops being a preference and becomes a restriction |

The last one exists because without it an unlucky bot finishes the draft with
no tight end, which no real drafter does, and which hands every other roster
free points in the grading.

---

## Marginal lineup value

The on-the-clock board is **not** ordered by value over replacement.

VOR answers "how good is this player." That is the wrong question once you
already have two running backs: the third one only plays when the flex wants him
or the first two are hurt, and no positional ranking knows what is already on
your roster.

`marginal_values()` asks the question the pick actually poses — how many points
does adding him put in my starting lineup — by re-optimising the lineup with and
without him. The roster is first **padded with replacement-level players in
every unfilled starting slot**. Without the padding, a candidate is measured
against a lineup with holes in it and every early pick looks equally enormous,
because anything beats nothing. The padding says what is true: the slot will get
filled by somebody, and the question is how much better than that somebody this
is.

Replacement is a **vector**, not a number: the (S,) points of the last startable
player at that position, replication by replication. Using his mean would compare
a candidate's good season against replacement's average one.

The diminishing return then falls out of the arithmetic rather than being
asserted by a positional rule.

---

## Grading

Every roster is scored on the same replications, so the finish inside a season is
a real head-to-head and the title odds mean something. Three things follow, and
all three are printed under the table:

1. **Lineups are optimal in hindsight.** A team starting two running backs
   starts its best two *in each simulated year*, not the two it drafted highest.
   That is best-ball scoring and it pays depth more than a manager setting a
   lineup each Sunday ever collects. The overstatement is roughly common across
   teams, so comparisons survive it; the absolute number is not a projection.
2. **Rosters share replications.** The season where a quarterback throws for
   5,000 yards is the season his receiver catches them, so a team stacked on one
   offence swings together — visible in its range, invisible in its mean.
3. **The circularity.** A seat drafting this model's board is then graded by
   this model. Read the gap between seats, not its level.

---

## Measured: does the model's board beat the market?

24 draft rooms per strategy, seat 5 of 12, 15 rounds, Full PPR, 3,000 simulated
seasons per room, FantasyPros consensus board of 2026-08-07. Every room is a
fresh draw of eleven opponents' perceived boards; the ± is the standard error
across rooms.

| your seat's strategy | title odds | playoff odds | mean finish | worst room |
|---|---:|---:|---:|---:|
| `adp` — draft the market board, like the bots | **7.08% ± 1.04** | 48.2% ± 2.9 | 6.64 | 1.1% |
| `vor` — best value over replacement left | 58.58% ± 2.13 | 96.6% ± 0.7 | 2.00 | 25.7% |
| `value` — best marginal lineup value | **63.44% ± 1.06** | 97.7% ± 0.2 | 1.82 | 54.8% |

**The `adp` row is the control and it is the important one.** A seat drafting the
same board as everyone else lands at 7.1%, against the 8.3% a twelve-team league
gives by construction. The machinery is not manufacturing an edge from nothing.

**Marginal value beats raw VOR, but the mean is not where it wins.** The gap in
title odds is 4.9 points against a combined standard error of about 2.4 — right
at two sigma, suggestive rather than settled. The unambiguous result is the
spread: VOR's standard error is twice as large, and its worst room out of 24
finished at 25.7% while marginal value's worst was 54.8%. VOR occasionally builds
a roster it cannot start — in the single room first tested it took six running
backs — and craters. Marginal value never does.

So the honest summary is **variance reduction, not a large mean gain**. That is
still worth having: a strategy whose bad case is 55% is better than one whose bad
case is 26% at the same mean.

**A single room measures nothing.** The first room run for this comparison had
VOR *ahead* of marginal value, 64.4% to 62.0%, which is inside the room-to-room
range of both. `--rooms N` exists so that mistake is hard to make.

### The bug this comparison caught

The first version of `marginal_values` padded the unfilled *positional* slots
and forgot the flex. That is not a small error. With two replacement running
backs in the RB slots and a vacant flex, adding any back pushes a replacement
down into the empty flex where he scores against nothing — so the candidate's
gain comes out as his entire projection rather than the ~150 points he is worth
over the man he displaces. Every player's gain equalled his projected points,
the ordering silently collapsed to raw projection, and the whole statistic did
nothing.

It was visible on the interactive board as a `Gain` column identical to `Proj`
in every row, which is why the display is worth having even when the number is
also fed to a bot. Padding the flex moved the strategy from 62.86% to 63.44%
and its worst room from 53.4% to 54.8%.

### Reproducing it

```bash
for s in adp vor value; do
  python -m nflsim draft --source fantasypros --seat 5 --strategy $s --rooms 24
done
```

---

## Things that are known to be missing

- **No in-season lineup decisions.** Grading is season-total best-ball. Weekly
  start/sit, the waiver wire, byes and trades are all absent, and each of them
  is worth real points that this cannot see.
- **No keeper or auction formats.** Snake only.
- **Bots do not stack, handcuff, or read the room.** They follow ADP with need
  and runs. A real league has at least one person who drafts his own team's
  players and one who takes a kicker in round nine.
- **The `wait` probability ignores need and run bonuses**, which only ever pull
  a position forward. It is an upper bound: if it says a tight end is 60% to
  last, he is 60% at best.
- **ESPN is the intended default and has never been exercised end to end.** The
  environment this was built in cannot reach `fantasy.espn.com`, so the payload
  parser is unit-tested against a recorded response shape rather than a live
  one. The first live run should be checked against ESPN's site by eye.
