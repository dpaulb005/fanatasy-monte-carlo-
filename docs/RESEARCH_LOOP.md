# Continuous research and experiment loop

This project treats new fantasy ideas as hypotheses, not features. Every cycle
uses three independent roles:

1. **Data scout** — finds newly accessible primary data and documents coverage,
   licensing, release timing and timestamp fields.
2. **Model skeptic** — searches for leakage, double counting, unstable effects
   and simpler explanations.
3. **Validation auditor** — defines rolling-origin tests before implementation,
   including cohorts, calibration metrics and rejection rules.

No researched signal becomes a default merely because it moves projections.
It must improve at least three walk-forward seasons without a material
calibration regression. Player rows are not independent, so uncertainty should
be bootstrapped by team-season.

## Current research queue

### Implemented and measurable now

- Controlled league-wide factor-off simulations for injuries, role volatility,
  team efficiency uncertainty, coaching scheme and full team context. These
  include teammate/opponent interactions and are not isolated causal effects.
- Teammate pressure and usage concentration: target/carry/goal-line shares,
  within-position role margin and team HHI.
- Conditional backup value and ceiling anatomy from coherent simulation
  replications.
- Backtest error split into games-played error and points-per-game error.
- Correct team-specific roster continuity and historical-season player ages.

### Next candidate: WR participation exposure

The weekly-stat feed omits active zero-target games, which biases opportunity
estimates upward. A direct rolling usage test found a small WR-only improvement
when snap-count exposure rows were included, but RB and TE worsened. Implement
as an opt-in build strategy and require full 2021–25 simulation backtests before
promotion.

### Gated candidate: correlated role simplex

Independent lognormal role multipliers are normalized inside each offense, but
they do not model a coherent team-level “narrow target tree” or separate target
and rushing role shocks. The safe candidate is a low-rank logistic-normal model
with separate target and rush channels, a shared RB factor, and deterministic
mean calibration after normalization. Do not fit a full player covariance
matrix: there are too few stable team-season observations.

Promotion requires:

- marginal simulated shares remain within 0.1 percentage point of their priors;
- improved role-share error and weighted interval score;
- better held-out teammate covariance and concentration distributions;
- no material MAE or coverage regression in 2021–25 walk-forward tests.

### Research-only data paths

- [nflverse participation](https://nflreadr.nflverse.com/reference/load_participation.html)
  can support pass-play participation and personnel-package exposure. It is a
  route proxy, not true routes run for every receiver.
- [FTN charting through nflverse](https://nflreadr.nflverse.com/reference/load_ftn_charting.html)
  provides motion, play action, screens and RPO flags from recent seasons, but
  no player identity. Start with coach/personnel scenarios, not causal “motion
  bonuses.”
- [NFL Next Gen Stats](https://operations.nfl.com/gameday/technology/nfl-next-gen-stats)
  confirms tracking-derived formation, route-detection, completion-probability
  and expected-rushing-yards data. Public aggregates are useful; raw tracking
  is not generally available.

## Rejection and leakage rules

- Freeze every input before September 1 of the projected season.
- Never use target-season participation, depth charts or injury reports.
- Do not transport a raw coach positional-share effect to a new team without a
  coach-switch holdout test. Initial research found persistence for continuing
  coach/team combinations but unstable transfer across team switches.
- Do not wire stored EPA residuals into play outcomes without first proving
  they add information beyond the CPOE, YPC and sack effects already consumed.
- Use external projections, ADP and props only as benchmarks/disagreement
  reports, never as hidden model inputs.
