# Vacated usage: was the workload earned, or was somebody hurt?

`python -m nflsim room`

## The hypothesis

`fit_usage` pools every game a player appeared in and weights only by season
recency. It cannot tell the difference between carries taken while the room was
whole and carries that existed because the man beside him was out. A back who
saw twenty touches for six weeks with the starter injured has those weeks folded
into his baseline at full strength — and the simulator then applies its *own*
injury cascade on top, so the same vacated work is counted once in the prior and
again in the draw.

## What the data says

Opportunity share is `(targets + carries) / (team targets + team carries)`,
per player per week, 2022–2025. A room is "whole" when every other player at
that position on that team who normally takes snaps took snaps that week,
weighted by his usual snap rate.

| position | whole room | depleted room | what `fit_usage` fits | vacated |
|---|---:|---:|---:|---:|
| RB | 16.81% | 19.40% | 18.43% | **+1.62pp** (9% of the baseline) |
| WR | 7.55% | 8.03% | 7.91% | +0.36pp (5%) |
| TE | 5.05% | 5.54% | 5.35% | +0.30pp (6%) |

Narrowed to backups specifically — players with somebody ahead of them — the
effect is much larger: **a second running back's share nearly doubles when the
man ahead of him is out**, 10.4% to 18.5%.

The individual cases are the point. As of the 2022–2025 window:

| player | whole room | depleted | fitted | vacated | healthy games |
|---|---:|---:|---:|---:|---:|
| Jordan Mason | 3.82% | 22.39% | 21.21% | +17.39pp | 6 |
| Aaron Jones | 21.19% | 33.51% | 32.92% | +11.72pp | 6 |
| **Tyrone Tracy Jr.** | **19.54%** | **31.61%** | **28.06%** | **+8.53pp** | 8 |
| Breece Hall | 28.34% | 37.61% | 36.22% | +7.88pp | 9 |
| Brian Robinson | 11.10% | 29.45% | 18.91% | +7.81pp | 18 |

**Tracy is the clearest case among lead backs, and it is not small.** Roughly
30% of his fitted usage baseline is work that existed only because someone else
was hurt. 2025 splits cleanly in two: weeks 1–8 with the room whole, mean share
21.2%; weeks 9–18 with the room at 35% health, mean share 33.3%. The model fits
28.4%. 2024 is more extreme still — 10.5% whole against 29.7% depleted — though
only two of those games had a fully healthy room, so that number is thin.

Note the `healthy games` column throughout. A player seen with a whole room
three or four times has a noisy estimate and the gap should be discounted
accordingly; `--min-inflation` filters on size, not on reliability.

## Why this is a diagnostic and not a correction

The obvious fix is to fit shares on whole-room games only and let the
simulator's cascade regenerate the redistribution. That was tested and it does
not clear the project's promotion gate.

**Test.** Compute room inflation on the 2021–2024 training window — the same
seasons and the same 1.1-season half-life that fed the 2025 projection — and
correlate it with the 2025 backtest error. `error` is projected minus actual, so
a model that carries an inflated baseline into a season must over-project the
inflated players. The correlation has to be positive.

| cohort | Pearson | Spearman | n |
|---|---:|---:|---:|
| all | −0.023 | −0.001 | 224 |
| RB | +0.066 | +0.099 | 58 |
| WR | −0.185 | −0.133 | 89 |
| TE | +0.136 | +0.047 | 77 |

Essentially zero, and the positions disagree on the sign.

The one encouraging cut is the RB gradient by inflation quartile:

| quartile | mean inflation | mean 2025 error |
|---|---:|---:|
| Q1 | −0.02 | −3.6 |
| Q2 | +0.02 | −9.2 |
| Q3 | +0.04 | +10.0 |
| Q4 | +0.08 | **+17.3** |

Monotone and in the predicted direction, a 21-point swing from Q1 to Q4. But
with 14–15 backs per bin and RB errors running near 70 points of MAE, the
standard error per bin is about 17 points — the Q1-to-Q4 gap is under one sigma.
Suggestive; not evidence.

**Why the effect is smaller than the raw shares suggest.** Two dampers sit
between the contaminated input and the projection:

1. **Normalisation.** `build._confidence_norm` rescales every share inside an
   offence to sum to one. Inflation common to a whole room cancels exactly. Only
   the part that differs *between* teammates survives — which is why the
   position-level table above (+1.62pp for RB) overstates what actually reaches
   the projection.
2. **Shrinkage.** A player's own history is blended toward a depth-chart
   baseline with confidence `eff_games / (eff_games + 8)`, and further discounted
   if he changed teams. The players with the most inflation are usually backups
   with thin samples, who are shrunk hardest.

So the mechanism is real in the usage data and largely absorbed by machinery
that already exists. That is a good outcome for the model and a boring one for
the hypothesis.

## What would settle it

The project's gate is three walk-forward seasons without a calibration
regression, bootstrapped by team-season because player rows are not
independent. What is needed:

- Backtests for 2022 and 2023 to go with 2024 and 2025, so the RB gradient has
  four seasons rather than one.
- The comparison run as an actual model change — refit shares whole-room-only,
  re-simulate, score — rather than as a correlation against the existing
  projection. A correlation cannot see the normalisation and shrinkage
  interaction, and those are exactly where the effect is going.
- Team-season bootstrap for the interval, since the flagged players cluster on
  the teams that had the injuries.

Until then `nflsim room` prints the flag and changes nothing.

## Two ways the measurement itself went wrong

Both were silent, and both produced plausible-looking output:

- **Availability from a left join.** A player who does not dress has no
  snap-count row at all, so joining availability onto the games that happened
  drops him rather than marking him absent. Every room came back healthy —
  98.9% of player-weeks — and the whole effect disappeared. Availability has to
  come from an explicit grid of room members crossed with weeks played.
- **Depth ranked by snap total.** A starter who missed six games has fewer
  season snaps than the backup who replaced him, so ranking on the total calls
  the backup the starter and inverts the thing being measured. Rank on snap
  *rate*.

Bye weeks are masked from the schedule for the same reason the injury hazards
had to be: a team that did not play is not a team whose players were hurt.
