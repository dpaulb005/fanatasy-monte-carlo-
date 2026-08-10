"""Draft patterns & sequences: how each manager actually drafts.

Reconstructs every manager's pick-by-pick draft sequence (the "draft DNA")
and distills cross-season tendencies from it: opening-round signatures,
position timing (first QB/TE/K round), reach-vs-value habits against public
ADP, and how much value each draft returned. Purely descriptive, computed
from picks that already happened — see docs/METRICS_CATALOG.md.

Sign convention (matches ``analytics/drafts.py``): ``adp_delta = overall_pick
- adp``. Negative means the pick was made EARLIER than consensus (a reach);
positive means the player fell (value).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from league.analytics.drafts import DraftValueRow
from league.analytics.frames import LeagueFrames, normalize_position

# A pick this many slots ahead of ADP counts as a reach; this many behind as a
# value pick. ~half a round in a 10-team league; deliberately coarse.
ADP_SWING_THRESHOLD = 5.0

# Round phases used for position-share tendencies.
EARLY_ROUNDS = range(1, 4)  # 1-3: where identities are set
MID_ROUNDS = range(4, 9)  # 4-8: the builds diverge
# 9+: late rounds / fliers

OPENING_ROUNDS = 3  # length of the "opening signature" (e.g. RB-RB-WR)

# Consecutive same-position picks (across the whole board) that count as a
# positional run. 3 is the shortest streak that reads as one.
RUN_MIN_LENGTH = 3

# A drafted player this many points above/below expectation marks the manager
# as loyal to / burned by them (projection delta when available, PoR fallback).
AFFINITY_THRESHOLD = 35.0
AFFINITY_TOP_N = 5

SIGNATURE_POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")


@dataclass
class _PickRow:
    year: int
    round: int
    round_pick: int
    overall_pick: int
    position: str
    player_name: str
    espn_player_id: int
    is_keeper: bool
    adp_delta: float | None
    points_over_replacement: float
    season_points: float
    projected_points: float | None = None


def _phase(round_number: int) -> str:
    if round_number in EARLY_ROUNDS:
        return "early"
    if round_number in MID_ROUNDS:
        return "mid"
    return "late"


def _manager_picks(
    frames: LeagueFrames,
    values_by_pick: dict[int, DraftValueRow],
    proj_lookup: dict[tuple[int, int], float] | None = None,
) -> dict[int, dict[int, list[_PickRow]]]:
    """manager_id -> year -> picks in draft order. Co-managers each get the draft."""
    proj_lookup = proj_lookup or {}
    out: dict[int, dict[int, list[_PickRow]]] = defaultdict(lambda: defaultdict(list))
    for pick in frames.draft_picks:
        tsf = frames.team_seasons.get(pick.team_season_id)
        if tsf is None:
            continue
        year = pick.season.year
        pid = pick.player.espn_player_id
        position = frames.player_position_by_year.get(year, {}).get(
            pid, normalize_position(pick.player.position)
        )
        value = values_by_pick.get(pick.id)
        row = _PickRow(
            year=year,
            round=pick.round,
            round_pick=pick.round_pick,
            overall_pick=pick.overall_pick,
            position=position or "?",
            player_name=pick.player.name,
            espn_player_id=pid,
            is_keeper=pick.is_keeper,
            adp_delta=value.adp_delta if value else None,
            points_over_replacement=value.points_over_replacement if value else 0.0,
            season_points=value.season_points if value else 0.0,
            projected_points=proj_lookup.get((year, pid)),
        )
        for manager_id in tsf.manager_ids:
            out[manager_id][year].append(row)
    for by_year in out.values():
        for picks in by_year.values():
            picks.sort(key=lambda p: p.overall_pick)
    return out


def _profile(drafts: dict[int, list[_PickRow]]) -> dict:
    """Cross-season tendency profile from one manager's drafts."""
    # Opening signature: positions of the first OPENING_ROUNDS picks the
    # manager actually made. Keepers excluded — a kept player says nothing
    # about how the manager drafts — so in keeper years the signature starts
    # at their first live pick.
    signatures: Counter[str] = Counter()
    first_round_by_pos: dict[str, list[int]] = defaultdict(list)
    phase_counts: dict[str, Counter[str]] = {
        "early": Counter(),
        "mid": Counter(),
        "late": Counter(),
    }
    adp_deltas: list[float] = []
    reaches = values = 0
    draft_por: list[float] = []
    total_picks = 0
    proj_deltas: list[float] = []
    proj_beats = 0

    for picks in drafts.values():
        drafted = [p for p in picks if not p.is_keeper]
        opening = [p.position for p in drafted[:OPENING_ROUNDS]]
        if len(opening) == OPENING_ROUNDS:
            signatures["-".join(opening)] += 1
        seen: set[str] = set()
        for p in drafted:
            total_picks += 1
            phase_counts[_phase(p.round)][p.position] += 1
            if p.position in SIGNATURE_POSITIONS and p.position not in seen:
                seen.add(p.position)
                first_round_by_pos[p.position].append(p.round)
            if p.adp_delta is not None:
                adp_deltas.append(p.adp_delta)
                if p.adp_delta <= -ADP_SWING_THRESHOLD:
                    reaches += 1
                elif p.adp_delta >= ADP_SWING_THRESHOLD:
                    values += 1
            if p.projected_points is not None:
                proj_deltas.append(p.season_points - p.projected_points)
                if p.season_points >= p.projected_points:
                    proj_beats += 1
        draft_por.append(sum(p.points_over_replacement for p in picks))

    # Manager-player affinity: who burned them, who won them a title. The
    # signal is actual − projected when a projection exists (scale-honest),
    # else points-over-replacement (older seasons). One entry per player,
    # averaged across the times this manager drafted them.
    pool: dict[str, dict] = {}
    for picks in drafts.values():
        for p in picks:
            if p.is_keeper:
                continue
            if p.projected_points is not None:
                signal = p.season_points - p.projected_points
            else:
                signal = p.points_over_replacement
            entry = pool.setdefault(
                p.player_name,
                {"player_name": p.player_name, "total": 0.0, "n": 0, "last_year": p.year},
            )
            entry["total"] += signal
            entry["n"] += 1
            entry["last_year"] = max(entry["last_year"], p.year)
    scored = [
        {
            "player_name": e["player_name"],
            "delta": round(e["total"] / e["n"], 1),
            "times_drafted": e["n"],
            "last_year": e["last_year"],
        }
        for e in pool.values()
    ]
    burned = sorted(
        (e for e in scored if e["delta"] <= -AFFINITY_THRESHOLD), key=lambda e: e["delta"]
    )[:AFFINITY_TOP_N]
    loyal = sorted(
        (e for e in scored if e["delta"] >= AFFINITY_THRESHOLD),
        key=lambda e: -e["delta"],
    )[:AFFINITY_TOP_N]

    top_signature, top_count = ("", 0)
    if signatures:
        top_signature, top_count = signatures.most_common(1)[0]

    def shares(counter: Counter[str]) -> dict[str, float]:
        total = sum(counter.values())
        if not total:
            return {}
        return {pos: round(n / total, 3) for pos, n in sorted(counter.items())}

    return {
        "opening": {
            "signature": top_signature,
            "count": top_count,
            "drafts": len(drafts),
            "all": [{"signature": s, "count": c} for s, c in signatures.most_common()],
        },
        "position_shares": {phase: shares(c) for phase, c in phase_counts.items()},
        "avg_first_round": {
            pos: round(sum(rounds) / len(rounds), 1)
            for pos, rounds in sorted(first_round_by_pos.items())
        },
        "avg_adp_delta": round(sum(adp_deltas) / len(adp_deltas), 2) if adp_deltas else None,
        "reach_rate": round(reaches / len(adp_deltas), 3) if adp_deltas else None,
        "value_rate": round(values / len(adp_deltas), 3) if adp_deltas else None,
        "adp_picks": len(adp_deltas),
        "total_picks": total_picks,
        "avg_draft_por": round(sum(draft_por) / len(draft_por), 1) if draft_por else 0.0,
        "affinity": {"burned": burned, "loyal": loyal},
        # How drafted players did against their draft-time projections.
        "projection": {
            "picks": len(proj_deltas),
            "beat_rate": round(proj_beats / len(proj_deltas), 3) if proj_deltas else None,
            "avg_delta": round(sum(proj_deltas) / len(proj_deltas), 1) if proj_deltas else None,
        },
    }


