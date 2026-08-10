# REVIEW_LOG

## 2026-07-15 session 1

- **Ingestion fixes (94649de)** — reviewed via: full test suite (46 pass), ruff,
  mypy, and live verification (force re-sync 2020–2025; positions 100% populated;
  ADP deltas resolve; league/manager names correct on all pages via screenshots).
- **Security remediation (4e96255)** — verified `scripts/check_secrets.sh` fails
  on a tracked .env and on cookie-shaped tracked content, passes on clean tree;
  CI job added. History rewrite deliberately NOT automated (shared-history risk;
  documented for human decision).
- **P-1 player value slice (committed 9667668)** — three independent finder
  agents (line-by-line, cross-file/removed-behavior, cleanup/efficiency/frontend)
  reviewed the full diff. Six findings, all fixed and re-verified:
  1. `int()` on raw query params → 500 on `?season=abc` (fixed: `_int_param`
     → DRF ValidationError 400; regression test).
  2. Degenerate 200 + "QBnull" tile for players with no data in the active
     league (fixed: 404 in `player_detail`; nullable TS type + "—" render;
     regression test).
  3. Per-season position decided by a career-wide latest-label map — wrong
     pools for players ESPN relabels across seasons; also affected draft PoR
     (fixed: `player_position_by_year` in frames, used by players + drafts).
  4. Unknown/blank positions got replacement baseline 0.0 → PoR = raw points
     (fixed: PoR 0.0 when no replacement pool exists).
  5. `managers.first()` bypasses `prefetch_related` (unordered → `order_by('pk')`
     clone) → one query per lineup row on player detail (fixed:
     `next(iter(.all()), None)` hits the prefetch cache).
  6. No stale-response guard in PlayersView filter fetches (fixed: monotonic
     request sequence).
  Cleared during review: career-agg annotate/values alias safety, engine
  delete scoping across leagues, D/ST normalization consistency with
  lineups/trends consumers, no `awards.py` position dependency.
  Known accepted tradeoff (documented in METRIC_CATALOG + model docstring):
  co-managed teams credit each manager with the same team-weeks, so manager
  splits exceed season totals only for co-managed rosters (none in this
  league's data today; synthetic fixtures are single-managed).

## 2026-07-15 consolidation pass (c7cef70)
- Simplification reviewer over the six session slices: 4 findings, 3 applied
  (dead season join in manager_scouting; _opt_manager_ref reuse; derived
  seasons computed in PlayersView), 1 skipped with rationale (museum/engine
  week_efficiency double-compute — offline batch, cross-module plumbing not
  worth it). Everything else reviewed clean.
- Live smoke: 12/12 routes OK (HTTP, h1, no error states, 0 console errors).
