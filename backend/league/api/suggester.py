"""Draft suggester: latest synced ADP ranked through this league's priors.

For a given overall pick, every ADP-listed player gets a league-adjusted
expected draft slot (ADP + positional bias), an 80% confidence interval on
that slot (sigma from the league's own historical pick-vs-ADP residuals,
normal model), availability probabilities now and at the user's next snake
pick, and the league-historical value band (points-over-replacement
quantiles) for their position in the current round.

Honesty contract (ADR-012): the ranking is market order recalibrated to this
league — it knows nothing about player skill beyond ADP and shows last
season's realized value only as context.
"""

from __future__ import annotations

import math
from functools import lru_cache

from django.db.models import Max
from django.http import Http404
from rest_framework.exceptions import ValidationError

from league.analytics.draft_patterns import _phase
from league.analytics.drafts import normalize_player_name
from league.models import (
    ExpertRanking,
    PlayerADP,
    PlayerProjection,
    PlayerSeasonValue,
    SeasonTrend,
    SimulationSnapshot,
)

# FFC position labels that differ from the league's canonical ones.
_FFC_POSITIONS = {"PK": "K", "DEF": "DST"}

Z80 = 1.2816  # 80% two-sided normal interval

# Absolute floor on per-player draft-slot sigma (picks).
MIN_PLAYER_SIGMA = 1.5

# Candidates whose availability at the requested pick is below this are gone
# for practical purposes and excluded from the board.
MIN_AVAILABILITY = 0.05

DEFAULT_LIMIT = 50


def _survival(x: float) -> float:
    """P(Z >= x) for standard normal."""
    return 0.5 * math.erfc(x / math.sqrt(2))


def snake_picks(teams: int, slot: int, rounds: int) -> list[int]:
    """All overall picks belonging to a draft slot in a snake draft."""
    picks = []
    for rnd in range(1, rounds + 1):
        in_round = slot if rnd % 2 == 1 else teams + 1 - slot
        picks.append((rnd - 1) * teams + in_round)
    return picks


def _priors() -> dict:
    row = SeasonTrend.objects.filter(season__isnull=True, key="draft_priors").first()
    if row is None:
        raise Http404("Draft priors not computed yet — run compute_analytics.")
    return row.data


def _calibration_for(priors: dict, position: str) -> dict:
    cal = priors.get("adp_calibration") or {}
    by_pos = cal.get("by_position") or {}
    overall = cal.get("overall") or {"bias": 0.0, "sigma": 10.0, "n": 0}
    return by_pos.get(position, overall)


def _value_band(priors: dict, position: str, round_number: int) -> dict | None:
    by_round = (priors.get("value_bands") or {}).get(position) or {}
    band = by_round.get(str(round_number))
    if band:
        return band
    by_phase = (priors.get("phase_bands") or {}).get(position) or {}
    return by_phase.get(_phase(round_number))


def _latest_projections() -> tuple[int | None, dict[str, PlayerProjection]]:
    """normalized player name -> latest season-long projection row."""
    season = PlayerProjection.objects.filter(week=0).aggregate(m=Max("season"))["m"]
    if season is None:
        return None, {}
    rows = PlayerProjection.objects.filter(week=0, season=season)
    return season, {normalize_player_name(r.player_name): r for r in rows}


def _expert_lookup() -> tuple[int | None, dict[str, dict]]:
    """normalized name -> merged expert-sheet data from the latest season.

    Overall rank / letter tier / consensus ADP come from ranking sheets
    (flock-style); risk / upside / numeric position tier from grade sheets
    (bigga-style)."""
    season = ExpertRanking.objects.aggregate(m=Max("season"))["m"]
    if season is None:
        return None, {}
    experts: dict[str, dict] = {}
    for row in ExpertRanking.objects.filter(season=season):
        e = experts.setdefault(normalize_player_name(row.player_name), {})
        if row.rank_overall is not None:
            e["expert_rank"] = row.rank_overall
            e["tier"] = row.tier or e.get("tier")
            e["consensus_adp"] = row.adp_overall
        if row.risk is not None:
            e["risk"] = row.risk
            e["upside"] = row.upside
    return season, experts


