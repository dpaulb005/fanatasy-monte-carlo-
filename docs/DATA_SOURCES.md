# DATA SOURCES

Inventory of every data source the app ingests, with access method, auth, coverage, license,
limits, provenance rules, and fallback strategy. All external content is treated as untrusted
input.

---

## Source inventory

| Source | Role | Access | Auth | History | License | Redistribution |
|---|---|---|---|---|---|---|
| **ESPN Fantasy `apis/v3`** (via `espn-api`) | Private league data (the user's own league) | Unofficial JSON API / `espn-api` MIT client | `espn_s2` + `SWID` cookies (user's own) | Full structural back to league start; per-player weekly 2019+ | None (undocumented) | **Do not redistribute.** Private/self-hosted only |
| **nflverse** (via `nflreadpy`) | Public NFL player weekly/seasonal stats, rosters, schedules | GitHub release assets / `nflreadpy` | None | 1999→present | **CC-BY 4.0** (FTN subset CC-BY-SA) | Permitted with attribution |
| **nflverse `load_ff_playerids`** (DynastyProcess) | Player-ID crosswalk (`gsis_id`↔`espn_id`↔…) | `nflreadpy` | None | current, weekly rebuild | CC-BY 4.0 / CC0 subset | Permitted with attribution |
| **FantasyFootballCalculator** | Historical ADP by season/format | Free JSON REST API | None | 2014+ | Free for commercial use | Consume/derive; don't rebroadcast raw feed publicly |
| **Sleeper `/v1/players/nfl`** *(optional)* | Live player master, injuries, depth, secondary IDs | Free JSON API | None | current only | Free, terms unstated | Keep internal to app |

---

## ESPN Fantasy API reference

### Base host & endpoint shapes

```
Base (current):  https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl
2018 → present:  /seasons/{year}/segments/0/leagues/{leagueId}
2017 and earlier: /leagueHistory/{leagueId}?seasonId={year}    # returns an ARRAY
```

`ffl` = football. The old `fantasy.espn.com` host is deprecated. `leagueHistory` returns a
one-element-per-season array — client code must handle both the object and array shapes.

### `view` query parameters (repeatable: `&view=...&view=...`)

| `view` | Returns |
|---|---|
| `mSettings` | League config: name, size, scoring rules, roster slots, schedule, playoff format, divisions, scoring-period calendar |
| `mTeam` | Teams: id, name/abbrev, owners (SWID GUID list), W/L/T, PF/PA, standing, division |
| `mRoster` | Roster entries per team (+ `scoringPeriodId` for weekly rosters): players, lineup slot IDs, acquisition type |
| `mMatchup` / `mMatchupScore` | Full-season schedule/matchup grid; `…Score` adds score detail |
| `mBoxscore` | Per-matchup box scores: per-player projected + actual points, slots. Requires `scoringPeriodId` |
| `mDraftDetail` | Every draft pick: overall no., round, roundPick, teamId, playerId, keeper flag, auction bid |
| `mTransactions2` | Transaction log: adds/drops/waivers/trades, type, status, bid, period |
| `kona_player_info` | Player catalog: metadata, ownership %, projections, injury (usually needs `X-Fantasy-Filter` header) |
| `kona_league_communication` | Activity feed (backs `recent_activity()`) |

Scope to a week with `&scoringPeriodId={n}`.

### Season-era capability matrix

| Data | 2019 → present | 2018 | 2017 and earlier (`leagueHistory`) |
|---|---|---|---|
| Settings / scoring / roster rules | ✅ | ✅ | ✅ |
| Teams, owners (SWID GUID), records, points | ✅ | ✅ | ✅ |
| Full-season schedule + final scores | ✅ | ✅ | ✅ |
| Draft results | ✅ | ✅ | ✅ |
| **Per-player weekly box scores** | ✅ | ⚠️ raw endpoint only (`espn-api` guards <2019) | ❌ |
| **Activity feed / transactions** | ✅ | ⚠️ spotty | ❌ |

**Design consequence:** two ingestion tiers — *summary* (all seasons) and *detailed weekly*
(2019+). Do not promise per-player weekly analytics for pre-2019 seasons; mark those seasons
`lineups_available=False` so analytics degrade gracefully.

### Authentication cookies (README-ready)

1. Log in at https://fantasy.espn.com in a desktop browser.
2. DevTools (F12) → **Application/Storage** → **Cookies** → `https://fantasy.espn.com`.
3. Copy:
   - `SWID` — GUID in braces `{AAAA1111-...}` (include braces).
   - `espn_s2` — long URL-encoded string (~300+ chars).
4. Provide as env vars `ESPN_S2` / `SWID` (never commit). Cookies are long-lived but rotate on
   password change / logout-all — plan a refresh procedure. They authenticate **as you** to all
   your ESPN fantasy data: treat as secrets.

### `espn-api` client notes

- MIT, v0.46.0 (Mar 2026), active. `pip install espn-api`. Python 3.8+.
- `League(league_id, year, espn_s2, swid)`; `fetch_league=False` to defer I/O; `debug=True` to
  log requests.
