"""Deterministic synthetic league generator.

Produces a coherent multi-season ``SeasonBundle`` stream with no external
dependencies or randomness-from-clock, so dev and CI run credential-free and
reproducibly. Weekly team scores are derived from actual started lineups, so
bench-points / optimal-lineup / luck analytics operate on real structure.

Design choices that exercise the analytics and identity layers:
- 10 managers with stable GUIDs across every season (one changes display name
  each year to test that identity resolves on GUID, not name).
- Per-manager latent "skill" makes career records meaningful, not noise.
- Actual lineups deviate from optimal by a per-manager "coaching" factor, so
  lineup efficiency and bench-points-lost vary by manager.
"""

from __future__ import annotations

import random

from league.ingestion.schemas import (
    DraftRow,
    LineupRow,
    ManagerRef,
    MatchupRow,
    PlayerRef,
    SeasonBundle,
    TeamRow,
)

# Standard ESPN-ish lineup: dedicated slots then one FLEX, plus bench.
STARTER_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DST", "K"]
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
BENCH_SIZE = 6
ROSTER_SIZE = len(STARTER_SLOTS) + BENCH_SIZE  # 15
POSITION_POOL = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "DST", "K"]

NUM_TEAMS = 10
REG_WEEKS = 13
DEFAULT_SEASONS = [2019, 2020, 2021, 2022, 2023]

_TEAM_NAME_WORDS = [
    "Gridiron",
    "Turbo",
    "Cosmic",
    "Rogue",
    "Thunder",
    "Velvet",
    "Iron",
    "Feral",
    "Quantum",
    "Midnight",
    "Savage",
    "Electric",
]
_TEAM_NAME_NOUNS = [
    "Badgers",
    "Dynamos",
    "Llamas",
    "Raptors",
    "Comets",
    "Goblins",
    "Yetis",
    "Otters",
    "Vikings",
    "Pythons",
    "Bandits",
    "Falcons",
]


def _manager_guids() -> list[str]:
    return [f"{{MGR-{i:02d}-GUID}}" for i in range(NUM_TEAMS)]


def _manager_display_name(index: int, year: int) -> str:
    base = [
        "Alex",
        "Bailey",
        "Casey",
        "Devon",
        "Emerson",
        "Finley",
        "Gray",
        "Harper",
        "Indy",
        "Jules",
    ][index]
    # Manager 0 renames every season; everyone else is stable — this verifies
    # cross-season identity keys on GUID, not display name.
    if index == 0:
        return f"{base} (v{year - 2018})"
    return base


_FRANCHISE_POS = ["QB", "RB", "WR", "RB", "WR", "TE", "QB", "RB", "WR", "TE"]
_FRANCHISE_NAMES = [
    "Cornerstone Carter",
    "Dynasty Diaz",
    "Legacy Lang",
    "Franchise Frost",
    "Bedrock Boone",
    "Keystone Kane",
    "Anchor Ali",
    "Pillar Pope",
    "Mainstay Mercer",
    "Staple Stone",
]


def _franchise_players(team_ids: list[int]) -> dict[int, PlayerRef]:
    """Stable star players, one per team, identical across every season."""
    stars: dict[int, PlayerRef] = {}
    for tid in team_ids:
        idx = (tid - 1) % len(_FRANCHISE_NAMES)
        stars[tid] = PlayerRef(
            espn_player_id=900000 + tid,
            name=_FRANCHISE_NAMES[idx],
            position=_FRANCHISE_POS[idx],
        )
    return stars


def _make_players(rng: random.Random, year: int) -> list[PlayerRef]:
    """A fresh pool each season, large enough for a full draft + benches."""
    players: list[PlayerRef] = []
    needed = NUM_TEAMS * ROSTER_SIZE
    pid_base = year * 1000
    # Distribute positions roughly like a real player pool.
    weights = {"QB": 0.12, "RB": 0.28, "WR": 0.34, "TE": 0.12, "DST": 0.07, "K": 0.07}
    positions = list(weights.keys())
    probs = list(weights.values())
    for i in range(needed):
        pos = rng.choices(positions, weights=probs, k=1)[0]
        players.append(
            PlayerRef(
                espn_player_id=pid_base + i, name=f"{pos} Player {i:03d} '{year}", position=pos
            )
        )
    return players


def _weekly_points(rng: random.Random, position: str, quality: float) -> float:
    """A plausible weekly fantasy score for a player of given quality [0,1]."""
    base = {"QB": 18, "RB": 12, "WR": 11, "TE": 8, "DST": 7, "K": 8}[position]
    ceiling = base * (0.6 + 0.9 * quality)
    return max(0.0, round(rng.gauss(ceiling, ceiling * 0.35), 1))


