# RESEARCH

## R-1: Can historical ESPN transactions be recovered? (2026-07-15)
- Question: is trade/waiver history retrievable for completed seasons 2020–2025?
- Sources: live probes against lm-api-reads.fantasy.espn.com (league 81945815, authed);
  espn-api 0.46.0 source (`requests/espn_requests.py`, installed in the backend image).
- Findings: `/communication/?view=kona_league_communication` → HTTP 404 for every
  completed season; HTTP 200 (0 topics) for the current season. `?view=mTransactions2`
  → 200 but no transactions payload for past seasons. espn-api's
  `recent_activity()` maps the 404 to `ESPNInvalidLeague`.
- Conclusion: historical transactions are unrecoverable. Current-season capture is
  feasible (weekly cron during the season). Implemented: no (backlog P-2).
- Also observed: ESPN edge throttling intermittently 404s valid requests after
  bursts → ingestion retry policy needed (backlog D-1).

## R-2: Manager-attributed player value — method (2026-07-15)
- Question: how to credit player production to managers without attributing
  full seasons to partial-season owners?
- Basis: LineupSlot rows are per (team_season, week, player) with points and slot,
  for every rostered player incl. bench (2019+ era; this league is fully 2020+).
  Ownership intervals are therefore implicit and exact at week granularity —
  no transaction data needed.
- Method chosen: weekly attribution. A player-week belongs to the team (and its
  manager(s)) whose roster held the player that week. Manager splits must sum to
  the player's season totals. Replacement level reuses the existing
  `_replacement_levels` (drafts.py): rank = round(starters_per_position × teams)
  over the rostered-player pool per season — keeps one definition league-wide.
- Rejected alternative: full-season attribution to final owner (violates the
  partial-ownership rule); daily granularity (no data).
- Limitations: co-managed teams credit each listed manager with the same team-week
  (documented; consistent with existing career stats which are team-based);
  free agents invisible; K/DST replacement pools thin in 6-team 2020 season.
- Implemented: yes — P-1 slice (this session).

## R-3: Which normalized cross-era measure first? (2026-07-15)
- Question: raw points mislead across eras (league grew 6→12 teams, scoring
  drifted). What's the first honest normalized measure?
- Options considered: season z-score (sensitive to small N per position),
  percent-above-median, position percentile among rostered player-seasons.
- Decision: position-rank + percentile within (season, position) pool — simple,
  explainable, uses the same pool as replacement level. Z-scores deferred.
- Implemented: position_rank in P-1.

## R-3: Historical projection data sources (2026-08-02)
- Question: can free, programmatic NFL fantasy projections be found for past
  seasons (2019-2025) — draft-time season-long and weekly?
- Method: four parallel research agents (nflverse/GitHub, FantasyPros/
  aggregators, platform APIs, community archives), all instructed to verify by
  fetching; conflicting claims re-verified directly.

### VERIFIED — draft-time season-long projections (the scarce commodity)
- **Sleeper undocumented API (PRIMARY)**: `api.sleeper.app/projections/nfl/{year}
  ?season_type=regular&position[]=RB...` — keyless, frozen preseason
  projections (re-verified directly: McCaffrey 2021 = 17 gp, 1126 rush yd,
  363.3 pts_ppr despite playing 7 games). ~550-750 players/season, 2019-2025,
  full component stats (re-scorable to league scoring), pts_ppr/half/std,
  ADP block real from 2020+. `api.sleeper.app/v1/players/nfl` (14 MB, one
  call) maps sleeper->espn_id for 6,736 players — native join to Player, no
  name matching. Undocumented => fetch-once-and-persist (fits ADR persist-
  first); ~1000 calls/min politeness ceiling, one call per season needed.
- **FantasyPros consensus via Wayback (SECOND OPINION)**: full draft-time
  tables (90-280 rows/position) with period-accurate rosters, 2019-2025, every
  skill position (gaps: DST 2020+2025). Key discovery: `week=draft` values
  stay frozen all season, so any snapshot from the season year works. Gotchas:
  `id_` endpoint returns raw gzip; CDX must be queried with wildcard not
  exact-URL. Live site `?year=` works back to 2014 but anonymously capped at
  10 rows and shows PRESENT-DAY team labels. Official API: $8.99/mo personal
  tier exists but historical/bulk appears Commercial-gated (unconfirmed).
