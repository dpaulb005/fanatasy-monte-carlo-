# CHANGELOG

## 2026-07-15 — autonomous session 1

- `94649de` fix(ingestion): live-sync fixes — FFC User-Agent 403; real league name
  on League row; real manager first/last names over ESPN handles; never clobber
  player name/position/gsis_id with blanks (fixed 79% positionless started slots).
  Verified: live re-sync of 2020–2025, 46 tests, ruff, mypy.
- `4e96255` chore(security): .env untracked (was committed with live cookies),
  `.env copy.example` scrubbed, `scripts/check_secrets.sh` added to `make check`
  + CI, incident runbook `docs/SECURITY_CREDENTIALS.md` (human actions pending:
  cookie rotation; optional history rewrite).
- Live data state: league 81945815 ("Swaggy league") fully synced 2020–2025 into
  Docker Postgres; analytics computed; site verified page-by-page with screenshots.
- Capability probes: historical ESPN transactions unrecoverable (404 for completed
  seasons); FFC ADP live for 2020–2024, 2025 unpublished; ESPN edge throttling
  observed → retry policy queued (D-1).
- docs/autonomous system created (this directory).
- `9667668` feat(players): P-1 player value system + Player Explorer. New
  computed tables PlayerSeasonValue/PlayerManagerSeasonValue (weekly manager
  attribution; splits sum to season totals), players API (list + detail),
  Player Explorer UI with ownership-timeline strips. Also fixed pre-existing
  bugs surfaced by the slice: D/ST→DST normalization (inflated D/ST draft PoR,
  defenses invisible to positional trends and the optimal-lineup DST slot) and
  vitest collecting Playwright e2e specs. Post-review hardening: 400 on
  malformed query params, 404 for players with no league data, per-season
  position pools (ESPN relabels players), PoR=0 for unmapped positions,
  prefetch-respecting manager lookups (N+1), stale-response guard in the list
  view. 56 backend tests green; verified live (1,385 player-seasons).
- `838d064` feat(identity): I-1 manager merge mechanism. Manager.merged_into
  pointer (reversible, operator-only command with no-chain/no-overlap
  validation), canonical resolution in load_frames, purge-scope fix in
  compute_league, profile id resolution, 5 tests. Real merges staged
  (2→8 Covol, 13→9 Weyandt) pending operator confirmation.
- `e1a050e` feat(adp): D-2 name-join normalization (suffixes, punctuation,
  D/ST nickname->city crosswalk applied to both sides), draft_adp_matched
  surfaced per compute. Live: 2024 148->159/160. D-1 verified already covered
  by Politeness.call retry-all (documented).
- `c771a23` feat(lineups): P-3 bench losses — losses where a legal alternate
  lineup would have won; season stat + award + manager-page column. Live:
  David Brown leads all-time, 25/45 losses winnable.
- `d789726` feat(museum): V-5 Museum of Pain — six formula-backed exhibits
  (closest losses, wasted masterpieces, daylight burglaries, blowouts, worst
  bench weeks, losing streaks) as a SeasonTrend blob + /api/v1/museum/ + page.
- `3d0c4cc` feat(managers): M-1 scouting report — five formula-backed career
  traits with league-percentile bars, 2+ season min-sample rule, no invented
  archetypes.
- `c7cef70` refactor: consolidation — simplify sweep (3 safe cleanups) +
  12-route live smoke pass; e2e suite documented as fixture-only.
- V-3 feat(seasons): weekly scoring fingerprints — per-season small multiples
  (W/L-colored weekly bars + league median line) on season pages, computed as
  per-season SeasonTrend blobs.
- V-2 feat(drafts): draft value quadrant (pick cost vs PoR, median-pick +
  zero-PoR cross, manager filter); works without FFC ADP.
- S-1 feat(seasons): playoff race chart (cumulative wins, playoff teams in
  color, champion emphasized) from the fingerprints blob — frontend only.
