# Week-to-week variance: what was wrong, and what was only wrong-looking

Reported symptom: *"a player averaging eighty yards per game gets around eighty
to ninety yards per game. You might have a game where you have thirty yards and
a game where you have a hundred and fifty."*

Correct observation, and it split into two separate things — one a display bug,
one a real modelling gap in a narrower place than it first appeared.

---

## 1. The display bug, which is what was actually on screen

The HTML report's game-by-game table showed `weekly_stats[w, stat, player]`,
which is `week_buf.mean(axis=1)` — **the mean across all ten thousand
replications for that week**. A mean is a mean. An 80-yard receiver shows 80
yards every week, and the only movement between weeks is opponent and pace
nudging the mean by a few yards. That is exactly the 80-to-90 pattern reported.

The distribution was there the whole time and simply was not rendered. Zay
Flowers, week 1, receiving yards, from the same buffer the table was reading:

| p10 | mean | p90 |
|---:|---:|---:|
| 28 | 76 | 136 |

**Fixed.** `season.py` now captures `weekly_stat_q` — the 10th, 50th and 90th
percentiles of every stat, per week, **conditioned on the replications where the
player was on the field**. The conditioning matters: averaging the universes
where he was hurt into the tenth percentile makes every starter's floor zero,
which says nothing about the shape of a game he actually plays. The weekly table
now renders each stat as floor–mean–ceiling.

---

## 2. The real variance, measured

Once the injury zeros are handled correctly, simulated weekly spread against
real game-log spread (2023–25, players with ≥10 games):

| position | simulated cv | real cv | ratio |
|---|---:|---:|---:|
| QB | 0.381 | 0.470 | **0.81** |
| RB | 0.741 | 0.588 | 1.26 |
| WR | 0.755 | 0.654 | 1.15 |
| TE | 0.773 | 0.676 | 1.14 |

Matched on scoring level, which is the more useful cut:

| points/game | sim sd | real sd | ratio |
|---|---:|---:|---:|
| 5–9 | 5.84 | 5.20 | 1.12 |
| 9–13 | 7.47 | 6.95 | 1.13 |
| 13–17 | 8.57 | 7.57 | 1.13 |
| **17–22** | **6.91** | **8.37** | **0.85** |

**Two errors pointing in opposite directions.** Mid- and low-scoring players get
too much weekly spread; the elite tier — 17–22 points a game, which is the top
of the draft board — gets too little, and so do quarterbacks. The model
compresses toward the middle. The reported symptom is real precisely for the
players a draft is about.

---

## 3. Where the missing variance is: opportunity, and almost entirely for backs

A fixed weekly share can only produce binomial sampling noise on the play count.
Measuring the dispersion of the *weekly share itself* against that binomial
floor isolates the game-to-game role variation the engine cannot express — net
of the game-script variation it already simulates.

**WR/TE target share**

| share band | real sd | binomial sd | ratio |
|---|---:|---:|---:|
| 0.05–0.10 | 0.0507 | 0.0474 | 1.07 |
| 0.10–0.15 | 0.0676 | 0.0588 | 1.13 |
| 0.15–0.20 | 0.0763 | 0.0676 | 1.10 |
| 0.20–0.35 | 0.0822 | 0.0763 | 1.08 |
| **all** | 0.0660 | 0.0605 | **1.08** |

**RB rush share**

| share band | real sd | binomial sd | ratio |
|---|---:|---:|---:|
| 0.10–0.25 | 0.1220 | 0.0785 | 1.58 |
| 0.25–0.40 | 0.1843 | 0.0984 | **1.82** |
| 0.40–0.55 | 0.1907 | 0.1035 | **1.82** |
| 0.55–0.90 | 0.1479 | 0.0975 | 1.56 |
| **all** | 0.1454 | 0.0937 | **1.65** |

**Receivers are fine.** At 1.08× the binomial floor, essentially all of a
receiver's weekly target variation is already sampling noise the engine
produces. There is nothing to add.

**Backs are not.** Real weekly rush share moves 1.65× what a fixed share can
generate, and the gap is worst in the middle of the distribution where committee
splits actually move — 1.82× for backs in the 25–55% share range. Closing it
needs a per-game role multiplier with a coefficient of variation around **0.37**
for RB and **0.17** for WR/TE.

The engine draws `role` once per **season** (`draw_role_factors`), so within a
season every game gets the same share. That is the mechanism. Game script moves
the *team's* carry count, and the back takes a fixed cut of a bigger or smaller
number — but in reality the script moves his cut too. A team that goes up three
scores feeds its lead back; a team down three scores benches him for a
pass-catcher. Share and script are correlated in a way a season-constant
multiplier cannot represent.

---

## 4. Why this is not yet fixed in the engine

Because adding it alone would make the overall picture worse. Section 2 shows RB
weekly spread is already **1.26× too wide**, while section 3 shows RB
*opportunity* spread is **1.65× too narrow**. Both are true. The excess is
coming from somewhere else — most likely per-play efficiency draws, or
touchdown lumpiness — and it is currently compensating for the missing
opportunity variance by accident.

Adding a per-game role multiplier without first finding and correcting the
over-dispersed component would push RB weekly variance from 1.26× to well past
1.5×. The right order is:

1. Decompose simulated weekly variance into opportunity and efficiency
   components and compare each against reality separately, the same way
   `backtest.py` decomposes season error into health and rate.
2. Correct whichever efficiency term is over-dispersed.
3. **Then** add the per-game role multiplier, RB-only, cv ≈ 0.37, drawn per game
   rather than per season.
4. Re-check the elite tier specifically — the 17–22 points/game band at 0.85 is
   the number that has to move, and league-wide averages will hide it.

Each step needs the walk-forward test in `RESEARCH_LOOP.md`. Note that this also
interacts with the conformal calibration in `calibrate.py`, which is currently
widening season intervals to compensate for narrowness that is partly this.

---

## 5. What changed now

- `season.py` captures `weekly_stat_q` (p10/p50/p90 per stat per week,
  conditioned on playing) and `weekly_fp_live` (p10/p90 of weekly fantasy
  points, likewise conditioned).
- `report_html.py` and the template render each weekly stat as floor–mean–ceiling
  instead of a bare mean.
- Result files written before this still load; the report falls back to means.

No change to the engine's behaviour. The numbers it produces are identical — the
report now shows more of them.
