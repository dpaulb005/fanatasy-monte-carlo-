# RESEARCH LOG

Research date: **2026-07-14**. Purpose: inform the design of a private, self-hosted ESPN
fantasy-football league analytics + comedy dashboard (Django + DRF + PostgreSQL + Vue 3).
Only feature ideas and public patterns are recorded here — no proprietary UI or unlicensed
code is copied.

All web content and external code referenced below is treated as **untrusted**: findings
are used to inform design decisions, never executed or vendored without review.

---

## 1. Competitive / Product Landscape

### Commercial & freemium league-analysis tools

| Product | Strengths worth adapting | Gaps | Notes |
|---|---|---|---|
| **League Vault** (league-vault.com) | Direct ESPN + Sleeper sync (no CSV upload); bundles history / draft grades / trades / records / rivalries / playoff insight — a good top-level IA blueprint | Closed source; hides the luck/expected-win math | Auto-sync is table stakes now |
| **League Legacy** (leaguelegacy.io) | "Record Book" framing — longest streaks & droughts, all-time member rankings; leans into comedy (Hall of Fame, roast the last place); companion newsletter-automation product | $36/yr, template-driven | Closest **tonal** match to our comedy pillar |
| **Fantasy Record Book** (fantasyrecordbook.com) | **Cross-platform manager identity** (unify a career across renames/platforms); regular-season vs playoff H2H split; championship history with runner-up + title-game score | Record-keeping over analytics; light viz | Validates our `Manager` identity model (§6 of ARCHITECTURE) |
| **Fantasy Almanac** (almanacfantasy.com) | "Almanac/yearbook" visual-narrative metaphor — champions, rivalries, records as a browsable timeline | Closed; breadth over depth | Strong organizing concept |
| **KeepTradeCut** (keeptradecut.com) | Quantified trade fairness via crowdsourced values | Crowd model **not replicable** for one private league | Adapt the *concept* only (value trades vs actual points scored) |
| **Draft Sharks / 4for4 / FantasyPros / Underdog / FFCalculator** | Value-vs-ADP color scale (green=value, red=reach); ADP-over-time line charts | These are *pre-draft prep*, not post-hoc league retrospective | Reuse the **viz patterns** for retrospective draft grades |

### Open-source projects

| Project | License | Health | Relevance |
|---|---|---|---|
| **cwendt94/espn-api** | **MIT** | ~916★, v0.46.0 (Mar 2026), active | **Adopt as ingestion layer.** De-facto standard ESPN client. |
| **DesiPilla/espn-api-v3 ("Dorito Stats")** | verify before reuse | Active, hosted Django app | Same stack as us. Its metric set (luck-vs-skill, ROS simulations, lineup efficiency, milestone awards) ≈ our MVP analytics, validated by a real deployment. **Feature reference only.** |
| **uberfastman/fantasy-football-metrics-weekly-report** | **GPL-3.0** | ~223★, v21 (2025), active | Gold-standard metric definitions (coaching efficiency, points left on bench, Monte Carlo playoff odds). **Copyleft — do NOT vendor code; reimplement definitions from public descriptions.** Discord/Slack auto-post = nice distribution idea. Avoid its Selenium auth + PDF pipeline. |
| **raphattack/espn-ffb** | none (all-rights-reserved) | small | Closest architectural sibling: Flask + SQLAlchemy + **PostgreSQL**, persist-then-serve, editable recap-commentary templates. Validates persistence-first design. Reference only. |
| **Robert-litts/espn_api_fantasy_football** | none | early | Motivation = *preserve history before platform migration loses it* → design principle: snapshot raw history early. |

### Fun / social recap tools

- **Fantasy Football Wrapped** (fantasyfootballwrapped.net) / **Fantasy Wrapped** (fantasywrapped.dev):
  "Spotify Wrapped for fantasy" — swipeable, shareable, animated superlative slides. Viral, low
  friction. **Currently Sleeper-centric → ESPN-first Wrapped is an open niche.**
- Recurring award taxonomy across recap tools: Biggest Blowout, Closest Nail-biter, Manager of
  the Year (best moves ≠ champion), Sleeper Pick, Biggest Bust, Points Left on Bench, Highest/
  Lowest week, Best/Worst pick, Unluckiest team (high PF / low wins).

---

## 2. Table Stakes vs Differentiators

**Table stakes** (ship in MVP): all-time standings (W-L, PF/PA, win%, playoff apps, titles);
H2H records (regular vs playoff split, clickable to game log); champion/trophy room; weekly &
season highs/lows & blowouts; all-play power rankings / expected wins; luck index; streaks &
droughts; basic draft grades; auto-sync from ESPN.

**Differentiators** (our opportunities): coaching efficiency / points-left-on-bench; explicit
luck-vs-skill decomposition with narrative ("7-3 but should be 5-5"); retrospective draft value
(ADP/slot vs actual points, positional value curves); **ESPN-first "Wrapped" shareable cards**;
non-crowdsourced trade-outcome review; rivalry pages with streaks; manager-identity continuity
across renames.

**Biggest single opportunity:** combine *deep analytics* (luck/skill, coaching efficiency,
sim-based odds, retrospective draft value) with a *shareable comedy layer* — for **ESPN**.
Existing tools do one or the other, and the Wrapped tools are Sleeper-first and shallow.

---

## 3. ESPN Ingestion (findings)

- **No official ESPN fantasy API and no native CSV/Excel export.** All ingestion uses the
  internal `apis/v3` JSON API authenticated with the user's own browser-session cookies. This is
  the universal community practice.
- **Base host (current):** `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl` (the old
  `fantasy.espn.com` host is deprecated; ESPN moved reads in ~2024).