- Surface: `.teams`, `.members` (name + SWID), `.settings`, `.draft`, `.box_scores(week)`,
  `.scoreboard(week)`, `.standings()`, `.recent_activity()`, `.transactions()`.
- Error handling: 401 → auto-swaps current/history endpoint once, else `ESPNAccessDenied`;
  404 → `ESPNInvalidLeague`. **No 429/backoff handling — we add politeness middleware.**

### Rate limits & politeness (we implement)

No published limits; undocumented throttling possible under bursts. Our request wrapper:
serialize backfill (no parallel fan-out), jittered 0.5–2 s delay between calls, exponential
backoff + jitter on 429/5xx honoring `Retry-After`, desktop `User-Agent`. Cache immutable
completed-season data (settings/draft/final box scores) — fetch once, never re-fetch. In-season
sync touches only current + just-completed scoring period.

---

## Public NFL data reference

### nflverse via `nflreadpy` (PRIMARY)

**Use `nflreadpy`, not the deprecated `nfl_data_py`.** Returns Polars (`.to_pandas()` available),
MIT code, built-in caching.

| Function | Data |
|---|---|
| `load_player_stats()` | Weekly/seasonal player stats incl. `fantasy_points`, `fantasy_points_ppr` (1999+) |
| `load_ff_playerids()` | DynastyProcess ID crosswalk (`gsis_id`, `espn_id`, `sleeper_id`, name, position, team) |
| `load_rosters()` / `load_rosters_weekly()` | Rosters |
| `load_schedules()` | Schedules/results |
| `load_snap_counts()` / `load_depth_charts()` | Usage/depth (optional) |
| `load_ff_opportunity()` | Expected fantasy points (CC-BY-SA, optional) |

Coverage: weekly player stats & pbp back to **1999**; snap counts ~2012+. Update: nightly in
season. License: **CC-BY 4.0** (FTN participation subset CC-BY-SA). No auth, no rate limit
beyond GitHub.

**Migration note:** old `nfl_data_py` names (`import_weekly_data`, `import_ids`,
`import_seasonal_rosters`) → `nflreadpy` (`load_player_stats`, `load_ff_playerids`,
`load_rosters*`).

### FantasyFootballCalculator ADP (PRIMARY for ADP)

```
GET https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams={n}&year={yyyy}&position={pos}
    format = standard | ppr | half-ppr | 2qb | dynasty | rookie
```

JSON; player objects include name, position, team, adp, high/low pick, times drafted, std dev.
History **2014+**. No auth, no published limits (cache per `(year, format, teams)` permanently
once a season ends). Free for personal & commercial use.

### Sleeper (OPTIONAL)

`GET https://api.sleeper.app/v1/players/nfl` — full player universe (~5 MB) incl. cross-ref IDs,
injury status, depth order. No auth. **Cache once/day** (Sleeper advises ≤1 call/day for this
dump). Secondary ID bridge + live injury/depth metadata.

---

## Player identity reconciliation

Canonical internal key = **`gsis_id`**.

1. Ingest nflverse weekly stats keyed on `gsis_id`.
2. Load `load_ff_playerids()`; build `gsis_id → {espn_id, sleeper_id, name, position, team}`.
3. Match ESPN league players via `espn_id`; fall back to normalized name+position+team for the
   unmatched tail (crosswalks lag a few days on brand-new rookies).
4. Log unmatched players for admin fixup (non-blocking — all ESPN-only analytics work without
   the crosswalk).

---

## Provenance rules

- Persist the **raw JSON payload** for every ESPN request keyed by
  `(league_id, year, view, scoringPeriodId)` **before** parsing (a `RawSourcePayload` store),
  so parser changes can re-run offline and completed-season data is fetched once.
- Every computed metric is traceable to source records + a documented formula
  (see [METRICS_CATALOG.md](./METRICS_CATALOG.md)).
- Record each ingestion run (`IngestionRun`/`SyncLog`): command, seasons, timestamps, status,
  row counts.

---

## Fallback strategies

- **No credentials / offline / CI:** `FixtureSource` reads saved JSON (curated golden fixtures +
  a deterministic synthetic multi-season league). All development and tests run credential-free.
- **Pre-2019 seasons:** summary tier only; `lineups_available=False`.
- **`espn-api` upstream break:** adapter port isolates it to one file; raw-`requests` fallback
  for the 2018/pre-2019 structural gaps.
- **Crosswalk miss:** name+position fallback, admin-editable alias.

---

## Compliance & privacy

- **Attribution:** visible line "Data via nflverse (CC-BY 4.0), FantasyFootballCalculator,
  Sleeper, DynastyProcess." Keep CC-BY-SA-derived outputs share-alike.
- **ESPN:** personal, private, low-volume, read-only, **non-redistributed** use of the user's own
  credentials on their own league is the intended community pattern (not legal advice). Never
  collect others' cookies, never read leagues you're not in, never redistribute raw ESPN data.
- **Personal data:** other managers' display names + SWID GUIDs are personal data — keep the app
  private/access-controlled, never expose GUIDs in public URLs/exports, provide a redaction/
  deletion path. Secrets live in env only, never in VCS, logs, or fixtures.