def _optimal_assignment(roster_points: list[tuple[PlayerRef, float]]) -> list[tuple[str, int]]:
    """Greedy best legal lineup as an explicit (slot_label, player_index) list.

    One entry per fillable slot, so the result is always a *legal* lineup — at
    most one FLEX, at most the dedicated count per position. Greedy is exact for
    a single FLEX with disjoint dedicated positions.
    """
    remaining = sorted(range(len(roster_points)), key=lambda i: -roster_points[i][1])
    used: set[int] = set()
    assignment: list[tuple[str, int]] = []
    for slot in STARTER_SLOTS:
        eligible = FLEX_ELIGIBLE if slot == "FLEX" else {slot}
        for i in remaining:
            if i in used:
                continue
            if roster_points[i][0].position in eligible:
                used.add(i)
                assignment.append((slot, i))
                break
    return assignment


def generate_season(year: int, seed_offset: int = 0) -> SeasonBundle:
    rng = random.Random(year * 7919 + seed_offset)
    guids = _manager_guids()
    managers = [
        ManagerRef(guid=g, display_name=_manager_display_name(i, year)) for i, g in enumerate(guids)
    ]

    # Latent per-manager traits, stable across seasons AND processes. Seed from
    # the manager index (not hash(guid) — Python's string hash is salted per
    # process, which would silently break cross-run determinism).
    skill = {}
    coaching = {}
    for index, g in enumerate(guids):
        mrng = random.Random(1000 + index)
        skill[g] = 0.35 + 0.5 * mrng.random()
        coaching[g] = 0.80 + 0.18 * mrng.random()  # fraction of optimal they achieve

    players = _make_players(rng, year)

    # Snake draft: assign rosters. Draft order = shuffled teams.
    team_ids = list(range(1, NUM_TEAMS + 1))
    owner_by_team = {tid: guids[tid - 1] for tid in team_ids}
    draft_order = team_ids[:]
    rng.shuffle(draft_order)

    rosters: dict[int, list[PlayerRef]] = {tid: [] for tid in team_ids}
    draft_rows: list[DraftRow] = []
    pool = players[:]
    # Sort pool by an intrinsic quality so early picks are better (ADP realism).
    quality = {p.espn_player_id: rng.random() for p in pool}
    pool.sort(key=lambda p: -quality[p.espn_player_id])

    # Each team keeps a stable "franchise" star across every season (same id and
    # name), drafted as its round-1 keeper. This makes cross-season player
    # loyalty analytics meaningful on the fixture (real ESPN data has persistent
    # player identities; the synthetic pool otherwise regenerates each year).
    franchise = _franchise_players(team_ids)
    for star in franchise.values():
        quality[star.espn_player_id] = 0.92  # stars are elite

    overall = 0
    pool_iter = iter(pool)
    for rnd in range(1, ROSTER_SIZE + 1):
        order = draft_order if rnd % 2 == 1 else list(reversed(draft_order))
        for round_pick, tid in enumerate(order, start=1):
            if rnd == 1:
                player = franchise[tid]
                keeper = True
            else:
                player = next(pool_iter)
                keeper = False
            overall += 1
            rosters[tid].append(player)
            draft_rows.append(
                DraftRow(
                    overall_pick=overall,
                    round=rnd,
                    round_pick=round_pick,
                    team_espn_id=tid,
                    player=player,
                    is_keeper=keeper,
                )
            )

    # Per-team, per-week: generate player points, pick a (slightly suboptimal)
    # starting lineup, and derive the team's weekly score from started points.
    lineup_rows: list[LineupRow] = []
    weekly_scores: dict[int, dict[int, float]] = {tid: {} for tid in team_ids}

    for week in range(1, REG_WEEKS + 1):
        for tid in team_ids:
            g = owner_by_team[tid]
            roster = rosters[tid]
            pts = [
                (
                    p,
                    _weekly_points(
                        rng, p.position, min(1.0, quality[p.espn_player_id] * skill[g] * 1.6)
                    ),
                )
                for p in roster
            ]
            assignment = _optimal_assignment(pts)
            # Actual lineup: usually optimal, but with prob (1-coaching) one slot
            # is filled by a worse bench player eligible for THAT slot — a legal
            # suboptimal choice that creates real bench-points-lost.
            started_indices = {i for _, i in assignment}
            if assignment and rng.random() > coaching[g]:
                j = rng.randrange(len(assignment))
                slot_label, _cur = assignment[j]
                eligible = FLEX_ELIGIBLE if slot_label == "FLEX" else {slot_label}
                bench_candidates = [
                    i
                    for i in range(len(pts))
                    if i not in started_indices and pts[i][0].position in eligible
                ]
                if bench_candidates:
                    assignment[j] = (slot_label, rng.choice(bench_candidates))
                    started_indices = {i for _, i in assignment}

            team_score = round(sum(pts[i][1] for _, i in assignment), 1)
            weekly_scores[tid][week] = team_score

            slot_by_index = {i: slot for slot, i in assignment}
            for i, (player, point) in enumerate(pts):
                slot = slot_by_index.get(i, "BE")
                lineup_rows.append(
                    LineupRow(
                        team_espn_id=tid,
                        week=week,
                        player=player,
                        slot=slot,
                        points=point,
                        projected_points=round(point * rng.uniform(0.85, 1.15), 1),
                    )
                )

    # Round-robin schedule (circle method) over regular-season weeks.
    matchup_rows: list[MatchupRow] = []
    rotation = team_ids[:]
    for week in range(1, REG_WEEKS + 1):
        pairs = _round_pairs(rotation, week)
        for home, away in pairs:
            matchup_rows.append(
                MatchupRow(
                    week=week,
                    home_espn_id=home,
                    away_espn_id=away,
                    home_score=weekly_scores[home][week],
                    away_score=weekly_scores[away][week],
                    kind="REG",
                )
            )

    # Standings from regular-season W/L and points.
    records = _compute_records(team_ids, matchup_rows, weekly_scores)
    standings = sorted(team_ids, key=lambda t: (-records[t]["wins"], -records[t]["pf"]))
    playoff_cut = 6

    teams: list[TeamRow] = []
    name_rng = random.Random(year)
    for rank, tid in enumerate(standings, start=1):
        rec = records[tid]
        team_name = f"{name_rng.choice(_TEAM_NAME_WORDS)} {name_rng.choice(_TEAM_NAME_NOUNS)}"
        teams.append(
            TeamRow(
                espn_team_id=tid,
                team_name=team_name,
                owner_guids=[owner_by_team[tid]],
                abbrev=f"T{tid:02d}",
                wins=int(rec["wins"]),
                losses=int(rec["losses"]),
                ties=int(rec["ties"]),
                points_for=round(rec["pf"], 1),
                points_against=round(rec["pa"], 1),
                final_standing=rank,
                made_playoffs=rank <= playoff_cut,
            )
        )

    # A simple championship game between the top two seeds in the final week+1.
    champ_week = REG_WEEKS + 1
    top1, top2 = standings[0], standings[1]
    s1 = round(rng.gauss(115, 20), 1)
    s2 = round(rng.gauss(112, 20), 1)
    matchup_rows.append(
        MatchupRow(
            week=champ_week,
            home_espn_id=top1,
            away_espn_id=top2,
            home_score=s1,
            away_score=s2,
            kind="CHAMPIONSHIP",
        )
    )

    return SeasonBundle(
        year=year,
        scoring_settings={"format": "standard"},
        roster_slots={"starters": STARTER_SLOTS, "bench": BENCH_SIZE},
        regular_season_weeks=REG_WEEKS,
        playoff_team_count=playoff_cut,
        is_complete=True,
        lineups_available=True,
        managers=managers,
        teams=teams,
        draft=draft_rows,
        matchups=matchup_rows,
        lineups=lineup_rows,
    )