- **Two endpoint shapes split by season:** `/seasons/{year}/segments/0/leagues/{id}` for
  **2018→present**; `/leagueHistory/{id}?seasonId={year}` for **2017 and earlier** (returns an
  *array*, one element per season).
- **Data-fidelity boundary is 2019, not 2018.** `espn-api` guards `box_scores()` and
  `recent_activity()` to raise before **2019**. So:
  - **2019→present:** full fidelity (per-player weekly box scores, projections, activity,
    transactions).
  - **2018:** structural data solid; per-player box scores / activity unreliable/guarded.
  - **≤2017:** `leagueHistory` only — reliable: settings, teams/owners (SWID GUID), final
    scores, schedule, draft. Missing: per-player weekly box scores, transactions, activity.
- **Aug-2025 change:** `leagueHistory` now generally **requires the `espn_s2` cookie** — treat
  authenticated access as mandatory for historical backfill.
- **`espn-api`** (MIT, v0.46.0, active) is the recommended client. It has **no built-in
  rate-limit/backoff/429 handling** — the caller must add politeness middleware.
- **Backfill volume is small:** per season ≈ 1 settings + 1 teams/matchup + 1 draft +
  ~14–17 box-score calls (one per scoring period). A 10-season backfill ≈ a few hundred
  requests — trivially polite if serialized with jittered delay + backoff.
- **Stability:** undocumented API, changes without notice (2024 host move, Aug-2025 auth
  tightening are recent examples). Mitigation: pin `espn-api`, isolate all ESPN specifics behind
  an adapter port so a break is a one-file fix.

Detailed endpoint reference, `view` parameters, auth-cookie setup, and the season-era capability
matrix live in **[DATA_SOURCES.md](./DATA_SOURCES.md)**.

---

## 4. Public NFL Data (findings)

- **Critical migration:** **`nfl_data_py` is officially deprecated** — its README directs users
  to **`nflreadpy`** (the maintained Python successor; returns Polars DataFrames with
  `.to_pandas()`, MIT code). All new code targets `nflreadpy`.
- **nflverse** is the backbone: free, **CC-BY 4.0** data, weekly player stats & play-by-play
  back to **1999**, `fantasy_points` / `fantasy_points_ppr` pre-computed. No auth, no rate limit
  beyond GitHub's.
- **Player identity is solved:** `nflreadpy.load_ff_playerids()` (DynastyProcess crosswalk,
  ~35 columns) maps `gsis_id` ↔ `espn_id` ↔ `sleeper_id` ↔ names. **Standardize the app on
  `gsis_id` as the canonical player key**; join ESPN players via `espn_id`, fall back to
  normalized name+position for the small unmatched tail.
- **ADP:** FantasyFootballCalculator free JSON API, historical **2014+**, all formats
  (standard/ppr/half/2qb), no auth, free for commercial use.
- **Optional:** Sleeper `/v1/players/nfl` (live player master + injuries; cache daily),
  `load_ff_opportunity()` (expected points, CC-BY-SA), DynastyProcess values.
- **Rejected:** FantasyPros scraping (ToS/no free API), Pro-Football-Reference scraping (ToS
  forbids redistribution, 20 req/min cap). nflverse covers the same stats cleanly.
- **Compliance:** add a visible attribution line ("Data via nflverse (CC-BY 4.0),
  FantasyFootballCalculator, Sleeper, DynastyProcess"). Keep any CC-BY-SA-derived outputs
  share-alike.

Full source inventory, licenses, and field notes in **[DATA_SOURCES.md](./DATA_SOURCES.md)**.

---

## 5. Rejected Ideas / Scope Discipline

- **Crowdsourced value models (KTC-style)** — impossible/pointless for one private league.
- **Selenium ESPN auth + PDF report pipelines** — the maintained API client + live web views are
  simpler.
- **Multi-platform abstraction (Yahoo/Sleeper/CBS)** — we are ESPN-only; skip the abstraction
  tax (but keep the adapter port so it's *possible* later).
- **Pre-draft ADP/projection tooling** — out of scope; our draft value is retrospective.
- **Redis / Celery / Kafka / GraphQL / ML** — deferred until a demonstrated need (see
  [DECISIONS.md](./DECISIONS.md)).

---

## 6. Open Research Questions (backlog)

- Optimal-lineup solver correctness across all historical ESPN roster-slot configs (FLEX / OP /
  IDP variants) — validate greedy vs exact per season settings.
- Fair cross-season comparison when scoring settings change (normalize to z-scores / percentiles
  within season).
- Statistical-significance guidance for small-sample league stats (10–14 teams × N seasons) —
  how to present "luckiest" without overclaiming.
- Player-crosswalk miss rate on rookies / mid-season name changes — measure after first real sync.

---

## Sources

ESPN: cwendt94/espn-api (GitHub, PyPI, `football/league.py`, `requests/espn_requests.py`);
stmorse.github.io ESPN v3 walkthrough; ffscrapr ESPN endpoint reference; fflr (Aug-2025 cookie
requirement); espn-api Discussions #150, #525.
Products: league-vault.com; leaguelegacy.io; fantasyrecordbook.com; almanacfantasy.com;
keeptradecut.com; fantasyfootballwrapped.net; fantasywrapped.dev; DesiPilla/espn-api-v3;
uberfastman/fantasy-football-metrics-weekly-report; raphattack/espn-ffb;
Robert-litts/espn_api_fantasy_football.
Public data: nflverse/nfl_data_py (deprecation notice); nflverse/nflreadpy + docs;
nflreadr load_player_stats / load_ff_playerids; FantasyFootballCalculator ADP API;
Sleeper API docs; dynastyprocess/data; sports-reference bot/data-use policies.
