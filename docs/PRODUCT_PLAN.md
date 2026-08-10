# PRODUCT PLAN

## Vision

A private analytics website, historical archive, scouting report, and comedy dashboard for one
long-running ESPN fantasy football league. It should feel like a **league yearbook crossed with
a stats lab**: deep, explainable analytics on one screen and shareable, funny superlatives on the
next — all for the same group of managers tracked across many seasons.

Every number is traceable to source records and a documented formula. Funny stats are derived
from real data, never fabricated.

## Users

- **Primary:** the commissioner / league historian (the operator) who runs the sync and browses
  everything.
- **Secondary:** league managers who view their own profiles, rivalries, and season recaps
  (read-only; local/self-hosted so sharing is via screen-share or exported cards initially).

## Core workflows

1. **Sync** — operator runs a management command to pull the league's full ESPN history + public
   NFL context into PostgreSQL, then precompute analytics.
2. **Browse league** — overview, standings, champions, records, trends.
3. **Browse a manager** — career page: records, luck, draft skill, rivalries, funny stats.
4. **Browse a season** — standings, weekly scores, playoff bracket, awards, recap.
5. **Explore drafts** — retrospective value: ADP/slot vs actual points, steals & reaches.
6. **Share** — auto-generated superlative / "Wrapped"-style cards.

## MVP (Phases 1–4)

Auto-sync from ESPN → PostgreSQL; all-time standings & records; head-to-head matrix; champion/
trophy room; weekly & season highs/lows & blowouts; **all-play power rankings / expected wins**;
**luck index**; streaks & droughts; a manager career page and a season page with the first
charts. Runs entirely on fixture data without ESPN credentials.

**MVP exit criteria:** load the synthetic multi-season fixture league, browse the home dashboard,
open a manager profile and a season page, and see correct standings, H2H, and a luck chart —
end-to-end, fast, on a laptop.

## Later phases

- **Phase 5 — League trends:** scoring evolution, parity, positional trends, bench inefficiency,
  schedule luck, rivalry pages.
- **Phase 6 — Draft intelligence:** retrospective draft value using public ADP + player outcomes;
  positional value curves; reach/value; clearly separating *history* vs *public consensus* vs
  *league tendency* vs *projection* vs *uncertainty*.
- **Phase 7 — Entertainment:** annual awards, manager archetypes, record book, season-recap
  narratives (citing the underlying stats), and shareable stat cards.

## Feature priorities

1. Correct, explainable core records + luck (the credibility foundation).
2. Manager-identity continuity across renames/seasons (the thing hobby projects get wrong).
3. Comedy/superlatives layer (the thing that makes it fun to return to).
4. Draft intelligence (the differentiator vs pre-draft tools).

## Success criteria

- A full multi-season history is browsable locally in a few clicks.
- Every metric has a definition, formula, and passing unit test.
- Page loads are fast (precomputed analytics; no per-request full-history scans).
- Adding a new award = one analytics function + one frontend card (no schema change).
- Setup is a documented `make` target + `.env`; no cloud services required.

## Non-goals

- Multi-platform support (Yahoo/Sleeper/CBS) — ESPN-only (adapter keeps it *possible* later).
- Pre-draft prep / live projections / a prediction engine.
- Real-time / streaming updates — season history is not real-time.
- Crowdsourced trade values — impossible for one private league.
- Public multi-tenant hosting / monetization.
- Machine learning where a deterministic formula is clearer.

## Privacy assumptions

- Self-hosted, single league, access-controlled. Other managers' names + SWID GUIDs are personal
  data: never exposed in public URLs/exports, redaction/deletion path provided.
- ESPN credentials and any secrets live in env only — never in VCS, logs, or fixtures.
- League data is not exposed publicly by default.
