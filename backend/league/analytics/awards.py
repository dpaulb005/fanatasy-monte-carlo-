"""Fun awards and superlatives — derived from real data, every one explainable.

Each award emits an Award-shaped dict with a ``context`` carrying the matchup /
pick / week behind it, so the UI can cite the numbers. Adding an award = one
function here + one card in the frontend; no schema change.
See docs/METRICS_CATALOG.md (Fun / funny stats).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from league.analytics.drafts import DraftValueRow
from league.analytics.frames import LeagueFrames


@dataclass
class AwardRow:
    season_year: int | None
    slug: str
    title: str
    winner_manager_id: int | None
    value: float
    context: dict


def _first_manager(frames: LeagueFrames, team_season_id: int) -> int | None:
    tsf = frames.team_seasons.get(team_season_id)
    if tsf and tsf.manager_ids:
        return tsf.manager_ids[0]
    return None


def _season_awards(
    frames: LeagueFrames,
    year: int,
    season_rows: list[dict],
    draft_values: list[DraftValueRow],
) -> list[AwardRow]:
    awards: list[AwardRow] = []
    rows = [r for r in season_rows if r["season_year"] == year]
    if not rows:
        return awards
    team_count = frames.team_count_by_year.get(year, 0)

    # Heartbreak of the Year: highest score in a losing week.
    # Daylight Robbery: lowest score in a winning week.
    best_loss = None
    worst_win = None
    for tw in frames.team_weeks:
        if tw.season_year != year:
            continue
        if tw.lost and (best_loss is None or tw.score > best_loss.score):
            best_loss = tw
        if tw.won and (worst_win is None or tw.score < worst_win.score):
            worst_win = tw
    if best_loss:
        awards.append(
            AwardRow(
                year,
                "heartbreak",
                "Heartbreak of the Year",
                _first_manager(frames, best_loss.team_season_id),
                round(best_loss.score, 1),
                {
                    "week": best_loss.week,
                    "score": best_loss.score,
                    "opponent_score": best_loss.opponent_score,
                },
            )
        )
    if worst_win:
        awards.append(
            AwardRow(
                year,
                "daylight_robbery",
                "Daylight Robbery",
                _first_manager(frames, worst_win.team_season_id),
                round(worst_win.score, 1),
                {
                    "week": worst_win.week,
                    "score": worst_win.score,
                    "opponent_score": worst_win.opponent_score,
                },
            )
        )

    # Benchwarmer of the Year: most points left on the bench.
    bench = max(rows, key=lambda r: r["bench_points_lost"])
    awards.append(
        AwardRow(
            year,
            "benchwarmer",
            "Benchwarmer of the Year",
            bench["manager_id"],
            round(bench["bench_points_lost"], 1),
            {"bench_points_lost": bench["bench_points_lost"]},
        )
    )

    # Left It on the Bench: most losses that a legal alternate lineup from the
    # same week's roster would have won. Requires at least one such loss.
    thrown = max(rows, key=lambda r: r.get("bench_losses", 0))
    if thrown.get("bench_losses", 0) > 0:
        awards.append(
            AwardRow(
                year,
                "bench_losses",
                "Left It on the Bench",
                thrown["manager_id"],
                float(thrown["bench_losses"]),
                {
                    "bench_losses": thrown["bench_losses"],
                    "weeks": thrown.get("bench_loss_weeks", []),
                    "definition": (
                        "Losses where a legal lineup already on the roster "
                        "would have beaten the opponent's actual score."
                    ),
                },
            )
        )

    # Glass Cannon: most volatile weekly scoring.
    cannon = max(rows, key=lambda r: r["weekly_score_stddev"])
    awards.append(
        AwardRow(
            year,
            "glass_cannon",
            "Glass Cannon",
            cannon["manager_id"],
            round(cannon["weekly_score_stddev"], 1),
            {"weekly_score_stddev": cannon["weekly_score_stddev"]},
        )
    )

    # The Sacko: last place.
    if team_count:
        sacko = [r for r in rows if r["final_standing"] == team_count]
        if sacko:
            awards.append(
                AwardRow(
                    year,
                    "sacko",
                    "The Sacko",
                    sacko[0]["manager_id"],
                    float(team_count),
                    {"final_standing": team_count},
                )
            )

    # Paper Champion: best expected wins that did NOT win the title.
    non_champs = [r for r in rows if r["final_standing"] != 1]
    if non_champs:
        paper = max(non_champs, key=lambda r: r["expected_wins"])
        awards.append(
            AwardRow(
                year,
                "paper_champion",
                "Paper Champion",
                paper["manager_id"],
                round(paper["expected_wins"], 1),
                {
                    "expected_wins": paper["expected_wins"],
                    "final_standing": paper["final_standing"],
                },
            )
        )

    # Luckiest Playoff Berth: made playoffs with the largest positive luck.
    berths = [r for r in rows if r["made_playoffs"]]
    if berths:
        lucky = max(berths, key=lambda r: r["luck_delta"])
        if lucky["luck_delta"] > 0:
            awards.append(
                AwardRow(
                    year,
                    "luckiest_berth",
                    "Luckiest Playoff Berth",
                    lucky["manager_id"],
                    round(lucky["luck_delta"], 2),
                    {"luck_delta": lucky["luck_delta"]},
                )
            )

    # Draft Whisperer: most total points-over-replacement drafted this season.
    pick_meta = {
        p.id: (p.season.year, _first_manager(frames, p.team_season_id), p.round)
        for p in frames.draft_picks
    }
    por_by_manager: dict[int, float] = defaultdict(float)
    for dv in draft_values:
        meta = pick_meta.get(dv.draft_pick_id)
        if meta and meta[0] == year and meta[1] is not None:
            por_by_manager[meta[1]] += dv.points_over_replacement
    if por_by_manager:
        whisperer_id = max(por_by_manager, key=lambda m: por_by_manager[m])
        awards.append(
            AwardRow(
                year,
                "draft_whisperer",
                "Draft Whisperer",
                whisperer_id,
                round(por_by_manager[whisperer_id], 1),
                {"points_over_replacement": round(por_by_manager[whisperer_id], 1)},
            )
        )

    # Cursed Pick: worst early-round (1-3) outcome vs the round median.
    early = [
        (dv, pick_meta.get(dv.draft_pick_id))
        for dv in draft_values
        if pick_meta.get(dv.draft_pick_id)
        and pick_meta[dv.draft_pick_id][0] == year
        and pick_meta[dv.draft_pick_id][2] <= 3
    ]
    if early:
        worst_dv, meta = min(early, key=lambda t: t[0].round_expectation_delta)
        awards.append(
            AwardRow(
                year,
                "cursed_pick",
                "Cursed Pick",
                meta[1] if meta else None,
                round(worst_dv.round_expectation_delta, 1),
                {
                    "round": meta[2] if meta else None,
                    "round_expectation_delta": worst_dv.round_expectation_delta,
                },
            )
        )

    return awards


def _all_time_awards(frames: LeagueFrames) -> list[AwardRow]:
    # Most Loyal: the (manager, player) pair that recurs across the most seasons.
    seen: dict[tuple[int, str], set[int]] = defaultdict(set)
    for pick in frames.draft_picks:
        mgr = _first_manager(frames, pick.team_season_id)
        if mgr is not None:
            seen[(mgr, pick.player.name)].add(pick.season.year)
    if not seen:
        return []
    (mgr, player_name), years = max(seen.items(), key=lambda kv: len(kv[1]))
    if len(years) < 2:
        return []
    return [
        AwardRow(
            None,
            "most_loyal",
            "Most Loyal (Manager–Player)",
            mgr,
            float(len(years)),
            {"player": player_name, "seasons": sorted(years)},
        )
    ]


def compute_awards(
    frames: LeagueFrames,
    season_rows: list[dict],
    draft_values: list[DraftValueRow],
) -> list[AwardRow]:
    awards: list[AwardRow] = []
    for year in sorted(frames.team_count_by_year):
        awards.extend(_season_awards(frames, year, season_rows, draft_values))
    awards.extend(_all_time_awards(frames))
    return awards
