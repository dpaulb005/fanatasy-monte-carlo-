# Player ratings, and how much defence is worth

Two questions, researched together because the answer to both turned out to be
"less than you'd think, and the effort belongs elsewhere."

1. Should players be represented as Madden-style *ratings* and simulated from
   those, rather than as the empirical rate parameters the engine uses today?
2. How much is the model's thin defensive representation actually costing?

Three research agents plus original measurement on nflverse. Everything below
that is marked **[measured]** was computed here or by an agent against
play-by-play, not taken from a source.

---

## 1. Ratings: decline, and the reason is structural

**No public NFL system goes from ratings *to* simulated play outcomes.** The
direction is always the reverse — ratings compress outcomes into a scalar for
ranking. Every simulator built to actually forecast has no rating layer:
DraftKings' same-game-parlay engine chains fitted conditional models over game
state; SaberSim builds plays from scratch; [NFLSimulatoR](https://github.com/rtelmore/NFLSimulatoR)
resamples real plays and carries no player identity at all. Ratings dominate
*entertainment* simulators and are absent from *forecasting* simulators. That
correlation is the finding.

**The information argument.** A rating is a deterministic function of the data,
so by the data-processing inequality it cannot contain information about the
outcome that the data did not already carry. The proposal is
`data → rating → rates → outcomes` in place of `data → rates → outcomes`, and
the extra step can only lose. A rating is usable generatively only if it is a
sufficient statistic for `P(outcome | context, rating)`; Madden-style ratings are
ordinal summaries on an arbitrary 0–99 scale with no likelihood attached.

**The granularity is a fiction.** FM-Arena runs controlled Football Manager
experiments — hold a squad fixed, move one attribute 8→20, play tens of
thousands of matches. Pace and acceleration dominate so heavily that the
community conclusion is to ignore everything else. FM presents ~36 attributes;
the engine responds to perhaps 2–8. Building an NFL rating card means assigning
numbers whose influence on the output is nil, and not knowing which ones until
you have done more work than fitting the rates directly.

**Madden specifically.** Its franchise simulation is undocumented, independently
assessed at coin-flip accuracy, uses roughly half its nominal scale, and sets
ratings partly under social pressure from players and teams. Its own community's
loudest complaint is that the low-fidelity sim disagrees with the high-fidelity
one — which is precisely the failure a bolted-on rating sim would introduce
here: a second engine with its own calibration, drifting from the first.

**What the model already has.** `off_pass`, `def_pass`, `off_cpoe`, `def_cpoe`,
`off_ypc`, `def_ypc`, `off_sack`, `def_sack` *are* ratings — continuous,
denominated in outcome units, recency-weighted, shrunk toward league mean with
an explicit pseudo-count, and shrunk further on coaching turnover. The rating
concept is already implemented in its good form. Re-expressing it as 0–99
integers would destroy information and add a calibration surface.

### The one place a rating layer is legitimate

Rookies. A player with no NFL history needs pre-NFL observables projected onto
the same rate parameters the engine consumes. That is a **prior**, not a rating
layer, and the distinction matters: a prior is dominated by data as data
arrives, while a rating sits permanently between the data and the outcome. The
right shape is a small latent skill vector regressed onto `adot`, `catch_oe`,
`yac_mean`, target share and `ypc_oe`, kept continuous, blended in with the same
`(num + prior·k)/(den + k)` form already used elsewhere — a rookie is then just
a player with `den = 0`, no second code path.

---

## 2. The combination-function recommendation, tested and rejected

The strongest concrete proposal from the research was to replace additive-in-
probability combination with additive-in-log-odds — the odds-ratio method that
fifty years of baseball simulation converged on, with a documented failure mode
(Morey & Cohen 2015) where log5 regresses outliers toward .500 rather than
toward the league mean, badly overestimating rare events.

The engine currently sums over-expected terms on the probability scale and
clips:

```python
cp = np.clip(ph.comp_by_ay[ay_i] + field_oe + off.catch_oe[rec_j]
             + off.qb_cpoe[qb_j] + off.off_comp_oe + dfn.def_comp_oe
             + ..., 0.02, 0.98)
```

**[measured]** Held-out 2025 completion probability, 17,490 passes, offsets fit
on 2018–24 with identical empirical-Bayes shrinkage on both scales:

| player-term size | additive in probability | additive in log-odds |
|---|---:|---:|
| 4× shrinkage | 0.58303 | 0.58302 |
| current | 0.58328 | 0.58319 |
| ¼ shrinkage | 0.58389 | **0.58482** |
| none | 0.59439 | **0.66837** |

They tie where the model performs best, and **probability wins as the terms grow**
— the log-odds form blows up on small-sample players with extreme rates. The
predicted clipping pathology never fires: **zero plays clipped**, maximum raw
additive value 0.967.

The agent's own instruction was to run this before changing anything and keep
the existing form if they tied. They tied. **No change.**

---

## 3. What the same test revealed instead

**[measured]** Three-way split — fit on 2018–23, shrinkage constants chosen on
2024, reported on 2025 which was never used to choose anything:

| | held-out 2025 log loss |
|---|---:|
| air-yards curve only, no player terms | **0.58390** |
| current shrinkage constants | 0.58469 |
| validation-chosen constants | 0.58392 |

**The current constants make completion prediction worse than using no player
information at all.** Best achievable with tuned shrinkage is a dead heat with
the bare air-yards curve. Receiver `catch_oe`, QB `cpoe` and team `def_comp_oe`
are collectively adding nothing out of sample for per-play completion.

The chosen constants are the interesting part: receiver wants *more* shrinkage
than currently used (k = 500 vs 120), and **team defence wants k = 20,000 — the
grid is monotone all the way up, meaning the optimum is to shrink the defensive
completion adjustment away entirely.**

Caveat worth keeping: this measures marginal value for a *single play's*
completion, which is dominated by air yards, on one held-out season. It does not
prove the terms are worthless for season aggregates. But it does show the
shrinkage is miscalibrated in a direction that costs accuracy.

---

## 4. How much is defence worth? Measured, and the answer is: weekly, not seasonal

**[measured, by agent, 2007–2024: 584,140 plays, 9,342 team-games, 576
team-seasons]**

### Schedule variation is indistinguishable from random

Dispersion of season-long opponent quality, relative to the dispersion of a
single opponent:

| defensive metric | ratio |
|---|---:|
| EPA/play | 0.237 |
| pass EPA/play | 0.230 |
| sack rate | 0.263 |
| CPOE | 0.227 |
| YPC | 0.225 |

**1/√17 = 0.243.** Every ratio sits within 0.02 of it. For defensive-quality
purposes the NFL schedule is statistically indistinguishable from drawing 17
opponents at random — there is essentially no systematic imbalance to recover.

### The weekly/seasonal split, quantified

Same data, leave-one-out on both sides to remove circularity:

| | ΔR² from adding opponent defence |
|---|---:|
| one game | **0.035** |
| a full season | **0.001** |

A **35:1 ratio**. Even giving a season-long projection an oracle — the actual
realised quality of every defence faced — adds ΔR² = 0.000.

### In fantasy points, for the most extreme schedule in the league

| position | season total, typical #1 | effect of the league's most extreme schedule |
|---|---:|---:|
| QB1 | 241 PPR | ±5.9 (2.5%) |
| RB1 | 199 PPR | ±7.8 (3.9%) |
| WR1 | 221 PPR | ±2.9 (1.3%) |
| TE1 | 123 PPR | ±1.7 (1.4%) |

For a *typical* player, roughly half that — under 2%. **The thin defensive
representation is costing very little at the season level.**

### Team defence barely persists

Year over year, 2007–2024, n = 544:

| metric | defence | offence |
|---|---:|---:|
| completion % | 0.417 | 0.531 |
| YPC | 0.270 | 0.224 |
| EPA/play | 0.266 | 0.417 |
| CPOE | 0.233 | 0.441 |
| **sack rate** | **0.176** | 0.394 |

Every scalar currently used sits at r = 0.18–0.27, i.e. 3–7% of next-season
variance. **Sack rate is the least stable input in the model.** Within-season
split-half reliability puts a *full season* of defensive EPA at only ~0.48 —
half signal, half noise — and the ratio of year-over-year to within-season
correlation implies **~45% of a defence's genuine quality does not survive the
offseason**.

Metrics *not* currently used that are more stable than every one that is:
**air yards per attempt allowed 0.417**, explosive rush rate allowed 0.368, TD
rate allowed 0.317. Air yards allowed is a scheme signature rather than a
performance outcome, which is why it survives roster churn.

### Defence-vs-position: three of four are noise

Decomposing DvP into general defensive quality and a position-specific residual,
out-of-sample weeks 1–8 → 9+:

| position | same-position DvP | general quality | **position-specific residual** |
|---|---:|---:|---:|
| QB | 0.169 | 0.180 | **0.068** |
| RB | 0.312 | 0.123 | **0.310** |
| WR | 0.173 | 0.061 | **0.164** |
| TE | 0.112 | 0.096 | **0.100** |

**QB DvP is a fraud** — general defensive quality predicts QB points allowed
*better* than QB-specific DvP does. **TE DvP is noise** (split-half reliability
of the residual: 0.077). **RB DvP is real** and the strongest position-specific
defensive signal in football — but most of it is run-defence quality already
captured by rush EPA and YPC allowed.

### Player-level matchup: measured ceiling under 1.2%

The cleanest test available is a 2026 ridge-regularised Bradley–Terry model over
153,138 blocker–rusher interactions with a proper holdout — the most favourable
possible case, since trench assignment is observable and one-to-one. Result:
**0.24%–1.21% relative log-loss reduction.** Coverage, where assignment is
ambiguous and shared, will be worse.

Shadow corners: the widely-cited "38–42% reduction" figures are selection-biased
(shadow corners are assigned to the best receivers in the most game-planned
games). The defensible number is **±13% on points per target** between an elite
and a poor corner — and quarterbacks throw away from elite corners, converting
some efficiency loss into volume loss, which partly cancels.

### A correction to something stated earlier in this project

Measuring persistence here found edge/DL pressure rate at r ≈ 0.61 against DB
coverage at r ≈ 0.21, and the natural conclusion was "model pass rush, not
coverage." **That is a non-sequitur.** Stability is not predictive value. PFF's
data study reports coverage grade predicting *next-year* pass EPA allowed at
r ≈ −0.26 while pass rush is roughly uncorrelated with it. Pass rush is the
more stable thing and the less useful thing. Both statements are true at once.

---

## 5. Where this leaves the model

Nothing has been changed. The items below are candidates, in value order, and
each still needs the walk-forward test in `RESEARCH_LOOP.md` before it becomes a
default.

**Worth doing**

1. **Increase shrinkage on the defensive scalars, sack rate hardest.** Measured
   reliabilities imply a preseason carry-over near 0.25–0.30 for most scalars and
   ~0.19 for sack rate. The independent completion-probability test above points
   the same way and more aggressively. This is the cheapest change and the
   best-evidenced.
2. **Add air-yards-allowed and explosive-rate-allowed as defensive terms.** Both
   are already in nflfastR, both are more stable than anything currently used,
   and they close part of the WR/TE representation gap.
3. **Replace sack rate with pressure rate, or model sacks as pressure ×
   conversion.** Pressure rate is roughly twice as reliable. Note that an
   earlier test here found the *decomposition* does not beat the aggregate on
   stability (QB-level sack rate 0.501, pressure rate 0.512, conversion 0.352),
   so the case is about the input being more stable, not about splitting it.
4. **Use the two dead fields or delete them.** `def_pass_epa` and `def_rush_epa`
   are fit, shrunk, stored on `TeamModel` and never read by the engine.
5. **Student-t rather than Gaussian noise** wherever EPA-like quantities are
   drawn — the posterior-predictive check on EPA fails visibly for Gaussian.

**Not worth doing**

- QB or TE defence-vs-position. Both are noise; general defensive quality
  outpredicts QB DvP outright.
- Shadow-corner or WR/CB matchup modelling. Real effect ±13% per target, mostly
  cancelled by target redistribution, and it averages away over 17 games.
- Any player-level defensive matchup layer. Measured ceiling under 1.2% relative
  log-loss on the most favourable problem in the sport.
- Opponent-adjusting the defensive ratings themselves. Published result: it
  makes defensive EPA *less* predictive (0.0127 → 0.0123).
- Preseason strength of schedule, in any form.

**The one-line version.** Defence-adjustment is a weekly phenomenon that almost
perfectly averages out over a season — 35:1. The binding constraint is not the
representation of defence but the *predictability* of defence, which caps the
whole enterprise at R² ≈ 0.04–0.13. Usage, target share, snap share and injury
modelling will repay effort far better.

---

## Sources

Research agents, August 2026. Primary references:

- [nflWAR — arXiv 1802.00998](https://arxiv.org/abs/1802.00998) · [code](https://github.com/ryurko/nflWAR)
- Morey & Cohen (2015), *Bias in the log5 estimation of outcome of batter/pitcher matchups* — [J. Sports Analytics 1:65–76](https://journals.sagepub.com/doi/10.3233/JSA-150005)
- Sabin (2021), *Estimating player value in American football using plus-minus models* — [JQAS 17(4)](https://www.degruyter.com/document/doi/10.1515/jqas-2020-0033/html)
- [NFLSimulatoR — arXiv 2102.01846](https://arxiv.org/pdf/2102.01846)
- Open Source Football: [estimating team ability from EPA](https://opensourcefootball.com/posts/2021-06-27-estimating-team-ability-from-epa/) · [adjusting EPA for opponent](https://opensourcefootball.com/posts/2020-08-20-adjusting-epa-for-strenght-of-opponent/) · [rolling averages of EPA](https://opensourcefootball.com/posts/2020-12-29-exploring-rolling-averages-of-epa/) · [defences vs WR1](https://opensourcefootball.com/posts/2021-07-30-evauluating-defenses-by-how-well-they-play-the-offenses-wr-1/)
- [Bradley–Terry over blocker–rusher interactions — arXiv 2604.01491](https://arxiv.org/abs/2604.01491)
- [DVOA v8.0](https://ftnfantasy.com/nfl/introducing-dvoa-v8-0) · [DVOA methods](https://www.footballoutsiders.com/info/methods)
- [DraftKings: mastering football simulation](https://careers.draftkings.com/life-at-draftkings/engineering/mastering-the-art-of-football-simulation/) · [SaberSim](https://www.sabersim.com/how-it-works)
- [FM-Arena attribute testing](https://fm-arena.com/table/26-player-attributes-testing/)
- [PFF: coverage vs pass rush](https://www.pff.com/news/pro-pff-data-study-coverage-vs-pass-rush) · [effect of opposing cornerbacks](https://www.pff.com/news/fantasy-football-the-effect-of-opposing-cornerbacks-on-a-receivers-fantasy-stats)
- [4for4: do defenses repeat](https://www.4for4.com/2026/preseason/do-defenses-repeat-fantasy-football-performances)