- **ESPN season-long projected_total_points: DO NOT USE for past seasons** —
  verified contaminated end-state (2023 Chubb/Rodgers = 0.0 post-injury), not
  a preseason snapshot. (Conflicting agent claim rejected on value evidence.)

### VERIFIED — weekly projections
- **Already in our DB**: LineupSlot.projected_points populated for rostered
  player-weeks 2019+ (ESPN box scores; 9724/9750 non-zero even in demo).
- **hvpkod/NFL-Data (GitHub, MIT)**: NFL.com weekly projections 2021-2025 with
  raw stat categories (re-scorable); no DST; schema drift 2021 vs 2022+;
  NFL-ids need crosswalk (Sleeper dump or nflverse ff_playerids covers it).
  README's "back to 2015" claim is false — nothing before 2021.
- **ESPN public v3 API**: weekly projections 2018-2025 (~255-320 players/wk,
  statSourceId=1), no auth — but week 1 is degraded/decayed for past seasons.
- **Sleeper weekly**: 2019-2025, but survivorship: only weeks the player was
  expected to play — never sum weekly to reconstruct a preseason total.

### Useful adjacent (not projections)
- DynastyProcess `db_fpecr`: FantasyPros ECR ranks archive 2020-2025, 9-10
  preseason snapshots/yr (draft-day market signal; no points).
- ffopportunity (nflverse): RETRODICTIVE expected points 2006-2025 — a luck/
  regression baseline, never a projection.
- MyFantasyLeague keyless historical ADP (second ADP opinion).

### Dead ends (do not re-investigate)
Yahoo (no player projections exposed at all, OAuth burden), NFL.com live API
(v1 404, v2 ignores season), CBS (year param ignored), numberFire live
(redirects to FanDuel), ffanalytics retroactive scraping (explicitly does not
work), FFA archive (paywalled), Kaggle (single-season snapshots only),
data.world (platform retired 2026-07), academic replication packages (none),
paid APIs (no affordable 2019-2025 archive; Fantasy Nerds $399/yr is
current-season-only; SportsData.io historical is quote-gated).

### ToS posture (private, self-hosted, non-commercial)
FantasyPros robots.txt allows /nfl/projections/ (crawl-delay 5); Sleeper docs
say no token needed, stay under 1000 calls/min; keep data private, honest
User-Agent, cache immutably, don't republish. Avoid NFL.com/CBS scraping
(explicit bans) — not needed anyway.

### Decision
PJ-1: PlayerProjection model + `sync_projections --source sleeper` backfill
2019-2025 (+ current season each August). PJ-2: suggester upgrade — per-player
projected points with empirical CIs from historical projection-error residuals
(actual vs projected by position), replacing position-round bands as the
primary value signal. PJ-3: draft retrospectives — who beat the projections.
Later: Wayback FantasyPros consensus as second source; hvpkod weekly for
start/sit analytics; ffopportunity luck baseline.

## R-4: Risk-adjusted drafting science (2026-08-03, agent-verified)
Deep dive into portfolio theory applied to fantasy (Hunter/Vielma/Zaman
arXiv:1604.01455; Haugh & Singal, Management Science 67(1) 2021; ETR/
PlayerProfiler/Spike Week best-ball empirics). Key verified findings:
- **The variance sign flip** (Haugh & Singal Alg. 2): if expected margin vs
  the payout threshold is positive, MINIMIZE variance; if negative, MAXIMIZE
  it. "Tournaments want ceiling" is just the special case of being behind.
  → Implemented as the Draft Day "Risk posture" advisor (my proj pts/pick vs
  room average; ±5 pts threshold; one-click lens switch).
- It's covariance-with-the-field that matters, not raw variance; naive
  Markowitz is mis-specified for rank-based payouts (ordinal objective).
- Published correlation matrices exist (Spike Week 2018-2023: QB-WR1 0.542,
  WR1-oppWR1 0.56, QB-RB1 0.09) — relevant if we ever build lineup/stack
  tools; less so for H2H redraft drafting.
- Epistemic (projector disagreement) ≠ aleatory (week-to-week) variance —
  never conflate; our expert RISK grades are closer to epistemic.
- Full report in agent transcript; sources cited inline there.
