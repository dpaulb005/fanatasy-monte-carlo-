# Data wanted — for a session with open internet

This environment's proxy blocks most of the web. Everything below was either
confirmed blocked here or is unavailable without a key. If you have open
egress, these are the things that would actually move the model, in priority
order — with what each one unlocks and where it plugs in.

**Format rule for all of it:** save as CSV or Parquet under `data/external/`,
one file per source, with a `README` line recording the URL and the date
fetched. Every loader in `nflsim/data.py` caches by path; adding a new source
means adding a loader there, not changing the engine.

---

## Tier 1 — would change the projections

### 1. Season-long player prop lines (the single most valuable item)

Sportsbooks post season over/unders for passing yards, rushing yards,
receptions, receiving yards and touchdowns. **This is the sharpest player-level
market signal that exists**, and almost no public analysis uses it, because it
is tedious to collect.

Why it matters here: our only market check is 52 game totals, which validates
*team* scoring and says nothing about whether we have a specific player's volume
right. Season props are a direct, per-player, market-priced comparison to our
projected stat lines.

- Wanted: player, stat, line, over/under price, book, date collected.
- Sources: DraftKings / FanDuel / BetMGM season specials; odds aggregators
  (OddsJam, unabated) if you have access.
- Plugs into: a new `validate.market_props()` alongside the existing game-total
  check. **Reference only — never an input**, same rule as the game lines.

### 2. Expert consensus rankings and ADP

**There is now a one-command way to fetch the ESPN half of this.** From any
machine that can reach `fantasy.espn.com`:

```bash
python -m nflsim adp --source espn --save data/external/espn_adp.csv
```

That hits ESPN's public fantasy API (`kona_player_info`) and writes the board
the draft simulator uses. Commit the CSV and it works everywhere:

```bash
python -m nflsim draft --adp data/external/espn_adp.csv --interactive
```

This environment cannot do it — the proxy answers 403 to CONNECT for
`lm-api-reads.fantasy.espn.com`, and for FantasyPros, Sleeper and Yahoo too.
Only GitHub is reachable, which is why the working fallback is FantasyPros ECR
via the DynastyProcess mirror on `raw.githubusercontent.com`. That is a
*ranking*, not a draft position, and the two differ systematically: rankers are
less swayed by name recognition than drafters are. Real ADP is the thing worth
fetching.

Re-fetch weekly through August — ADP moves fastest in the two weeks before the
season, which is exactly when the practice drafts matter.

Beyond ESPN, here is what else is useful and why.

- **ADP** (Underdog, Sleeper, ESPN, Yahoo, NFFC), as player + positional ADP +
  overall ADP + date. Underdog and NFFC are best-quality because real money.
- **FantasyPros ECR** — expert consensus rank, and the individual expert ranks
  if exportable.

Two uses, and only two:
1. **Disagreement report.** Where we differ most from consensus is where the
   model is either earning its keep or badly wrong. That list is the single most
   useful artifact for a draft, and it is also the best bug-finder we have — the
   Barkley error was found exactly this way, by a human noticing a number that
   looked wrong.
2. **Benchmark.** The strongest finding in the public literature (Fantasy
   Football Analytics, a decade of it) is that the *average of many sources*
   beats every individual source. If we cannot beat consensus on a matched
   cohort, that is worth knowing before trusting the model over it.

Do **not** blend ADP into the projections. The moment we do, we inherit the
market's opinion and can no longer disagree with it — which is the entire point
of building this. `ffsimulator`, the most-used public tool in this category,
keys off ADP rank and therefore structurally cannot disagree with the market.

### 3. College production for rookies

Confirmed unavailable here: `cfbfastR-data` keeps 2002–2020 in the repo tree
(reachable) but everything 2021+ in GitHub release assets (proxy returns 404),
and `api.collegefootballdata.com` refuses connection entirely.

- Wanted: for every drafted skill player 2019–2026 — final two college seasons
  of receiving/rushing/passing volume and efficiency, **team totals for the same
  seasons** (so shares can be computed, not just raw counts), games played, age
  at draft, and conference.
- The share matters more than the raw production. Dominator rating (share of
  team receiving yards + TDs) and breakout age are the two college metrics with
  the best-documented predictive record for receivers.
- Sources: `cfbfastR-data` release assets; collegefootballdata.com API (free key
  at collegefootballdata.com/key); sports-reference college (blocked here).
- Plugs into: `players.fit_rookie_curves()`, which currently uses draft capital
  plus combine testing alone. Makai Lemon is projected as Philadelphia's WR2 on
  draft slot and a depth-chart line with **no production evidence whatsoever**;
  he is the least-supported number in the whole output.

### 4. Routes run

- Wanted: routes run per player per game, 2019–2025.
- Why: target share is a ratio whose denominator is team pass attempts, which
  conflates "he is the first read" with "he was on the field". Targets per route
  run separates the two and is markedly more stable year to year.
- Source: PFF (paid), FTN, or Fantasy Points Data (paid). Not in nflverse.
- Plugs into: `players.fit_usage()` as a second usage channel.

---

## Tier 2 — would improve validation, not the projections

### 5. More seasons of backtest, for conformal calibration

No download needed — just compute time. The interval calibration currently fits
on one season and overshoots (see `docs/HANDOFF.md`), because the degree of
miscalibration itself varies year to year. Pooling 2021–2024 as the calibration
set should stabilise it.

```bash
for y in 2021 2022 2023 2024; do
  python -m nflsim backtest --season $y --sims 3000 --out artifacts/backtest_$y.csv
done
```

Caveat: depth charts before 2025 use the older weekly-formation schema, which is
supported but lower quality; 2021–22 coverage should be spot-checked before the
results are trusted.

### 6. Historical closing lines and totals, 2016–2025

- `nfldata`'s `games.csv` already carries `spread_line` and `total_line` back
  many seasons and is reachable here — so this is mostly a matter of using it.
- Why: lets us score team-level simulated scoring against the closing line
  historically rather than against 52 forward-looking 2026 games.

### 7. Injury detail

- Wanted: body part, mechanism, and games missed per injury, rather than the
  binary participation signal we fit from now.
- Source: Sports Injury Predictor database (paid, powers Draft Sharks), or
  scraped injury reports with designations.
- Why: our hazard model is positional and age-adjusted with a personal
  durability multiplier. It cannot distinguish a hamstring from a torn ACL, and
  those have very different recurrence and duration profiles.

---

## Tier 3 — nice to have

- **Depth chart history pre-2025 in the new schema** — the old weekly format is
  supported but coarser, which weakens the older backtests.
- **Weather forecasts** for outdoor stadiums (we model wind only, from the
  schedule's recorded value; forecast data would help in-season).
- **Coordinator history** — our coaching profiles are head-coach-attributed
  because public coordinator play-calling assignment is not reliably available.
  Where the coordinator calls plays and the head coach does not, the profile
  blends both. A clean coordinator table would sharpen this measurably.
- **Snap-share splits by formation/personnel** — would let usage vary by
  package rather than being a single season-long share.

---

## What NOT to fetch

- **Other people's projections, as model input.** Scraping ESPN/CBS/PFF
  projections and blending them makes this an aggregator. `ffanalytics` already
  does that well and there is no reason to build a worse copy.
- **pro-football-reference.com directly.** Blocked here (403 at the proxy), and
  their terms prohibit scraping. The PFR advanced stats we use come through the
  nflverse mirror, which is the sanctioned route: `data.pfr_advstats()`.
