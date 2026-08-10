# PRODUCT_BACKLOG

Prioritized per the product directives: correctness → identity → luck/schedule →
storytelling → creative viz → comedy → draft → experimental. Entries carry the
fields that matter for the decision; full metric definitions live in METRIC_CATALOG.

## Security and correctness
- **DONE (4e96255)** Credential remediation: .env untracked, example scrubbed,
  secret scan in `make check` + CI, runbook with human actions.
- **HUMAN** Rotate ESPN cookies; optional git history rewrite (docs/SECURITY_CREDENTIALS.md).
- **DONE (94649de)** Ingestion correctness: FFC UA 403, league name, real manager
  names, player position clobbering.

## Data integrity
- **D-1 — VERIFIED COVERED (e1a050e docs).** Politeness.call retries all exceptions incl. throttle-shaped 404s. ESPN edge intermittently 404s valid leagues after
  bursts. `Politeness`/`EspnApiSource` should retry `ESPNInvalidLeague` a bounded
  number of times before failing a sync. Small, do with next ingestion change.
- **D-2 — DONE (e1a050e).** PlayerADP↔Player join is `(season, lower(name))`;
  suffixes ("Jr."), D/ST naming, and spelling differences silently drop matches
  (2024: 148/160 picks matched). Add normalization (strip suffixes/punctuation)
  + a sync report of unmatched names. Never fuzzy-merge silently.
- **D-3 FFC 2025 ADP missing upstream** — re-run when FFC publishes.

## Identity continuity
- **I-1 Manager merge — MECHANISM DONE (838d064); execution awaits operator confirmation (2→8, 13→9).** Two humans have two ESPN accounts
  each (Braylan Covol: mgr ids w/ 43-25 + 9-4; Matt Weyandt: 24-30 + 3-11).
  Design: `Manager.merged_into` self-FK + `merge_managers` management command;
  frames resolve to canonical manager before compute; API hides merged rows.
  Data required: operator confirmation of which SWIDs are the same human.
  Risks: silent auto-merge by name is forbidden — operator command only.
- **I-2 Player identity**: keyed on stable `espn_player_id` (fine). gsis_id
  crosswalk unpopulated; needed only when nflverse stats land. D/ST are
  pseudo-players; exclude from cross-source joins.

## Core analytics
- **P-1 Player value system — DONE (9667668).**
  Question: "Who were the greatest fantasy players in league history, and how much
  value did each manager actually receive from them?"
  Data: LineupSlot (11,960 rows, complete 2020–2025, started+bench, per-week,
  per-team) + DraftPick + PlayerADP. Free agents/never-rostered: no data (documented).
  Method: PlayerSeasonValue (total/started/bench points, weeks rostered/started,
  points-over-replacement reusing drafts.py `_replacement_levels`, position rank);
  PlayerManagerSeasonValue (same, attributed weekly to the rostering team's
  manager(s) — a manager only gets weeks the player sat on their roster).
  API: `players/` (bounded list, filters season/position/sort) +
  `players/<espn_player_id>/` (career, per-season, per-manager, draft/ADP context).
  UI: Player Explorer (list + detail). Era note: raw points shown with season
  context; era-normalized views deferred (position percentile included as the
  first normalized measure).
  Acceptance: values reconcile with LineupSlot sums; manager attribution splits
  sum to season totals; tests for split-season (traded/waived mid-year) players.
- **P-2 Transaction capture going forward.** Historical: impossible (probed —
  SESSION_STATE). Implement current-season activity capture in `full_sync` when
  2026 starts; Transaction model already exists. Trades/waiver analytics become
  possible from 2026 on. Label eras honestly in UI.
- **P-3 — DONE (c771a23).** Lineup decision analytics (games lost on bench with legal-swap rule),
  data fully available 2020–2025.
- **P-4 Schedule multiverse / all-play deep views** — data available (Matchups).

## Creative visualizations (candidates; VISUAL_DESIGN_LAB has sketches)
- V-1 Ownership timeline strip on player page (who rostered the player, by week).
- V-2 Draft-cost vs production quadrant (data ready: DraftPickValue).
- V-3 Weekly scoring fingerprint (small-multiple sparklines per manager-season).
- V-4 League time machine (champions/records/streaks on a scrubbable timeline).
- V-5 Museum of Pain — DONE (d789726).

## Manager / season / rivalry experiences
- M-1 — DONE (3d0c4cc). Scouting report with percentile bars; archetype labels deliberately omitted (bars are the identity).
- S-1 Season story map (weekly race chart; playoff bracket needs bracket modeling).
- R-1 Rivalry pain index (formula must be documented before build).

## Comedy and awards
- C-1 Extend award engine with player-flavored awards once P-1 lands
  ("Most points wasted on a bench", "The one who got away" needs transactions → 2026+).

## Rejected ideas
- **Historical trade analytics (all forms)** — rejected 2026-07-15: ESPN does not
  retain completed-season transaction data (probed live; see SESSION_STATE).
  Revisit only for 2026+ captured data.
- **Radar-chart manager fingerprints** — axes not comparably scaled; use small
  multiples / percentile bands instead.
- **League Constellation network view** — deferred indefinitely: 14 managers,
  80 pairs — a matrix (already shipped as Rivalries heatmap) is strictly more
  readable at this scale.

## Draft analyzer roadmap (added 2026-08-02, post PJ-1..3)
The app's primary identity is now the draft analyzer. Shipped: DA-1 Draft DNA,
DS-1 suggester (ADP calibration + CIs), PJ-1..3 (Sleeper projections,
projection-error CIs, steals/busts). Candidates, roughly ordered:

- **DA-2 positional run detection**: find streaks of same-position picks in
  each draft's sequence; identify who STARTS runs vs who panics into their
  middle (pick timing within run + reach size). Data already in the patterns
  blob; pure analytics + one chart.
- **DS-2 live draft assistant mode**: suggester tracks picks as they happen
  (operator clicks players off the board); remaining-player availability
  re-normalizes on the fly. No new data — UI state + a "taken" set.
- **DS-3 roster-need weighting**: score suggestions vs the user's roster so
  far (starters unfilled > bench depth), using league roster_slots per season.
- **PJ-4 weekly projection ingestion**: hvpkod NFL.com archive (2021-2025,
  re-scorable categories) + LineupSlot.projected_points already in DB →
  start/sit report cards per manager ("points left on bench vs projections
  said so"). Distinct from optimal-lineup luck (which uses actuals).
- **PJ-5 FantasyPros Wayback consensus backfill**: second projection source
  (2019-2025) via archive.org snapshots (gzip + CDX wildcard gotchas are
  documented in R-3); enables projection-source disagreement analysis.
- **PJ-6 projection accuracy meta-analysis**: which positions/rounds do
  projections systematically miss in this league (already have residuals);
  "trust the projection?" indicator per suggester row (n + spread).
- **DA-3 draft-slot fairness**: does draft position predict final standing
  here? Slot vs finish across seasons + snake-position value curve.
- **DA-4 auction-year support**: auction_price exists on DraftPick; if any
  season used auctions, spend-pattern DNA (budget allocation by position).
- **V-4 time machine** (pre-existing): event extraction; draft-day recap mode
  pairs well with projection steals/busts.

## Draft analyzer — rejected/parked
- Live win-probability during drafts: needs real-time opponent modeling,
  out of scope for a self-hosted hobby app.
- Paid projection APIs: no affordable 2019-2025 archive exists (R-3).
- Yahoo anything: no projections exposed; OAuth burden for zero payoff.
