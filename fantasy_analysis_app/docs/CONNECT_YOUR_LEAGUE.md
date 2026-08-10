# Connecting your ESPN league

This app syncs your league on **your own machine** — ESPN's API is read directly
using your browser session, and your credentials never leave your computer. (The
build/CI environment cannot reach ESPN's servers, so a live sync must be run
locally.)

## 1. Find your league details

From your league URL, e.g.
`https://fantasy.espn.com/football/team?leagueId=XXXXXXXX&teamId=6&seasonId=2026`:

- `leagueId` → `ESPN_LEAGUE_ID`
- `seasonId` is the current season; set `ESPN_START_YEAR` to your league's **first**
  season so the backfill covers your whole history.

## 2. Get your cookies (private leagues)

Most leagues are private, so you need two cookies from a browser where you're
logged in to ESPN:

1. Log in at <https://fantasy.espn.com>.
2. Open DevTools (F12) → **Application** (Chrome/Edge) or **Storage** (Firefox) →
   **Cookies** → `https://fantasy.espn.com`.
3. Copy:
   - `SWID` — a GUID in braces, e.g. `{AAAA1111-....}` (include the braces).
   - `espn_s2` — a long URL-encoded string (~300+ chars).

These authenticate **as you**. Keep them secret — never share, never commit.
(A fully public league needs no cookies; leave them blank.)

## 3. Configure `.env`

Copy `.env.example` to `.env` (it is gitignored) and fill in:

```
ESPN_LEAGUE_ID=XXXXXXXX
ESPN_START_YEAR=2016          # your league's first season
ESPN_S2=<your espn_s2 cookie>
ESPN_SWID={<your SWID>}
```

## 4. Sync + compute

```
cd backend
.venv/bin/pip install -r requirements.txt      # includes espn-api
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_espn --years <first>-<current>   # e.g. 2016-2026
.venv/bin/python manage.py sync_nfl_context --source ffc --years <first>-<current>
.venv/bin/python manage.py compute_analytics
```

Then run the servers (`manage.py runserver` + `cd frontend && npm run dev`) and
open <http://localhost:5173>.

### Notes on ESPN data by season

- **2019 → present:** full fidelity (weekly box scores, lineups, transactions).
- **2018 and earlier:** standings, drafts, final scores, and settings only —
  per-player weekly lineups aren't available, so bench/optimal-lineup analytics
  are skipped for those seasons (they degrade gracefully).
- The 2026 season won't have game data until the NFL season starts; sync it once
  your draft/weeks begin. Historical seasons can be backfilled any time.

### Re-syncing

- Completed seasons are cached and skipped on re-run (`--force` to override).
- During the season, `python manage.py full_sync` refreshes the current season
  and recomputes analytics — good for a weekly cron.

### If a sync fails

- `ESPNAccessDenied` → your cookies are missing, wrong, or expired: re-copy them
  (they rotate on password change / logout-all).
- `ESPNInvalidLeague` → check `ESPN_LEAGUE_ID`.
- Network/proxy errors → run the sync from a machine with normal internet access
  (some managed/CI environments block ESPN's host).
