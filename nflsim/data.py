"""Data acquisition layer.

Everything the model knows comes from here. Sources are the public nflverse
data releases (play-by-play back to 1999, weekly player stats, rosters, depth
charts, snap counts, injury reports, Next Gen Stats, PFR advanced stats,
combine, draft picks) plus the nfldata schedule file, which also carries head
coach assignments and closing market lines.

Files are cached on disk after first download; re-running is cheap.
"""

from __future__ import annotations

import io
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable

import pandas as pd

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLDATA = "https://raw.githubusercontent.com/nflverse/nfldata/master/data"

CACHE = Path(os.environ.get("NFLSIM_CACHE", Path.home() / ".cache" / "nflsim"))


def _fetch(url: str, dest: Path, retries: int = 4) -> Path:
    """Download `url` to `dest` with exponential backoff, caching on disk."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            print(f"  fetching {url.rsplit('/', 1)[-1]} ...", file=sys.stderr, flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "nflsim/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = resp.read()
            if len(body) < 512:
                raise OSError(f"suspiciously small response ({len(body)} bytes)")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(body)
            tmp.replace(dest)
            return dest
        except Exception as exc:  # noqa: BLE001 - network layer, retry everything
            last = exc
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"failed to download {url}: {last}")


def _parquet(tag: str, name: str) -> pd.DataFrame:
    path = _fetch(f"{NFLVERSE}/{tag}/{name}", CACHE / tag / name)
    return pd.read_parquet(path)


def _csv(name: str, **kw) -> pd.DataFrame:
    path = _fetch(f"{NFLDATA}/{name}", CACHE / "nfldata" / name)
    return pd.read_csv(path, **kw)


# --------------------------------------------------------------------------
# Play-by-play
# --------------------------------------------------------------------------

# Only the columns the model actually consumes. play_by_play files carry 372
# columns and ~50k rows per season; restricting the read keeps a decade of
# history inside a couple of GB.
PBP_COLS = [
    "game_id", "season", "season_type", "week", "posteam", "defteam",
    "home_team", "away_team", "play_type", "down", "ydstogo", "yardline_100",
    "goal_to_go", "qtr", "game_seconds_remaining", "half_seconds_remaining",
    "quarter_seconds_remaining", "score_differential", "shotgun", "no_huddle",
    "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "pass_attempt",
    "rush_attempt", "complete_pass", "incomplete_pass", "interception",
    "sack", "fumble_lost", "touchdown", "pass_touchdown", "rush_touchdown",
    "yards_gained", "air_yards", "yards_after_catch", "pass_length",
    "pass_location", "run_location", "run_gap", "epa", "wp", "vegas_wp",
    "first_down", "fourth_down_converted", "fourth_down_failed",
    "field_goal_attempt", "field_goal_result", "kick_distance",
    "extra_point_attempt", "extra_point_result", "two_point_attempt",
    "two_point_conv_result", "punt_attempt", "penalty", "penalty_yards",
    "passer_player_id", "passer_player_name", "receiver_player_id",
    "receiver_player_name", "rusher_player_id", "rusher_player_name",
    "td_player_id", "play_id", "drive", "series_result", "special_teams_play",
    "roof", "surface", "temp", "wind", "posteam_type", "xpass", "pass_oe",
    "cp", "cpoe", "safety", "return_touchdown",
]


def play_by_play(seasons: Iterable[int], columns: list[str] | None = None) -> pd.DataFrame:
    """Regular + postseason play-by-play for the given seasons."""
    cols = PBP_COLS if columns is None else columns
    frames = []
    for yr in seasons:
        path = _fetch(
            f"{NFLVERSE}/pbp/play_by_play_{yr}.parquet",
            CACHE / "pbp" / f"play_by_play_{yr}.parquet",
        )
        try:
            df = pd.read_parquet(path, columns=cols)
        except Exception:
            # Column set drifts slightly across eras; fall back to intersection.
            full = pd.read_parquet(path)
            df = full[[c for c in cols if c in full.columns]].copy()
            for missing in [c for c in cols if c not in full.columns]:
                df[missing] = pd.NA
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out


# --------------------------------------------------------------------------
# Player-level datasets
# --------------------------------------------------------------------------

def player_week(seasons: Iterable[int]) -> pd.DataFrame:
    """Weekly per-player statistical lines."""
    frames = [_parquet("stats_player", f"stats_player_week_{yr}.parquet") for yr in seasons]
    return pd.concat(frames, ignore_index=True)


def rosters(season: int) -> pd.DataFrame:
    return _parquet("rosters", f"roster_{season}.parquet")


def weekly_rosters(seasons: Iterable[int]) -> pd.DataFrame:
    frames = [_parquet("weekly_rosters", f"roster_weekly_{yr}.parquet") for yr in seasons]
    return pd.concat(frames, ignore_index=True)


def depth_charts(season: int) -> pd.DataFrame:
    return _parquet("depth_charts", f"depth_charts_{season}.parquet")


def snap_counts(seasons: Iterable[int]) -> pd.DataFrame:
    frames = [_parquet("snap_counts", f"snap_counts_{yr}.parquet") for yr in seasons]
    return pd.concat(frames, ignore_index=True)


def injuries(seasons: Iterable[int]) -> pd.DataFrame:
    frames = []
    for yr in seasons:
        try:
            frames.append(_parquet("injuries", f"injuries_{yr}.parquet"))
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def players() -> pd.DataFrame:
    return _parquet("players", "players.parquet")


def draft_picks() -> pd.DataFrame:
    return _parquet("draft_picks", "draft_picks.parquet")


def combine() -> pd.DataFrame:
    return _parquet("combine", "combine.parquet")


def ngs(kind: str) -> pd.DataFrame:
    """Next Gen Stats. kind in {passing, rushing, receiving}."""
    return _parquet("nextgen_stats", f"ngs_{kind}.parquet")


def pfr_advstats(kind: str) -> pd.DataFrame:
    """PFR advanced season stats. kind in {pass, rush, rec, def}."""
    return _parquet("pfr_advstats", f"advstats_season_{kind}.parquet")


# --------------------------------------------------------------------------
# Schedule / games (also the source of head coaches and market lines)
# --------------------------------------------------------------------------

def games() -> pd.DataFrame:
    df = _csv("games.csv", low_memory=False)
    return df


def schedule(season: int) -> pd.DataFrame:
    g = games()
    s = g[(g.season == season) & (g.game_type == "REG")].copy()
    return s.sort_values(["week", "gameday", "home_team"]).reset_index(drop=True)


__all__ = [
    "CACHE", "play_by_play", "player_week", "rosters", "weekly_rosters",
    "depth_charts", "snap_counts", "injuries", "players", "draft_picks",
    "combine", "ngs", "pfr_advstats", "games", "schedule",
]