def _league_history_lookup() -> dict[str, dict]:
    """normalized name -> {burned: [manager labels], loyal: [...]} from the
    patterns blob — who in this league got burned by / fell in love with the
    player. Managers avoid re-drafting their busts and chase their guys."""
    row = SeasonTrend.objects.filter(season__isnull=True, key="draft_patterns").first()
    if row is None:
        return {}
    lookup: dict[str, dict] = {}
    for entry in row.data.get("managers", []):
        label = entry.get("manager", {}).get("label", "?")
        affinity = entry.get("profile", {}).get("affinity") or {}
        for kind in ("burned", "loyal"):
            for item in affinity.get(kind, []):
                key = normalize_player_name(item["player_name"])
                lookup.setdefault(key, {"burned": [], "loyal": []})[kind].append(label)
    return lookup


def _last_season_values() -> tuple[int | None, dict[str, dict]]:
    """normalized player name -> last completed season's realized value."""
    year = PlayerSeasonValue.objects.aggregate(m=Max("season__year"))["m"]
    if year is None:
        return None, {}
    values = {}
    rows = PlayerSeasonValue.objects.filter(season__year=year).select_related("player")
    for row in rows:
        values[normalize_player_name(row.player.name)] = {
            "points_over_replacement": round(row.points_over_replacement, 1),
            "position_rank": row.position_rank,
        }
    return year, values


def _league_average_shares() -> dict[str, dict[str, float]]:
    """phase -> position -> share, averaged over the league's managers."""
    row = SeasonTrend.objects.filter(season__isnull=True, key="draft_patterns").first()
    if row is None:
        return {}
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for entry in row.data.get("managers", []):
        for phase, shares in (entry.get("profile", {}).get("position_shares") or {}).items():
            bucket = sums.setdefault(phase, {})
            for pos, share in shares.items():
                bucket[pos] = bucket.get(pos, 0.0) + share
            counts[phase] = counts.get(phase, 0) + 1
    return {
        phase: {pos: total / counts[phase] for pos, total in bucket.items()}
        for phase, bucket in sums.items()
    }


@lru_cache(maxsize=8)
def _compiled_simulation(snapshot_id: int, checksum: str) -> tuple[dict, dict]:
    """Compile the large immutable JSON payload once per web process/version."""
    payload = SimulationSnapshot.objects.only("payload").get(pk=snapshot_id).payload
    players = {
        normalize_player_name(row["player"]): row for row in payload.get("players", [])
    }
    pairs = {
        frozenset((normalize_player_name(pair["a"]), normalize_player_name(pair["b"]))): pair
        for pair in payload.get("pairs", [])
    }
    return players, pairs


def _simulation_context(teams: int, roster: list[str] | None) -> tuple[dict | None, dict]:
    """Latest matching nflsim snapshot and normalized per-player enrichments."""
    snapshot = (
        SimulationSnapshot.objects.filter(league_teams=teams)
        .only("id", "checksum", "season", "simulations", "scoring", "generated_at")
        .order_by("-season", "-generated_at")
        .first()
    )
    if snapshot is None:
        return None, {}

    player_lookup, pair_lookup = _compiled_simulation(snapshot.id, snapshot.checksum)
    roster_names = [normalize_player_name(name) for name in (roster or []) if name]

    def value(row: dict, key: str, digits: int = 3):
        item = row.get(key)
        return round(item, digits) if isinstance(item, (int, float)) else None

    enriched = {}
    for normalized, row in player_lookup.items():
        roster_pairs = []
        for roster_name in roster_names:
            pair = pair_lookup.get(frozenset((normalized, roster_name)))
            if pair:
                roster_pairs.append({
                    "player": (
                        pair["b"]
                        if normalize_player_name(pair["a"]) == normalized
                        else pair["a"]
                    ),
                    "correlation": value(pair, "corr"),
                    "tail_lift": value(pair, "lift"),
                    "p_both_boom": value(pair, "p_both_boom"),
                })
        correlations = [p["correlation"] for p in roster_pairs if p["correlation"] is not None]
        lifts = [p["tail_lift"] for p in roster_pairs if p["tail_lift"] is not None]
        enriched[normalized] = {
            "points": value(row, "points", 1),
            "range": [value(row, "p10", 1), value(row, "p90", 1)],
            "vor": value(row, "vor_sim", 1),
            "vor_range": [value(row, "vor_sim_p10", 1), value(row, "vor_sim_p90", 1)],
            "p_position_1": value(row, "p_pos1"),
            "p_top_3": value(row, "p_top3"),
            "p_starter": value(row, "p_starter"),
            "contingent_gain": value(row, "contingent_gain", 1),
            "behind": row.get("behind"),
            "ceiling_volume_ratio": value(row, "volume_ratio", 2),
            "ceiling_td_dependence": value(row, "td_dependence", 2),
            "playoff_delta": value(row, "playoff_delta", 1),
            "roster_fit": ({
                "average_correlation": round(sum(correlations) / len(correlations), 3)
                if correlations else None,
                "average_tail_lift": round(sum(lifts) / len(lifts), 3) if lifts else None,
                "pairs": roster_pairs,
            } if roster_pairs else None),
        }

    metadata = {
        "season": snapshot.season,
        "simulations": snapshot.simulations,
        "scoring": snapshot.scoring,
        "generated_at": snapshot.generated_at.isoformat(),
        "weekly_capture": any(
            row.get("playoff_delta") is not None for row in player_lookup.values()
        ),
        "snapshot_players": len(enriched),
    }
    return metadata, enriched


