# METRIC_CATALOG

Existing metrics (pre-session) are cataloged summarily; new P-1 metrics in full.
Every metric here must have a unit test before it ships to the UI.

## Pre-existing (defined in analytics/, tested in backend/league/tests/)
- **Expected wins (xWins)** — all-play weekly win share summed over season.
- **Luck** — actual wins − expected wins.
- **Lineup efficiency** — actual started points ÷ optimal-lineup points (2019+ eras only).
- **Points over replacement (draft)** — season points − positional replacement level;
  replacement = points of the rank-⌈starters×teams⌉ player among rostered players
  of that (season, position). Source: drafts.py `_replacement_levels`.
- **ADP delta** — overall_pick − FFC ADP, joined on (season, normalized name); null
  when unmatched (documented miss modes: suffixes, D/ST naming, FFC gaps).
- **Award formulas** — see analytics/awards.py; each award embeds its criteria.

## P-1: PlayerSeasonValue (new)
| Field | Definition |
|---|---|
| `total_points` | Σ LineupSlot.points for the player across all rosters, all weeks of the season (started + benched). Fantasy points under league scoring, ESPN-reported. |
| `started_points` | Σ points where slot ∉ {BE, IR}. |
| `bench_points` | Σ points where slot ∈ {BE, IR}. |
| `weeks_rostered` | COUNT of lineup rows (unique weeks; a player is on ≤1 roster/week). |
| `weeks_started` | COUNT where started. |
| `points_over_replacement` | total_points − replacement level of (season, position); same definition as draft metric above. |
| `position_rank` | Rank of total_points within (season, position) among rostered players (1 = best). |

- Granularity: season. Missing data: none within 2020–2025 (all seasons have
  lineups); if a future season lacks lineups (`lineups_available=False`), no rows
  are computed and the UI must say why. Free agents: absent by construction —
  "points while rostered in this league", not NFL totals. Min sample: none
  (facts, not inferences). API: `players/` + `players/<id>/`. UI: Player Explorer.

## P-1: PlayerManagerSeasonValue (new)
Same fields as PlayerSeasonValue but restricted to weeks the player sat on a
team_season managed by that manager. Splits are guaranteed to sum to the season
totals (tested). Co-managed teams: each listed manager is credited with the same
team-weeks (consistent with TeamSeason career attribution; noted in UI copy).

## P-1 interpretation notes
- "Greatest player" defaults to points_over_replacement, not raw points, so kickers
  with many weeks don't outrank scarce elite RBs; both are shown.
- Raw points are not era-adjusted; position_rank/percentile is the honest
  cross-era comparator (league size changed 6→12 teams). UI shows season context.

## P-3: bench_losses (new)
- Definition: count of REGULAR-season losses where `optimal_points(roster)` —
  the best slot-legal lineup from that week's actual roster — strictly exceeds
  the opponent's actual score. Opponent lineup is taken as played.
- NOT a sum of bench points; each counted week is individually winnable.
- Missing data: seasons without lineups contribute 0 (never shown as "clean").
- Limitations: assumes opponent lineup fixed; ties are not counted; playoff
  weeks excluded (REG only, consistent with other weekly metrics).
- Tests: hand-built winnable-vs-honest-loss scenario; bench_losses <= losses.
- API: manager profile season rows. UI: ManagerView column (tooltip carries
  definition); award "Left It on the Bench" with weeks in context.

## M-1: scouting traits (new)
All career aggregates over ManagerSeasonStats (REG season), percentile-ranked
among managers with >= 2 seasons (SCOUTING_MIN_SEASONS):
- Firepower = Σ points_for / Σ games. Volatility = mean weekly_score_stddev.
- Fortune = Σ luck_delta (wins − expected wins). Discipline = Σ points_for /
  Σ optimal_points. Self-sabotage = Σ bench_losses / Σ losses (lower better —
  percentile inverted).
- Missing data: < 2 seasons → values shown, percentiles null, reason in UI.
- Limitations: era-mixed raw values (firepower spans 6- to 12-team seasons);
  percentiles are the comparator, values are context.

## DA-1: draft patterns / sequences (new)
Stored as the league-wide SeasonTrend blob `draft_patterns` (own endpoint
`/api/v1/drafts/patterns/`, excluded from `/trends/`). Per canonical manager:
- Sequence ("draft DNA"): every draft's picks in overall_pick order with
  position, player, keeper flag, adp_delta, points_over_replacement.
- Opening signature: positions of the first 3 LIVE picks (keepers excluded, so
  keeper years start at the first live pick); most common across drafts.
- avg_first_round per position: mean round of the first QB/RB/WR/TE/DST/K taken.
- Phase position shares: pick-share by position in rounds 1-3 / 4-8 / 9+.
- Reach/value: adp_delta = overall_pick − adp (negative = reach). Rates use
  |Δ| ≥ ADP_SWING_THRESHOLD (5 slots); avg_adp_delta over ADP-matched picks.
- avg_draft_por: mean total points_over_replacement per draft class (keepers
  included here — the roster outcome, not a drafting skill claim).
- Missing data: picks without ADP are excluded from reach/value rates
  (`adp_picks` reports coverage); co-managers each get credited with the draft.
