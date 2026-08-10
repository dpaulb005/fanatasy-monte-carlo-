# METRICS CATALOG

Every statistic the app computes, with: question answered, formula, required source data, edge
cases, interpretation, limitations, complexity, caching, tests, and chart. Funny stats are
derived from real data and cite the underlying records. This catalog is the single source of
truth for analytics; `analytics/*.py` implements it and `tests/` verifies it.

Conventions: *n* = teams in a season; computed tables are rebuilt by `compute_analytics` (cache =
"precomputed, invalidated on sync"). Complexity is per full compute run over all seasons unless
noted; all are vectorized groupbys, sub-second at league scale.

---

## Performance & records

### Career record (W / L / T, win%)
- **Question:** How good is a manager all-time?
- **Formula:** sum wins/losses/ties across all `Matchup` rows for the manager's `TeamSeason`s;
  `win% = (W + 0.5T) / games`.
- **Source:** `Matchup`, `TeamSeason`, `Manager`.
- **Edges:** co-owned teams (attribute to all owners); ties; incomplete current season (flag).
- **Limits:** scoring settings differ across eras — win% is comparable, raw points are not.
- **Chart:** record table; win% sparkline by season.

### Points for / against, average weekly score, variance, consistency
- **Question:** How much does a manager score, and how consistently?
- **Formula:** PF/PA totals; `avg = mean(weekly team score)`; `variance = stddev(weekly score)`;
  `consistency = 1 − (stddev / mean)` (coefficient-of-variation based).
- **Source:** `Matchup` (or `LineupSlot` sums where available).
- **Edges:** pre-2019 seasons lack per-player detail but have team totals — OK for these.
- **Chart:** box/violin per manager per season (ceiling/floor); line of weekly PF.

### Champions, playoff appearances, playoff conversion, finishes
- **Formula:** from `TeamSeason.final_standing` + `Matchup.matchup_type`
  (CHAMPIONSHIP/PLAYOFF); `playoff conversion = playoff apps / seasons`.
- **Chart:** champions timeline; dot plot of finishes.

### Streaks & droughts (win/lose, playoff, title)
- **Formula:** run-length scan over each manager's chronologically ordered games/seasons.
- **Complexity:** O(games). **Chart:** record cards.

---

## Luck

### All-play record & expected wins
- **Question:** How many games *should* a manager have won given their scores?
- **Formula:** for each team-week, `all_play_win_frac = (# league teams outscored that week)/(n−1)`;
  `expected_wins = Σ_weeks all_play_win_frac`. One `groupby(season, week).rank()` over all history.