def draft_suggestions(
    pick: int,
    teams: int | None = None,
    slot: int | None = None,
    position: str | None = None,
    limit: int = DEFAULT_LIMIT,
    simulate: bool = False,
    roster: list[str] | None = None,
) -> dict:
    priors = _priors()

    adp_season = PlayerADP.objects.aggregate(m=Max("season"))["m"]
    if adp_season is None:
        raise Http404("No ADP synced yet — run sync_nfl_context.")

    rounds = priors.get("rounds") or 15
    teams = teams or priors.get("team_count_recent") or 12
    if pick < 1:
        raise ValidationError({"pick": "must be >= 1"})
    if teams < 2:
        raise ValidationError({"teams": "must be >= 2"})
    if slot is not None and not 1 <= slot <= teams:
        raise ValidationError({"slot": f"must be between 1 and {teams}"})

    round_at_pick = min(math.ceil(pick / teams), max(rounds, 1))
    next_pick = None
    if slot is not None:
        upcoming = [p for p in snake_picks(teams, slot, rounds) if p > pick]
        next_pick = upcoming[0] if upcoming else None

    value_year, last_values = _last_season_values()
    proj_season, proj_by_name = _latest_projections()
    proj_error = priors.get("projection_error") or None
    proj_scale = proj_error["scale"] if proj_error else "pts_ppr"
    expert_season, experts = _expert_lookup()
    history = _league_history_lookup()
    simulation_model, simulated = _simulation_context(teams, roster)

    # The Gap: expected number of players per position drafted between the
    # current pick and the user's next one (sum of per-player availability
    # drops), plus tier survival — P(any current-tier player at a position is
    # still there next turn), independence-approximated.
    gap_taken: dict[str, float] = {}
    tier_pool: dict[str, dict] = {}

    players = []
    adp_rows = PlayerADP.objects.filter(season=adp_season).order_by("adp")
    for row in adp_rows:
        pos = _FFC_POSITIONS.get(row.position, row.position)
        cal = _calibration_for(priors, pos)
        mu = max(1.0, row.adp + cal["bias"])
        # Per-player sigma: ADP scatter grows with draft depth (verified
        # against FFC's published stdev: sigma ≈ 0.359 * ADP^0.715, R²=0.84).
        # A flat per-position sigma is ~2x too wide in round 1 and far too
        # narrow late. Blend the depth curve with the league's positional
        # residual spread, floored at the global minimum.
        sigma = max(MIN_PLAYER_SIGMA, 0.359 * (row.adp**0.715), cal["sigma"] * 0.35)
        # At pick 1 the board is untouched — the continuous model doesn't know
        # that, so clamp. Elsewhere the normal survival is the estimate.
        p_now = 1.0 if pick <= 1 else _survival((pick - mu) / sigma)
        if p_now < MIN_AVAILABILITY:
            continue
        p_next = _survival((next_pick - mu) / sigma) if next_pick is not None else None

        norm_name = normalize_player_name(row.player_name)
        expert = experts.get(norm_name, {})

        # Gap accounting runs over EVERY live candidate, before any position
        # filter — the forecast describes the whole board.
        if p_next is not None:
            gap_taken[pos] = gap_taken.get(pos, 0.0) + max(0.0, p_now - p_next)
            tier = expert.get("tier")
            if tier and p_now >= 0.5:
                pool = tier_pool.setdefault(pos, {"tier": tier, "p_all_gone": 1.0, "n": 0})
                if tier == pool["tier"]:
                    pool["p_all_gone"] *= 1.0 - p_next
                    pool["n"] += 1
                elif tier < pool["tier"]:  # letters: earlier tier outranks
                    tier_pool[pos] = {"tier": tier, "p_all_gone": 1.0 - p_next, "n": 1}

        if position and pos != position:
            continue

        # Projected points with an empirical CI: the league's historical
        # projection-error quantiles (actual − projected) added onto this
        # player's projection. p10..p90 of the residuals ≈ an 80% interval.
        projection = proj_by_name.get(norm_name)
        projected_points = getattr(projection, proj_scale, None) if projection else None
        projected_range = None
        if projected_points is not None and proj_error:
            err = proj_error["by_position"].get(pos) or proj_error["overall"]
            projected_range = [
                round(projected_points + err["p10"], 1),
                round(projected_points + err["p90"], 1),
            ]
        players.append(
            {
                "player_name": row.player_name,
                "position": pos,
                "adp": round(row.adp, 1),
                "expected_pick": round(mu, 1),
                "ci80": [max(1.0, round(mu - Z80 * sigma, 1)), round(mu + Z80 * sigma, 1)],
                "p_available_now": round(p_now, 3),
                "p_available_next": round(p_next, 3) if p_next is not None else None,
                "value_band": _value_band(priors, pos, round_at_pick),
                "projected_points": projected_points,
                "projected_range": projected_range,
                "expert": {
                    "rank": expert.get("expert_rank"),
                    "tier": expert.get("tier"),
                    "risk": expert.get("risk"),
                    "upside": expert.get("upside"),
                    # Positive edge: experts rank him ahead of where the
                    # market drafts him — a value the room may miss.
                    "edge": (
                        round(row.adp - expert["expert_rank"], 1)
                        if expert.get("expert_rank")
                        else None
                    ),
                }
                if expert
                else None,
                "league_history": history.get(norm_name),
                "last_season": last_values.get(norm_name),
                "monte_carlo": simulated.get(norm_name),
            }
        )

    if simulation_model is not None:
        simulation_model = {
            **simulation_model,
            "board_matches": sum(player["monte_carlo"] is not None for player in players),
        }

    # Board order is the league-adjusted market, not raw ADP — positional bias
    # can reorder neighbors.
    players.sort(key=lambda p: p["expected_pick"])
    full_board = players
    players = players[:limit]

    # Monte Carlo pass (MC-1): simulate the picks between now and the user's
    # next turn with league-tendency-weighted opponents; replaces the
    # independence assumption with an actual exactly-N-players-leave model.
    simulation = None
    if simulate and next_pick is not None and next_pick > pick:
        from league.api.draft_sim import simulate_draft

        board = [
            {
                "name": p["player_name"],
                "position": p["position"],
                "mu": p["expected_pick"],
                "projected_points": p["projected_points"],
            }
            for p in full_board
        ]
        shares = _league_average_shares()
        result = simulate_draft(
            board,
            pick=pick,
            next_pick=next_pick,
            teams=teams,
            slot=slot or 1,
            slot_profiles={s: {"shares": shares} for s in range(1, teams + 1)},
        )
        survival = result.pop("survival")
        for p in players:
            p["mc_survival_next"] = survival.get(p["player_name"])
        simulation = result

    gap_forecast = None
    if next_pick is not None:
        gap_forecast = {
            "expected_taken": {p: round(v, 1) for p, v in sorted(gap_taken.items())},
            "tier_survival": {
                p: {
                    "tier": pool["tier"],
                    "p_any_next": round(1.0 - pool["p_all_gone"], 3),
                    "players_left": pool["n"],
                }
                for p, pool in sorted(tier_pool.items())
            },
        }

    return {
        "adp_season": adp_season,
        "value_season": value_year,
        "projection_season": proj_season,
        "projection_scale": proj_scale if proj_season is not None else None,
        "projection_error": proj_error,
        "expert_season": expert_season,
        "gap_forecast": gap_forecast,
        "simulation": simulation,
        "simulation_model": simulation_model,
        "pick": pick,
        "round": round_at_pick,
        "teams": teams,
        "slot": slot,
        "next_pick": next_pick,
        "rounds": rounds,
        "calibration": priors.get("adp_calibration"),
        "players": players,
    }
