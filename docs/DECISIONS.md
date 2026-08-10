# DECISIONS (ADR log)

Meaningful architectural decisions and their rationale. Newest first.

---

## ADR-012 — Draft suggester: market-calibrated, not player-projecting (amends ADR-007)
**Decision:** Add a forward-looking draft suggester (`/api/v1/drafts/suggest/`
+ the Suggester page), explicitly requested by the operator, as a bounded
amendment to ADR-007's "retrospective only" stance. The suggester ranks the
latest synced ADP re-centered by this league's historical pick-vs-ADP bias per
position, with 80% confidence intervals whose sigma comes from the league's own
residual spread (normal model, floored at ±3 picks), snake-aware availability
probabilities ("will he make it back to me"), and per-(position, round) value
bands that are quantiles of realized points-over-replacement in this league.
**Why:** Everything in it derives from already-synced data (PlayerADP +
DraftPickValue history) — no projections dependency, no model to maintain, and
every number has a plain-English provenance. The honesty line ADR-007 drew
still holds: the suggester never claims player skill; it quantifies the market,
this league's deviation from it, and historical positional payoff. Priors are
precomputed at sync time (`draft_priors` blob); only the cheap per-request
normal-CDF math happens at request time, keeping ADR-004's read-cheap property.

---

## ADR-011 — One narrow write endpoint for operator setup (manager identity)
**Decision:** The REST API stays read-only for all analytics, with a single
exception: `POST /api/v1/setup/managers/` writes the three operator-only
Manager identity fields (`real_name`, `email`, `merged_into`). Merge writes
reuse the exact validation rules as the `merge_managers` command (shared in
`league/identity.py`), and any name/merge change synchronously rebuilds
analytics (labels are baked into computed blobs at compute time; ADR-010 makes
the rebuild sub-second).
**Why:** The Setup page's whole job is correcting the app's predictions
(ESPN never provides emails and often provides handles instead of names), and
"edit in the Django admin" is not an acceptable operator UX for that. The
trust model is unchanged — this is a private, self-hosted, unauthenticated
app; the endpoint writes nothing that sync or analytics write, so ingestion
stays the single source of truth for league data.

---

## ADR-010 — Pure-Python analytics (no pandas on the compute path)
**Decision:** Compute all analytics with plain Python (load-once dataclass frames
+ vectorized-by-hand aggregation) instead of pandas. This is a deliberate
deviation from the pandas approach sketched in the original ARCHITECTURE/METRICS
drafts.
**Why:** At league scale (a few thousand team-weeks) pure-Python aggregation runs
in well under a second, keeps formula unit tests crystal-clear against
hand-computed values, and removes a heavy dependency the user explicitly wanted
to avoid ("algorithmically efficient and not bloated", "small dependency
footprint"). The engine is confined to `league/analytics/`; if a future metric
genuinely needs pandas/numpy, it can be added there without touching the request
path.
**Note:** `nflreadpy` (Phase 6 public-data ingestion) still returns Polars/pandas
frames — that dependency lives only in the ingestion path for that data source,
not in the analytics compute path.

---

## ADR-009 — Manager identity keyed on ESPN SWID GUID
**Decision:** `Manager` is a first-class cross-season entity keyed on the stable ESPN SWID GUID,
with `TeamSeason` as the per-year instantiation (co-owners via M2M) and an admin-editable alias
for merges.
**Why:** Managers rename teams and change display names across seasons; SWID GUIDs are stable.
This is the differentiator hobby projects get wrong (validated by Fantasy Record Book's
cross-platform identity feature). All career/rivalry analytics depend on it.

## ADR-008 — ESPN-first "Wrapped"-style shareable cards as the flagship differentiator
**Decision:** Prioritize a comedy/superlatives layer with shareable stat cards for Phase 7.
**Why:** Research shows analytics tools are dry and the viral "Wrapped" recap tools are
Sleeper-first and shallow. Owning *both* deep analytics and a shareable comedy layer for ESPN is
the standout market gap.

## ADR-007 — Retrospective (not predictive) draft intelligence
**Decision:** Draft analysis grades what actually happened (ADP/slot vs realized points, value
over replacement). No prediction engine. UI strictly separates history / public consensus /
league tendency / projection / uncertainty.
**Why:** Pre-draft tools already saturate projections; the retrospective angle is under-served and
avoids overclaiming. Aligns with "deterministic and explainable" operating rule.

## ADR-006 — `nflreadpy`, not `nfl_data_py`, for public NFL data
**Decision:** Use `nflreadpy` (Polars, MIT code, CC-BY 4.0 data) and its `load_ff_playerids`
crosswalk; canonical player key = `gsis_id`.
**Why:** `nfl_data_py` is officially deprecated ("switch immediately") with no further
maintenance. `nflreadpy` is the maintained successor; the crosswalk solves ESPN↔gsis_id
reconciliation. ADP via FantasyFootballCalculator (free, 2014+).

## ADR-005 — ESPN access via `espn-api` behind an adapter port, with a fixture source
**Decision:** Wrap `espn-api` (MIT, v0.46.0) in an `EspnApiSource` behind a `LeagueDataSource`
Protocol; provide a `FixtureSource` (saved JSON + synthetic league) so all dev/tests run without
credentials. Add politeness middleware (jitter, backoff, `Retry-After`) since `espn-api` has
none. Persist raw payloads before parsing.
**Why:** The unofficial ESPN API is undocumented and changes without notice; the adapter contains
the blast radius to one file. Fixtures keep CI credential-free and make ingestion testable.
Two ingestion tiers: summary (all seasons) + detailed weekly (2019+), since box scores/activity
are unavailable before 2019.

## ADR-004 — Precompute analytics at sync time into computed tables
**Decision:** Analytics run in `compute_analytics` (load DB → pandas frames once → vectorized
groupbys → truncate-and-rebuild computed tables). Request path is indexed lookups; pandas is
confined to `analytics/`.
**Why:** Data changes only at sync time. Precomputation makes reads fast without caching infra and
keeps the request path lean (no pandas import). Sub-second at league scale.

## ADR-003 — No Redis / Celery / Kafka / GraphQL / ML (yet)
**Decision:** Defer all of these until a demonstrated need. Sync is a management command
(cron/manual); caching is Django local-memory keyed on a sync-bumped version.
**Why:** Backfill is minutes, weekly sync is seconds; a task queue and message broker are pure
bloat at this scale. Operating rules explicitly forbid fashionable-but-unjustified infra.
**Revisit if:** in-season syncs must be user-triggered from the UI with progress (→ Celery), or
multi-league concurrent syncs appear.

## ADR-002 — Apache ECharts for visualization
**Decision:** ECharts via `vue-echarts`, per-chart module imports; chart data shaped server-side.
**Why:** Native heatmaps (H2H matrix, draft grids), boxplots (weekly variance), and dataZoom for
15-year time axes — Chart.js needs plugins for half of these. Tree-shakeable; first-class Vue 3
binding. (Plotly considered; heavier bundle, less idiomatic in Vue.)

## ADR-001 — Django modular monolith + PostgreSQL, monorepo with Vue 3 frontend
**Decision:** Single Django app (`league/`) with internal `models`/`ingestion`/`analytics`/`api`
packages; PostgreSQL (SQLite for fast tests); Vue 3 + TS + Vite frontend; Docker Compose for local
dev. Business logic in service layers, not views/serializers.
**Why:** Matches the user-specified stack and the scale (one league, hundreds of thousands of rows
at most). A monolith avoids microservice overhead; the internal package split gives structure
without app-boundary ceremony. Persist-then-serve validated by raphattack/espn-ffb.
