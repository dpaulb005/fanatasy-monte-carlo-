# fantasy_analysis_app

A private, self-hosted analytics + comedy dashboard for one long-running **ESPN fantasy
football** league. It pulls the league's full multi-season history, enriches it with public NFL
data, and generates deep trends and funny superlatives — tracking each manager across many years.

> Status: **functional (all planned phases built).** Runs locally on a built-in synthetic league
> with no ESPN credentials; live ESPN sync is a documented operator step. See
> [`OVERNIGHT_PROGRESS.md`](./OVERNIGHT_PROGRESS.md) for the full report.

## Quick start (synthetic demo, no credentials)

```
# backend
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
make demo-data                                    # migrate + fixtures + ADP + analytics
cd backend && .venv/bin/python manage.py runserver

# frontend (separate shell)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173. To connect your **own** ESPN league, follow
[docs/CONNECT_YOUR_LEAGUE.md](./docs/CONNECT_YOUR_LEAGUE.md) — run the sync on your own
machine (your ESPN cookies stay local; managed/CI environments block ESPN's API).

## What it does

- Hooks onto ESPN Fantasy (via the `espn-api` client, using your own league credentials) to
  archive rosters, drafts, matchups, scoring, and transactions across many seasons.
- Blends in public NFL datasets (nflverse via `nflreadpy`, FantasyFootballCalculator ADP) for
  league context and retrospective draft value.
- Tracks each **manager** across seasons (stable through team renames) — career records, luck,
  draft skill, rivalries.
- Generates smart charts (Apache ECharts) and funny, data-backed awards.

## nflsim integration

The draft room can combine league-specific behavior with a full play-by-play Monte Carlo
season model. The simulator stays outside the web process: it writes a versioned JSON snapshot,
and Django validates and persists that immutable analysis artifact. API reads remain fast and do
not load NumPy, rerun games, or depend on either repository being at a particular filesystem path.

```bash
# Produce the artifact from the simulator repository. Match --teams and scoring to the league.
cd "/Users/davidbrown/dev/monte-fantasy /repo"
python3 -m nflsim app-export --teams 12 --scoring ppr \
  --out artifacts/application-snapshot.json

# Import or atomically replace that season/format snapshot in the app.
cd /Users/davidbrown/dev/fantasy_analysis_app/backend
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_nflsim \
  "/Users/davidbrown/dev/monte-fantasy /repo/artifacts/application-snapshot.json"
```

Once imported, the Draft Suggester adds simulated point ranges, value over a replacement level
recomputed in every simulated season, position-title equity, and joint upper-tail lift against
the user's marked roster. The UI labels these as model evidence; market availability and league
history remain separate evidence streams.

## Stack

Django + Django REST Framework + PostgreSQL · Vue 3 + TypeScript + Vite + ECharts · Docker
Compose · pytest / Vitest / Playwright.

## Documentation

| Doc | Contents |
|---|---|
| [docs/PRODUCT_PLAN.md](./docs/PRODUCT_PLAN.md) | Vision, users, MVP, phases, non-goals |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | System design, DB model, pipelines (Mermaid) |
| [docs/DATA_SOURCES.md](./docs/DATA_SOURCES.md) | ESPN + public data reference, auth, licenses |
| [docs/METRICS_CATALOG.md](./docs/METRICS_CATALOG.md) | Every metric: formula, edges, tests |
| [docs/RESEARCH.md](./docs/RESEARCH.md) | Competitive & technical research log |
| [docs/DECISIONS.md](./docs/DECISIONS.md) | Architecture decision records |

## Privacy

Self-hosted, single league. ESPN credentials live in environment variables only — never
committed. Other managers' names and IDs are treated as personal data. Data is not exposed
publicly by default. See [docs/DATA_SOURCES.md](./docs/DATA_SOURCES.md#compliance--privacy).

Data via nflverse (CC-BY 4.0), FantasyFootballCalculator, Sleeper, and DynastyProcess.