def _round_pairs(teams: list[int], week: int) -> list[tuple[int, int]]:
    """Circle-method round-robin pairing for a given week (1-indexed)."""
    n = len(teams)
    arr = teams[:]
    # Rotate all but the first element by (week-1) steps.
    fixed = arr[0]
    rest = arr[1:]
    shift = (week - 1) % len(rest)
    rest = rest[-shift:] + rest[:-shift] if shift else rest
    order = [fixed] + rest
    pairs = []
    for i in range(n // 2):
        pairs.append((order[i], order[n - 1 - i]))
    return pairs


def _compute_records(
    team_ids: list[int],
    matchups: list[MatchupRow],
    weekly_scores: dict[int, dict[int, float]],
) -> dict[int, dict[str, float]]:
    rec = {t: {"wins": 0, "losses": 0, "ties": 0, "pf": 0.0, "pa": 0.0} for t in team_ids}
    for m in matchups:
        if m.kind != "REG" or m.away_espn_id is None:
            continue
        h, a = m.home_espn_id, m.away_espn_id
        rec[h]["pf"] += m.home_score
        rec[h]["pa"] += m.away_score
        rec[a]["pf"] += m.away_score
        rec[a]["pa"] += m.home_score
        if m.home_score > m.away_score:
            rec[h]["wins"] += 1
            rec[a]["losses"] += 1
        elif m.home_score < m.away_score:
            rec[a]["wins"] += 1
            rec[h]["losses"] += 1
        else:
            rec[h]["ties"] += 1
            rec[a]["ties"] += 1
    return rec


def generate_league(years: list[int] | None = None) -> list[SeasonBundle]:
    return [generate_season(y) for y in (years or DEFAULT_SEASONS)]