def _position_runs(
    frames: LeagueFrames, values_by_pick: dict[int, DraftValueRow]
) -> tuple[list[dict], dict[int, dict[str, int]]]:
    """Positional runs on the draft board, and per-manager run behavior.

    A run is >= RUN_MIN_LENGTH consecutive same-position picks in overall
    order. The first pick starts the run; later picks joined it, and a join
    that was also a reach (adp_delta <= -threshold) counts as a panic join —
    the manager chased the run ahead of the market's price.
    """
    by_year: dict[int, list] = defaultdict(list)
    for pick in frames.draft_picks:
        by_year[pick.season.year].append(pick)

    def pos_of(pick) -> str:
        return frames.player_position_by_year.get(pick.season.year, {}).get(
            pick.player.espn_player_id, normalize_position(pick.player.position)
        )

    runs: list[dict] = []
    behavior: dict[int, dict[str, int]] = defaultdict(
        lambda: {"started": 0, "joined": 0, "panic_joins": 0}
    )
    for year, picks in sorted(by_year.items()):
        picks.sort(key=lambda p: p.overall_pick)
        i = 0
        while i < len(picks):
            j = i
            while j + 1 < len(picks) and pos_of(picks[j + 1]) == pos_of(picks[i]):
                j += 1
            length = j - i + 1
            if length >= RUN_MIN_LENGTH:
                run_picks = picks[i : j + 1]
                entries = []
                for idx, pick in enumerate(run_picks):
                    tsf = frames.team_seasons.get(pick.team_season_id)
                    value = values_by_pick.get(pick.id)
                    adp_delta = value.adp_delta if value else None
                    panic = idx > 0 and adp_delta is not None and adp_delta <= -ADP_SWING_THRESHOLD
                    for manager_id in tsf.manager_ids if tsf else []:
                        if idx == 0:
                            behavior[manager_id]["started"] += 1
                        else:
                            behavior[manager_id]["joined"] += 1
                            if panic:
                                behavior[manager_id]["panic_joins"] += 1
                    entries.append(
                        {
                            "overall_pick": pick.overall_pick,
                            "player_name": pick.player.name,
                            "manager": (" / ".join(tsf.manager_labels.values()) if tsf else "?"),
                            "panic": panic,
                        }
                    )
                runs.append(
                    {
                        "year": year,
                        "position": pos_of(picks[i]),
                        "start_pick": picks[i].overall_pick,
                        "length": length,
                        "picks": entries,
                    }
                )
            i = j + 1
    runs.sort(key=lambda r: (-r["length"], r["year"], r["start_pick"]))
    return runs, dict(behavior)