- Limitations: descriptive, not predictive; auction seasons would need spend
  patterns instead of slot sequence (not built).
- Tests: test_draft_patterns.py (compute over synthetic keeper league +
  endpoint shape + trends-leak guard).
- UI: Draft DNA view (/drafts/patterns) — tendency table + per-draft colored
  sequence strips (position letter in every cell; color never the only channel).

## DS-1: draft suggester priors + availability CIs (new)
Priors precomputed into the `draft_priors` SeasonTrend blob (excluded from
/trends/); ranking happens at request time in `/api/v1/drafts/suggest/`.
- ADP calibration: residual = overall_pick − adp over all ADP-matched,
  non-keeper picks in history. bias = mean, sigma = stdev (floored at 3.0),
  per position when n ≥ 8 else overall fallback.
- Expected pick μ = max(1, adp + bias_pos); 80% CI = μ ± 1.2816·σ_pos.
- Availability: P(available at pick N) = 1 − Φ((N − μ)/σ), clamped to 1.0 at
  N=1 (untouched board); also computed for the user's next snake pick.
  Candidates below 5% availability are dropped from the board.
- Value bands: quantiles (p10..p90) of realized points-over-replacement by
  position × round across synced history; phase (early/mid/late) fallback for
  empty cells. Board sorted by μ (league-adjusted market order).
- Limitations (ADR-012): no player-skill projection — ADP is the only
  forward-looking signal; latest synced ADP season may lag the upcoming
  draft; normal model ignores that exactly N−1 players are gone at pick N
  (availability is an approximation, worst near the top of the board);
  FFC ADP assumes 12-team formats. Last-season PoR shown as context only.
- Tests: test_draft_suggester.py (snake math, quantile monotonicity,
  calibration from synthetic residuals, endpoint ordering/filtering/CI sanity).
- UI: Suggester page (/drafts/suggester) — teams/slot/pick controls, snake
  pick chips, CI bars with current-pick marker, availability color + %.

## PJ-1..3: projections pipeline (new)
- PlayerProjection (migration 0006): season-long (week=0) draft-time
  projections per source; Sleeper is the real source (frozen preseason,
  2019-2025, keyless — RESEARCH.md R-3), synthetic derives actual+N(0,25)
  for offline dev/tests. espn_player_id crosswalk from Sleeper player dump.
- Scale detection: the league's scoring format isn't recorded, so the
  analytics pick the projection column (ppr/half/std) minimizing median
  |actual − projected| over matched player-seasons.
- projection_error (in draft_priors blob): residual quantiles p10..p90
  per position (n ≥ 8, overall fallback). Suggester shows projected_points
  + projected_range = proj + [p10, p90] (~80% empirical CI). Residual actual
  = league-scored points while rostered — slightly understates players cut
  mid-season; documented, acceptable for drafted-player analysis.
- draft_patterns projection block: per-manager beat_rate (share of drafted
  players meeting/beating projection) + avg_delta; league-wide top-10
  steals/busts (actual − projected), keepers excluded.
- Sync: `sync_projections --source sleeper --years 2019-2025` (operator,
  network) or `--source synthetic`; SyncLog row with espn_id match count.

## DA-2: positional run detection (new)
- Run = >= 3 consecutive same-position picks in overall board order (keepers
  included in the sequence; a run is a board phenomenon).
- First pick STARTS the run; later picks JOINED; a join with adp_delta <=
  -5 (reached ahead of market to chase) is a PANIC JOIN.
- Per manager (patterns blob profile.runs): started / joined / panic_joins.
- League (patterns blob position_runs): total count + 10 longest with full
  pick lists and panic flags.
- UI: Draft DNA "Longest position runs" table (panic joins struck in red
  with a bolt) + "Runs" column in tendencies.

## CS/GF/AF: expert sheets, gap forecast, affinity (new, 2026-08-03)
- ExpertRanking (0007): operator cheat sheets via load_expert_ranks; JSON
  fixtures parsed from PDFs (league/fixtures/expert_ranks/). bigga = per-pos
  rank/tier(1-9)/risk/upside/ADP(round.pick, 12-team); flock = overall
  rank/tier(S-P)/ESPN rank/consensus ADP. Joined by normalized name.
- Suggester expert block: edge = market ADP − expert overall rank (positive
  = experts say he's better than his price). Letter tier from ranking sheet.
- The Gap (gap_forecast): expected players taken per position between the
  current pick and the user's next = Σ max(0, p_now − p_next) over live
  candidates (whole board, pre-filter). Tier survival: for the best letter
  tier per position among players with p_now ≥ 0.5, P(at least one survives
  to next pick) = 1 − Π(1 − p_next) (independence approximation, stated).
- Affinity (patterns blob, profile.affinity): per manager, players with mean
  (actual − projected) ≤ −35 (burned) or ≥ +35 (loyal); PoR fallback when no
  projection. Top 5 each. Suggester flags candidates with burned/loyal
  manager labels — the "won't redraft his bust / will reach for his guy"
  signal. Descriptive only; not yet folded into availability math (see
  backlog: opponent modeling).
- Limitations: expert sheets are a point-in-time operator upload; edge vs
  a stale ADP season exaggerates (fix by syncing current-year ADP); tier
  survival assumes independent picks.
