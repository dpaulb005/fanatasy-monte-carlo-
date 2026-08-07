# Factor experiment findings

Generated 2026-08-07 from the `dev` branch.

## Exploratory 2026 sensitivity run

The first factor sweep used 500 simulations per scenario, seed `20260807`, Full
PPR, 608 players and six controlled league-wide scenarios. It is useful for
finding large effects and debugging the framework, but not for trusting small
tail differences. Use at least 5,000 simulations before making draft decisions
from p90 or contingent-value differences.

Among projected fantasy starters, the median sensitivities were:

| cohort | all-healthy environment | role-system p90 lift | median absolute scheme sensitivity | median absolute full-context sensitivity |
|---|---:|---:|---:|---:|
| QB top 12 | +38.0 | -0.9 | 3.0 | 9.2 |
| RB top 24 | +20.5 | +50.9 | 3.4 | 5.6 |
| WR top 36 | +12.2 | +52.9 | 4.1 | 5.2 |
| TE top 12 | +12.3 | +48.9 | 4.6 | 3.8 |

Large, potentially durable observations:

- Role uncertainty is the dominant source of tail width for draftable RB, WR
  and TE players. This supports researching a team-correlated role simplex, but
  does not validate one yet.
- QB uncertainty is much more availability/environment driven than role driven.
- Team efficiency shocks produced small and noisy marginal p90 changes in this
  exploratory run. They should not be enlarged merely to widen intervals.
- Cincinnati and Kansas City players had several of the largest absolute
  league-scheme sensitivities. Because the intervention neutralizes every team,
  this is not a clean estimate of one coach's causal value.
- The conditional-backup table is dominated by quarterbacks. Position-specific
  views and higher simulation counts are needed before using it for RB
  handcuff decisions.

## Corrected 2025 backtest

The 1,000-simulation 2025 backtest uses projected-season age, same-team roster
continuity and snap-count games played. Headline results remain close to the
prior handoff, which is reassuring: pooled top-200 correlation `.599`, rank
correlation `.594`, MAE `60.7`, bias `+5.7`.

The new symmetric error decomposition diagnoses the open RB problem:

| position | MAE | mean absolute games-played component | mean absolute points-per-game component | health bias | rate bias |
|---|---:|---:|---:|---:|---:|
| QB | 68.0 | 55.6 | 28.3 | -12.2 | +7.3 |
| RB | 69.2 | 38.1 | 47.6 | +1.4 | +7.4 |
| WR | 60.1 | 31.3 | 42.0 | +2.2 | +7.8 |
| TE | 39.1 | 23.1 | 36.8 | +1.8 | -1.9 |

For RB, scoring rate while active is the larger error component and explains
most of the upward bias. The next experiment should therefore target workload
and per-game opportunity—not simply increase injury variance. QB is the
opposite: games-played error dominates, so job-security and injury-state work
belongs there first.

These two absolute components can overlap and partially cancel; they are an
exact algebraic decomposition player by player, but their mean absolute values
are not expected to sum to MAE.

