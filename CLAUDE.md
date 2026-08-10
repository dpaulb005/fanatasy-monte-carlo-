# Fantasy League Analysis App — Claude Code Context

Private, self-hosted analytics + comedy dashboard for one long-running ESPN fantasy
football league (league id in `.env`, seasons 2020–present). Pulls multi-season league
history from ESPN, enriches with public NFL data, and precomputes trends, awards,
rivalries, and manager career stats.

## Stack

- **Backend**: Django 5.1 + DRF, Python 3.11, in `backend/`. PostgreSQL 16 in Docker;
  SQLite fallback when `DATABASE_URL` is empty (dev/tests).
- **Frontend**: Vue 3 + TypeScript + Vite + Pinia + ECharts (vue-echarts), in `frontend/`.
- **No Celery/Redis/background workers** (ADR-003): sync is synchronous management
  commands, run manually or via cron.
- **Persist-first design** (docs/ARCHITECTURE.md): ESPN is hit only at sync time.
  Analytics are precomputed into dedicated tables; the REST API is read-only.

## Running it

```bash
make dev            # docker compose up --build → db:5432, backend:8000, frontend:5173
make down
# Non-Docker: make venv → make demo-data → make runserver + (cd frontend && npm run dev)
```

App: http://localhost:5173 · API: http://localhost:8000/api/v1 (health at /api/v1/health/)

Compose hardcodes `DATABASE_URL=postgres://fantasy:fantasy@db:5432/fantasy` in the
backend service (overrides `.env`), so **run sync commands inside the backend container**
to populate the DB the site actually reads:

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py sync_espn --years 2020-2025
docker compose exec backend python manage.py sync_nfl_context --source ffc --years 2020-2025
docker compose exec backend python manage.py compute_analytics
```

`full_sync` chains all three for the current season (cron-style). Synthetic demo data
(no credentials): `make demo-data` or `--source synthetic` (league id 999999).

## Data pipeline (order matters)

1. `sync_espn` → populates `League`, `Season`, `Manager`, `TeamSeason`, `Player`,
   `DraftPick`, `Matchup`, `LineupSlot`; writes a `SyncLog` row per run. Completed
   seasons are skipped unless `--force`.
2. `sync_nfl_context` → `PlayerADP` (FantasyFootballCalculator), `PlayerWeekStat` (nflverse).
3. `compute_analytics` → truncate-and-rebuild of `ManagerSeasonStats`,
   `ManagerCareerStats`, `HeadToHeadRecord`, `DraftPickValue`, `SeasonTrend`, `Award`.
   **The API selectors read these computed tables** — pages look empty until this runs.

ESPN era boundaries (`backend/league/ingestion/ports.py`): full fidelity (box scores,
lineups) only 2019+; ≤2018 is standings/drafts/final scores only; ≤2017 uses the
history endpoint. `capabilities_for_year()` gates what gets fetched.

## Key paths

| Path | What |
|---|---|
| `backend/league/ingestion/espn_source.py` | `EspnApiSource` — only module importing `espn-api` (lazy) |
| `backend/league/ingestion/espn_normalize.py` | espn-api objects → `SeasonBundle` (brittle mapping layer, ADR-005) |
| `backend/league/ingestion/runner.py` / `persist.py` | source-agnostic sync orchestration; idempotent upserts |
| `backend/league/ingestion/politeness.py` | serialized calls, jittered delay, backoff |
| `backend/league/models/` | `core.py`, `events.py`, `computed.py`, `context.py`, `provenance.py` |
| `backend/league/management/commands/` | `sync_espn`, `sync_nfl_context`, `compute_analytics`, `full_sync`, `load_fixtures` |
| `backend/league/api/` | `urls.py`, `views.py`, `selectors.py` — read-only, under `/api/v1` |
| `backend/league/analytics/players.py` | Player value: season + manager-attributed (weekly attribution) |
| `docs/autonomous/` | Session state, backlog, research, metric catalog — read SESSION_STATE.md first |
| `frontend/src/views/` | Home, Season, Manager(+Card), Trends, Rivalries(+Pair), Drafts, HallOfFame, Players(+Detail) |
| `frontend/src/api/client.ts` | single `apiGet` client, base `VITE_API_BASE` |
| `docs/CONNECT_YOUR_LEAGUE.md` | operator runbook for live ESPN sync |
| `docs/DECISIONS.md` | ADR log — read before changing architecture |

## Environment (.env — NEVER commit)

`ESPN_LEAGUE_ID`, `ESPN_S2`, `ESPN_SWID` (browser cookies; authenticate as the owner),
`ESPN_START_YEAR` (documentation-only — backfill range comes from `sync_espn --years`),
`DATABASE_URL`, `DJANGO_*`, `CORS_ALLOWED_ORIGINS`, `VITE_API_BASE`.

⚠️ Live cookies were committed to git history on this branch (remediated 2026-07-15:
`.env` untracked, example scrubbed, secret scan in `make check` + CI — see
docs/SECURITY_CREDENTIALS.md). Human actions still required: rotate the ESPN
cookies (log out of all ESPN sessions); optionally rewrite history before any push.

## Quality gates

```bash
make check          # secret-scan + ruff + mypy + pytest (54 backend tests)
make frontend-test  # vitest
make frontend-e2e   # Playwright (needs stack running with data)
```

Tests never hit the network — ESPN normalizer tests use fakes; pipeline tests use the
synthetic source. There is no `--dry-run`; the credential-free path is `--source synthetic`.