def compute_draft_patterns(
    frames: LeagueFrames,
    draft_values: list[DraftValueRow],
    projections: list | None = None,
    projection_scale: str = "pts_ppr",
) -> dict:
    """The draft-patterns blob: per-manager sequences + tendency profiles."""
    values_by_pick = {v.draft_pick_id: v for v in draft_values}

    # (season, espn_id) -> projected points on the detected scale; real
    # sources beat "synthetic" when both cover a season.
    proj_lookup: dict[tuple[int, int], float] = {}
    proj_source: dict[tuple[int, int], str] = {}
    for proj in projections or []:
        if proj.week != 0 or proj.espn_player_id is None:
            continue
        projected = getattr(proj, projection_scale, None)
        if projected is None:
            continue
        key = (proj.season, proj.espn_player_id)
        if key in proj_lookup and proj_source[key] != "synthetic":
            continue
        proj_lookup[key] = projected
        proj_source[key] = proj.source

    by_manager = _manager_picks(frames, values_by_pick, proj_lookup)
    runs, run_behavior = _position_runs(frames, values_by_pick)

    labels: dict[int, str] = {}
    for tsf in frames.team_seasons.values():
        labels.update(tsf.manager_labels)

    rounds = max((p.round for p in frames.draft_picks), default=0)

    managers: list[dict] = []
    for manager_id, drafts in by_manager.items():
        profile = _profile(drafts)
        profile["runs"] = run_behavior.get(
            manager_id, {"started": 0, "joined": 0, "panic_joins": 0}
        )
        managers.append(
            {
                "manager": {"id": manager_id, "label": labels.get(manager_id, "?")},
                "profile": profile,
                "drafts": [
                    {
                        "year": year,
                        "slot": picks[0].round_pick if picks else 0,
                        "draft_por": round(sum(p.points_over_replacement for p in picks), 1),
                        "picks": [
                            {
                                "round": p.round,
                                "overall_pick": p.overall_pick,
                                "position": p.position,
                                "player_name": p.player_name,
                                "is_keeper": p.is_keeper,
                                "adp_delta": p.adp_delta,
                                "points_over_replacement": p.points_over_replacement,
                                "season_points": p.season_points,
                            }
                            for p in picks
                        ],
                    }
                    for year, picks in sorted(drafts.items())
                ],
            }
        )
    managers.sort(key=lambda m: str(m["manager"]["label"]).lower())

    # League-wide projection steals/busts: drafted players vs their draft-time
    # projection (keepers excluded — nobody "drafted" them).
    events: list[dict] = []
    for pick in frames.draft_picks:
        if pick.is_keeper:
            continue
        value = values_by_pick.get(pick.id)
        year = pick.season.year
        pid = pick.player.espn_player_id
        projected = proj_lookup.get((year, pid))
        if value is None or projected is None:
            continue
        ts_frame = frames.team_seasons.get(pick.team_season_id)
        events.append(
            {
                "year": year,
                "player_name": pick.player.name,
                "position": frames.player_position_by_year.get(year, {}).get(
                    pid, normalize_position(pick.player.position)
                ),
                "round": pick.round,
                "manager": " / ".join(ts_frame.manager_labels.values()) if ts_frame else "?",
                "projected": round(projected, 1),
                "actual": round(value.season_points, 1),
                "delta": round(value.season_points - projected, 1),
            }
        )
    events.sort(key=lambda e: e["delta"], reverse=True)

    return {
        "seasons": sorted({p.season.year for p in frames.draft_picks}),
        "rounds": rounds,
        "adp_swing_threshold": ADP_SWING_THRESHOLD,
        "managers": managers,
        "projection": {
            "scale": projection_scale if proj_lookup else None,
            "matched_picks": len(events),
            "steals": events[:10],
            "busts": sorted(events[-10:], key=lambda e: e["delta"])[:10] if events else [],
        },
        "position_runs": {
            "min_length": RUN_MIN_LENGTH,
            "total": len(runs),
            "longest": runs[:10],
        },
    }