- **Interpretation:** expected wins strips out schedule luck (who you happened to play).
- **Limits:** treats every week independently; ignores h2h scheduling intent (that's the point).
- **Complexity:** O(seasons × weeks × teams). **Chart:** diverging bar actual − expected.

### Luck index (schedule luck)
- **Formula:** `luck_delta = actual_wins − expected_wins`. Positive = lucky schedule.
- **Chart:** diverging bar; scatter PF (x) vs actual wins (y) with expected-wins trend line
  (unlucky teams sit below the line).

### Points-against luck
- **Formula:** percentile of a team's total/again-per-week PA vs the league PA distribution;
  perennially high PA percentile = unlucky.
- **Chart:** ranked bar.

### Close-game & opponent-underperformance luck (optional)
- **Formula:** record in games decided by < 1 stddev of weekly margin; count of wins where
  opponent scored below their season mean.
- **Limits:** small samples — present with counts, not just rates.

---

## Lineup / coaching efficiency

### Optimal lineup & points left on bench
- **Question:** How many points did a manager leave on the bench?
- **Formula:** per team-week, from `LineupSlot` rows compute the best legal lineup: sort players
  by actual points and greedily fill dedicated position slots, then FLEX from remaining eligibles.
  `bench_points_lost = optimal − actual`; `lineup_efficiency = actual / optimal`.
- **Source:** `LineupSlot` (2019+ only).
- **Edges:** greedy is exact for standard ESPN single-FLEX slot structures; **flag and validate**
  seasons with unusual slots (OP/superflex/IDP) — fall back to exact search if the greedy
  assumption fails for that season's `roster_slots`.
- **Limits:** unavailable pre-2019 (`lineups_available=False`).
- **Complexity:** O(team-weeks × roster size). **Chart:** efficiency line; "Coach of the Year".

---

## Head-to-head

### H2H record (regular vs playoff split), streaks, biggest blowout
- **Formula:** one pass over `Matchup` accumulating into an ordered manager-pair dict
  (a_id < b_id); expand co-owned teams to all owner pairs; split by `matchup_type`.
- **Complexity:** O(matchups). **Chart:** symmetric win% heatmap; per-rivalry game-log strip.

---

## Drafting (retrospective — Phase 6)

### Points over replacement (draft value)
- **Question:** Did a pick return starter-level value?
- **Formula:** `points_over_replacement = player_season_points − baseline(position)`, where
  baseline = points of the `(starters × n)`-th ranked player at that position that season
  (replacement level derived from the league's own data — no external source needed).
- **Source:** `DraftPick`, `PlayerWeekStat` (or ESPN player points), `Season.roster_slots`.
- **Chart:** green→red graded draft board.

### ADP delta (steal / reach)
- **Formula:** `adp_delta = overall_pick − adp` (from `PlayerADP`, matched season/format). Positive
  = drafted later than consensus (potential steal).
- **Edges:** ADP missing for some players/years → null, excluded from steal/reach ranking.
- **Chart:** scatter ADP (x) vs actual points (y), quadrant-annotated for steals/reaches.

### Round expectation delta
- **Formula:** player points vs median points of all picks in that round across league history.
- **Chart:** value-by-round curve (median points per draft slot / round).

### Positional runs
- **Formula:** scan draft in overall-pick order; flag ≥3 same-position picks within a 5-pick
  window. **Complexity:** O(picks). **Chart:** draft-board annotation.

**Separation discipline (Phase 6):** the UI must clearly label each number as *league history*,
*public consensus (ADP)*, *league tendency*, or *projection/uncertainty* — never blur them.

---

## League trends (Phase 5)

- **Scoring evolution:** per-season mean/median/stddev of weekly team scores → inflation line +
  variance band. **Chart:** line + confidence band.
- **Parity:** stddev of season win% across teams per season (lower = more parity). **Chart:** line.
- **Positional scarcity / share:** share of *started* points by position per season. **Chart:**
  stacked area.
- **Weekly score distribution:** per-season boxplot of team-week scores. **Chart:** boxplot.

All emitted as `SeasonTrend` chart-shaped JSON blobs.

---

## Fun / funny stats & awards (Phase 7)

Each is a small function over the frames emitting `Award` rows (per-season + `ALL_TIME`), with a
`context` JSON carrying the matchup/pick/week behind it (so narratives cite real data). Adding an
award = one function + one frontend card; **no schema change**.

| Award | Definition (real-data basis) |
|---|---|
| **Heartbreak of the Year** | Highest score in a losing effort (max losing team score) |
| **Daylight Robbery** | Lowest score in a winning effort (min winning team score) |
| **Benchwarmer of the Year** | Max `bench_points_lost` in a week/season |
| **The Sacko** | Last-place / toilet-bowl finisher (+ career sacko count) |
| **Cursed Pick** | Worst `round_expectation_delta` among rounds 1–3 |
| **Draft Whisperer** | Best total points-over-replacement drafted in a season |
| **Waiver Wizard** | Most points from undrafted starters (add via `Transaction`/undrafted `LineupSlot`) |
| **Glass Cannon** | Highest weekly score stddev |
| **Paper Champion** | Best all-play / expected-wins record that missed the title |
| **Luckiest Playoff Berth** | Made playoffs with the largest positive `luck_delta` |
| **Most Loyal (Manager–Player)** | Player appearing on the same manager's roster across the most seasons |
| **Longest Streaks** | Career & season win/lose streaks |

**Interpretation guard:** behavioral labels/archetypes are presented as playful, explainable
analysis — never psychological fact — and always link to the numbers that produced them. Avoid
amusing-but-misleading metrics (e.g. "performs best after criticism" requires a defined,
data-backed trigger or it is not shipped).

---

## Testing requirements

- **Formula unit tests** with hand-computed expectations for: all-play/expected wins, luck delta,
  optimal-lineup solver (incl. FLEX edge cases), points-over-replacement, H2H accumulation,
  streak scanning.
- **Identity-resolution tests:** renamed teams, changed display names, co-owned teams collapse to
  the right `Manager`.
- **Scoring-setting variation tests:** metrics behave under different per-season settings.
- **Malformed-data tests:** missing box scores (pre-2019), null ADP, unmatched players.
