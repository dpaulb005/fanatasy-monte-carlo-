# Projection landscape and dashboard decisions

Research reviewed 2026-08-07. This is a product and modelling comparison, not
an endorsement of any commercial source. External projections remain a
benchmark only and are never blended into `nflsim`.

## What established fantasy products emphasize

| Source | Publicly described inputs or method | What nflsim should learn from it |
|---|---|---|
| [PFF projection methodology](https://www.pff.com/news/fantasy-the-logic-behind-pffs-fantasy-projections) | Projected game scores, team and player volume, target/carry share, air yards, red-zone opportunities, blocking and defensive grades | Volume and game context belong upstream of player outcomes. `nflsim` already models both at play level; the dashboard should expose the resulting uncertainty. |
| [PFF projection FAQ](https://profootballfocussupport.zendesk.com/hc/en-us/articles/360023131813-How-does-PFF-develop-their-Fantasy-rankings-and-Fantasy-projections) | Expected snaps, strength of schedule, teammate quality, upside/downside distributions, analyst judgment | Distribution and teammate competition matter. We expose finish and starter probabilities without adding subjective overrides. |
| [FantasyPros accuracy method](https://www.fantasypros.com/about/faq/football-draft-accuracy-methodology/) | Preseason snapshots, position-specific cohorts, weighted absolute error | Backtests need frozen, relevant cohorts and absolute error, not only correlation. The existing backtest follows that direction and the dashboard states its calibration caveat. |
| [FantasyPros product overview](https://www.fantasypros.com/about/) | Expert consensus, multiple scoring formats, mock drafts and live draft support | Users need decisions, not another static projection list. The draft lab directly compares players under the selected league shape. |
| [nflverse data repository](https://github.com/nflverse/nflverse-data) | Versioned play-by-play, rosters, weekly stats, snap counts, schedules and related public NFL datasets | Keep primary-data provenance and reproducible caches. Do not silently import a competitor's point estimate. |

## Implemented Monte Carlo advantage

The HTML report now exposes information that a mean projection or independent
player percentile table cannot provide:

- probability of finishing first or top three at the player's position;
- probability of finishing above the league's starter/replacement cutoff;
- a p10-p90 range for value above replacement, with replacement recalculated
  separately inside every simulated season;
- a draft decision matrix for two to four players, showing how often the row
  player produces more season-specific value than the column player in the
  **same simulation replication**.

The comparison uses value above position-specific replacement rather than raw
points, so cross-position decisions are meaningful. Ties count as half a win.
The embedded matrix is limited to the top 80 draft-board players to bound HTML
size and report-generation cost.

## Important limits

- These are model probabilities, not calibrated betting odds. The current
  interval calibration caveat remains prominent.
- ADP and expert consensus would be useful for disagreement reports and
  benchmarking, but should not become model inputs; see `DATA_WANTED.md`.
- College production, routes run and richer injury detail remain meaningful
  data gaps. They require licensed or currently unavailable inputs and should
  not be replaced with invented values.

