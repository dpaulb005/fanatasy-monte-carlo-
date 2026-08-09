# Why is this player projected there?

`python -m nflsim why "Rhamondre Stevenson"`

Prints the chain behind one projection: what the player actually did, the
recency-weighted mean of it, the shrinkage blend toward his depth-rank
baseline, what the engine was finally handed after team normalisation, and the
room around him. Three case studies below, worked through with that command,
plus what generalised and what did not.

---

## Where age enters the model: one place, and it is not usage

Grepping for it gives a single call site — `age_injury_multiplier`, which
raises the weekly injury hazard. **There is no aging curve on usage or on
efficiency anywhere in the model.** A 37-year-old's target share and yards per
reception are carried forward at full strength.

Worse, for a durable veteran the one age term that exists gets cancelled. The
hazard is `base × age_injury_multiplier(age) × avail_mult`, and `avail_mult` is
the player's own availability history. Travis Kelce's is 0.635, so his personal
durability record eats the age penalty and he is projected for 15.3 games at 37.

### Does that show up as a measurable bias?

2025 backtest error by age band (`error` = projected − actual; positive means
over-projected):

| age | mean error | mean abs error | n |
|---|---:|---:|---:|
| 25–28 | −9.5 | 54.2 | 62 |
| 28–31 | **+20.7** | 41.0 | 83 |
| 31–34 | **+21.4** | 52.9 | 46 |
| 34+ | +4.3 | 47.6 | 16 |

A ~30-point swing between the 25–28 and 31–34 bands, in the direction a missing
aging curve predicts. The 34+ cell is only sixteen players and its standard
error is around 12 points, so it neither confirms nor contradicts.

### The trend hypothesis, which failed

The tempting general story is that a recency-weighted mean of *levels* always
sits between the observations, so a player in a straight-line decline is
projected above his most recent season. That is arithmetically true — it is
exactly what happens to Kelce below — but it does not generalise into a
measurable bias. Correlating each player's 2021–24 points-per-game trend with
his 2025 error:

| cohort | Pearson | Spearman | n |
|---|---:|---:|---:|
| all | −0.091 | −0.014 | 207 |
| QB | +0.215 | +0.310 | 24 |
| RB | −0.216 | −0.179 | 48 |
| WR | −0.054 | −0.061 | 85 |
| TE | −0.175 | +0.084 | 50 |

And the quartile table is not monotone: steepest decliners average +8.0 points
of error, the third quartile +20.7, the steepest risers +4.2. **Trend is not a
usable correction.** Age band is the better handle.

---

## Case 1 — Travis Kelce, TE2, 195 projected

| season | targets | target share | ppg |
|---|---:|---:|---:|
| 2022 | 152 | 24.9% | 18.6 |
| 2023 | 121 | 22.7% | 14.6 |
| 2024 | 133 | 24.1% | 12.2 |
| 2025 | 108 | 19.7% | 11.4 |

Four consecutive declines, points per game down 39% across the window. The
model projects **12.7 ppg** — which is the recency-weighted mean of
11.4/12.2/14.6/18.6 almost exactly, and 11% *above* what he did last year at 36.

That is the arithmetic above, working as designed and pointing the wrong way for
this player. Nothing in the model can express "he is a year older." His
touchdown conversion is +9% versus league, so that is not the cause; the
`validate` cohort table also shows the TE top-12 running +6.7% hot generally.

**Verdict: agree, and the mechanism is identified.** A weighted mean of levels
with no age term cannot project a decline to continue.

---

## Case 2 — Rhamondre Stevenson, RB14, 206 projected

The strongest of the three, because every link in the chain moves the same
wrong way.

| season | carries | rush share |
|---|---:|---:|
| 2022 | 210 | 49.4% |
| 2023 | 156 | 50.6% |
| 2024 | 207 | 53.1% |
| 2025 | 130 | **31.9%** |

TreVeyon Henderson arrived and took the backfield. Then:

| step | rush share |
|---|---:|
| what he did in 2025 | 0.319 |
| recency-weighted over four seasons | 0.417 |
| shrinkage toward the **depth-1** RB baseline (0.480) at confidence 0.78 | 0.431 |
| after normalisation inside the offence | **0.480** |

The single most informative fact about him is halved by recency weighting, then
partly *reversed* by shrinkage — because the depth chart still lists him RB1, so
the baseline he is pulled toward is the one for a lead back. Normalisation then
lifts him the rest of the way back to the baseline he started from.

His goal-line carry share is **62.7%**, which produces 7.7 rushing touchdowns.

Note this is the mirror image of the depth-rank penalty that was tested and
removed (see the comment block in `build.py`). That penalty fired when history
implied a *better* job than the depth chart. This is the case where the chart
and the history agree on the label and disagree on the workload, and the
baseline attached to the label wins.

**Verdict: agree, and this is the one worth fixing.**

---

## Case 3 — Zay Flowers, WR3, 274 projected

Here the answer is that the model is not doing anything unusual.

| season | targets | target share | rec | yards | TD | ppg |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 108 | 24.0% | 77 | 858 | 5 | 12.9 |
| 2024 | 116 | 25.4% | 74 | 1059 | 4 | 12.3 |
| 2025 | 118 | **29.0%** | 86 | 1211 | 5 | 14.3 |

His share is rising, and **the model projects 25.9% — below his 2025 actual.**
The volume input is conservative, not aggressive. Yards per reception comes out
at 13.0 against 14.1 actual, also conservative. He is durable (personal
multiplier 0.570), so he gets 15.7 games.

The whole gap is touchdowns: **8.7 projected against a career range of 4–5**,
worth 22 fantasy points on its own. So the obvious hypothesis is that the model
is missing player-level red-zone skill — and it is true that it has none. Within
a position, red-zone share is overall target share times a fixed positional
multiplier, identical for every player:

| position | rz share ÷ target share | sd across players |
|---|---:|---:|
| RB | 0.960 | 0.008 |
| TE | 1.167 | 0.010 |
| WR | 0.940 | 0.008 |

And real conversion varies enormously — 0.143 for George Pickens to 0.457 for
Mark Andrews, sd 0.079 around a league rate of 0.238. Flowers himself converts
at 0.189, 20% below league.

**But it does not persist.** Correlating each player's 2022–23 red-zone TD rate
with his own 2024–25 rate, for the 45 players with at least 20 red-zone targets
in both halves: **r = −0.047**. Conversion rate is noise. The model is right to
hold it constant, and Flowers' three below-average touchdown seasons do not
predict a fourth.

What is left is ordinary: Baltimore is projected at 460 points (27.1 a game)
against 424 actual in 2025, and the `validate` cohort table shows the top WR
running **+18.9%** hot — the long-standing WR bias recorded in `HANDOFF.md`.

**Verdict: disagree that Flowers is the problem.** His inputs are conservative;
he is high because he is durable, on a top-projected offence, with touchdowns
regressed to a league average that the data says is the right call. If anything
is wrong here it is the general top-WR inflation, which is already the number
one open problem.

---

## What to do next

1. **An aging curve on usage and efficiency**, fitted from within-player
   year-over-year deltas — never cross-sectionally. The cross-sectional table is
   badly survivorship-biased: tight ends aged 34–36 average a *higher* target
   share than tight ends under 26, because the only 35-year-old tight ends still
   playing are the good ones. Fitting that curve directly would make old players
   better.
2. **Stop shrinkage from raising a displaced starter.** Where the most recent
   season disagrees sharply with the depth-rank baseline in the direction of
   *less* work, the baseline should not pull him back up. Needs the usual
   walk-forward test before it becomes a default.
3. Leave red-zone conversion alone. It was measured and it is noise.
