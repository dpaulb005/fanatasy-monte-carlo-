# OVERNIGHT_REPORT — session 1 (2026-07-15, final)

## Executive summary

- **Most valuable completed improvements**: (1) live ESPN data end-to-end —
  six real seasons synced, verified, and serving every page; (2) credential
  exposure remediated with a permanent CI secret-scan gate; (3) seven product
  slices shipped, each reviewed, tested, and live-verified.
- **Current product condition**: 70 backend tests + ruff + mypy + vue-tsc +
  eslint + vitest all green; 12-route live smoke pass clean; 20 commits on
  `claude/fantasy-league-analysis-plan-wm8zke`; STATUS: CLEAN_CHECKPOINT.
- **Most interesting analytical discovery**: Travis Kelce is the career
  points-over-replacement king (+678) despite Josh Allen out-scoring him by
  ~570 raw points — and 25 of David Brown's 45 career losses were winnable
  with a legal lineup swap (league worst).
- **Most successful visual improvements**: player ownership-timeline strips;
  the Museum of Pain; per-season weekly fingerprints (small multiples).
- **Largest unresolved risk**: leaked ESPN cookies remain valid until rotated
  (human action, docs/SECURITY_CREDENTIALS.md).
- **Recommended next task**: V-2 draft quadrant framing, then S-1 season
  story map. Two staged human decisions unblock more: manager merges
  (`merge_managers 2 8`, `merge_managers 13 9`) and cookie rotation.

## Completed features (all committed, gated, live-verified)

1. `94649de` **Ingestion fixes from first live sync** — FFC 403 UA, league
   name, real manager names, player-field clobbering (79% positionless slots).
2. `4e96255` **Security remediation** — .env untracked, example scrubbed,
   secret scan in `make check` + CI, incident runbook.
3. `9667668` **P-1 Player value + Explorer** — weekly manager attribution over
   11,960 lineup rows; PlayerSeasonValue/PlayerManagerSeasonValue; players
   API; Explorer list + detail with ownership timelines. 3-finder review, 6
   findings fixed. Also fixed pre-existing D/ST→DST mismatches.
4. `838d064` **I-1 Manager merge mechanism** — reversible operator command,
   canonical resolution in frames, no-chain/no-overlap validation. Execution
   staged, awaiting operator confirmation.
5. `e1a050e` **D-2/D-1 ADP join normalization** — suffix/punct/D-ST crosswalk;
   2024 match rate 148→159/160; retry policy verified already covered.
6. `c771a23` **P-3 Games lost on the bench** — legal-lineup rule, season stat,
   award, manager-page column. David Brown leads all-time (25/45).
7. `d789726` **V-5 Museum of Pain** — six formula-backed exhibits (a 0.02-pt
   loss; a 1.9-pt week with 121.9 benched).
8. `3d0c4cc` **M-1 Scouting report** — five percentile traits, min-sample rule.
9. `c7cef70` **Consolidation** — simplify sweep (3 applied, 1 skipped with
   rationale), 12-route live smoke pass.
10. `3b1280d` **V-3 Weekly fingerprints** — small-multiple season grids.

## Research
- Historical ESPN transactions: unrecoverable (probed live) → historical trade
  analytics rejected; current-season capture (P-2) possible once 2026 starts.
- ESPN edge throttling: transient 404s after bursts; Politeness retry covers it.
- FFC ADP: 2025 unpublished upstream (recheck later); defense naming crosswalk.
- Era normalization: position-rank/percentile chosen as first honest
  cross-era comparator (league grew 6→12 teams).

## Metric integrity
New cataloged metrics with tests: player season/manager value (+ reconciliation
invariants), points-over-replacement reuse, bench_losses (legal-swap rule),
scouting traits, fingerprints. See METRIC_CATALOG.md.

## Test summary
- Baseline → final: backend 46 → 70 passed; frontend 3 vitest + tsc + eslint
  (plus a pre-existing vitest/Playwright collection clash fixed).
- Not run: Playwright e2e (fixture-shaped, no browser in env — path documented).

## Resume instructions

NEXT TASK: V-2 draft-cost vs production quadrant framing
NEXT ACTION: read SESSION_STATE.md, then extend the Drafts scatter with quadrant framing + manager filter
NEXT COMMAND: docker compose exec -T -e DATABASE_URL= backend pytest -q
STATUS: CLEAN_CHECKPOINT

Human actions pending: rotate ESPN cookies; confirm staged manager merges
(2→8 Covol, 13→9 Weyandt) then `compute_analytics`; optional history rewrite.
