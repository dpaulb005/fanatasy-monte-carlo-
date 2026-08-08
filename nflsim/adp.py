"""Average draft position: what the market thinks, as opposed to the model.

The simulator's own board is a projection. A draft is a negotiation with
eleven other people who are not using it, and the only way to practise against
them is to know where players actually come off the table. That is what ADP
is, and it is the one input here that is deliberately *not* derived from the
engine -- the whole point is that it disagrees.

Sources, in preference order:

  espn         ESPN's public fantasy API, `averageDraftPosition` from live
               drafts. This is the real thing and the default.
  csv          A file you exported yourself, for leagues whose board is not
               ESPN's, or for a snapshot you want to freeze.
  fantasypros  Expert consensus rank via the DynastyProcess mirror. Not ADP --
               it is what the analysts say rather than what drafters do -- but
               it is a genuine outside opinion, it updates daily, and it is
               reachable from environments that cannot see ESPN.

Every source is normalised to the same frame: one row per player, with `adp`
in overall-pick units and `adp_sd` in the same units.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .data import CACHE

# --------------------------------------------------------------------------
# ESPN
# --------------------------------------------------------------------------

ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"
ESPN_PATH = "/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/0"

# ESPN's own identifiers. Only the four positions the engine projects are kept;
# kickers and defences are not simulated and would only pollute the board.
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV",
    14: "LA", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
    28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# ESPN keys its draft ranks by scoring type; ours are the fantasy formats the
# engine supports.
ESPN_RANK_TYPE = {"Full PPR": "PPR", "Half PPR": "PPR", "Standard": "STANDARD"}


def _espn_filter(limit: int, offset: int, rank_type: str) -> str:
    return json.dumps({
        "players": {
            "limit": limit,
            "offset": offset,
            "sortDraftRanks": {
                "sortPriority": 100, "sortAsc": True, "value": rank_type,
            },
            "filterStatsForTopScoringPeriodIds": {"value": [0]},
        }
    })


def _espn_page(season: int, limit: int, offset: int, rank_type: str,
               retries: int = 4) -> list[dict]:
    url = f"{ESPN_HOST}{ESPN_PATH.format(season=season)}?view=kona_player_info"
    headers = {
        "User-Agent": "nflsim/1.0",
        "Accept": "application/json",
        "x-fantasy-filter": _espn_filter(limit, offset, rank_type),
        "x-fantasy-source": "kona",
        "x-fantasy-platform": "kona-PROD",
    }
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read()).get("players", [])
        except Exception as exc:  # noqa: BLE001 - network layer, retry everything
            last = exc
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(
        f"ESPN ADP fetch failed for {season}: {last}\n"
        "  If this environment cannot reach fantasy.espn.com, run\n"
        "  `python -m nflsim adp --source espn --save espn_adp.csv` somewhere\n"
        "  that can, then pass `--adp espn_adp.csv` here."
    )


def fetch_espn(season: int, scoring_name: str = "Full PPR",
               pages: int = 4, per_page: int = 300) -> pd.DataFrame:
    """Live ESPN average draft position, in overall-pick units.

    ESPN reports ADP as a mean over real drafts, so a player taken 1.05 on
    average sits at 1.05 -- already the unit a draft runs in. Players nobody
    has drafted come back as zero, which is a missing value rather than the
    first pick, and are dropped.
    """
    rank_type = ESPN_RANK_TYPE.get(scoring_name, "PPR")
    rows = []
    for page in range(pages):
        batch = _espn_page(season, per_page, page * per_page, rank_type)
        if not batch:
            break
        rows.extend(espn_rows(batch, rank_type))
        if len(batch) < per_page:
            break
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"ESPN returned no players for {season}")
    return _finish(df, "espn")


def espn_rows(batch: list[dict], rank_type: str = "PPR") -> list[dict]:
    """Flatten one page of ESPN's player payload.

    Split out from the fetch so it can be tested without a network: this is
    the part that goes wrong when ESPN moves a field, and it is the part that
    cannot be exercised from an environment that ESPN is not reachable from.
    """
    out = []
    for item in batch:
        p = item.get("player") or {}
        own = p.get("ownership") or {}
        adp = own.get("averageDraftPosition")
        ranks = (p.get("draftRanksByRankType") or {}).get(rank_type) or {}
        out.append({
            "player": p.get("fullName"),
            "pos": ESPN_POS.get(p.get("defaultPositionId")),
            "team": ESPN_TEAM.get(p.get("proTeamId")),
            # ESPN reports zero for a player no draft has ever taken. That is
            # a missing value, not the first pick, and `_finish` drops it.
            "adp": float(adp) if adp else np.nan,
            "espn_rank": ranks.get("rank"),
            "auction": ranks.get("auctionValue"),
            "pct_owned": own.get("percentOwned"),
        })
    return out


# --------------------------------------------------------------------------
# FantasyPros expert consensus, via the DynastyProcess mirror
# --------------------------------------------------------------------------

FPECR = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_fpecr.parquet"


def fetch_fantasypros(season: int) -> pd.DataFrame:
    """Redraft expert consensus rank, used as an ADP stand-in.

    A consensus rank is not a draft position: analysts rank the player they
    think is better, drafters take the player they want. The two differ
    systematically -- rankers are less swayed by name and more by projection.
    Treating rank as pick number is therefore a proxy, and the header of any
    board built this way says so.

    What it does give, and ESPN does not, is `sd`: the disagreement between
    experts on each player. That is a per-player uncertainty, and it drives
    the bots' pick noise far better than one league-wide constant can.
    """
    dest = CACHE / "adp" / "db_fpecr.parquet"
    if not (dest.exists() and dest.stat().st_size > 0):
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  fetching {FPECR.rsplit('/', 1)[-1]} ...", file=sys.stderr, flush=True)
        req = urllib.request.Request(FPECR, headers={"User-Agent": "nflsim/1.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
        tmp = dest.with_suffix(".part.parquet")
        tmp.write_bytes(body)
        tmp.replace(dest)

    raw = pd.read_parquet(dest, columns=["player", "pos", "tm", "ecr", "sd",
                                         "page_type", "scrape_date"])
    board = raw[raw.page_type == "redraft-overall"]
    if board.empty:
        raise RuntimeError("no redraft-overall rankings in the FantasyPros mirror")
    # Only the newest scrape: the file is a full history and stacking scrapes
    # would average this year's board with last August's.
    board = board[board.scrape_date == board.scrape_date.max()]
    df = board.rename(columns={"tm": "team", "ecr": "adp", "sd": "adp_sd"})
    df = df[["player", "pos", "team", "adp", "adp_sd"]].copy()
    df["asof"] = str(board.scrape_date.max())
    return _finish(df, "fantasypros")


# --------------------------------------------------------------------------
# User-supplied file
# --------------------------------------------------------------------------

# Every column name any of the usual exports uses for the same thing.
CSV_ALIASES = {
    "player": ["player", "name", "player_name", "full_name", "playername"],
    "pos": ["pos", "position"],
    "team": ["team", "tm", "nfl_team", "pro_team"],
    "adp": ["adp", "avg", "average", "averagedraftposition", "rank",
            "overall", "overall_rank", "ecr"],
    "adp_sd": ["adp_sd", "sd", "stdev", "std", "sddev"],
}


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read an exported board, tolerating whatever the exporter called things."""
    raw = pd.read_csv(path)
    lookup = {re.sub(r"[^a-z]", "", c.lower()): c for c in raw.columns}
    out = {}
    for want, names in CSV_ALIASES.items():
        for n in names:
            if n in lookup:
                out[want] = raw[lookup[n]]
                break
    missing = {"player", "adp"} - set(out)
    if missing:
        raise SystemExit(
            f"{path}: need at least a player column and an ADP column; "
            f"missing {sorted(missing)}. Columns present: {list(raw.columns)}"
        )
    df = pd.DataFrame(out)
    if "pos" not in df:
        df["pos"] = None
    if "team" not in df:
        df["team"] = None
    # Boards often carry "RB1", "WR23" in the position column.
    df["pos"] = df.pos.astype(str).str.extract(r"([A-Za-z]+)")[0].str.upper()
    df["adp"] = pd.to_numeric(df.adp, errors="coerce")
    return _finish(df, "csv")


# --------------------------------------------------------------------------
# Shared normalisation and name matching
# --------------------------------------------------------------------------

# Teams that have moved or that a source spells differently.
TEAM_FIX = {"LAR": "LA", "STL": "LA", "SD": "LAC", "OAK": "LV", "WSH": "WAS",
            "WFT": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL",
            "CLV": "CLE", "HST": "HOU", "GNB": "GB", "KAN": "KC",
            "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB", "LVR": "LV"}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(raw) -> str:
    """A name reduced to what two sources can agree on.

    Punctuation, case and generational suffixes are the three things that
    differ between any two fantasy data providers for the same person, and
    none of them identify anybody.

    Initials are the fourth and the awkward one. One source writes "D.K.
    Metcalf" and another "DK Metcalf", so stripping the periods leaves
    "d k metcalf" against "dk metcalf" -- still a miss, and it hits exactly
    the players who go by initials. Runs of single letters are therefore
    glued back together, which folds both spellings onto the same key.
    """
    s = str(raw).lower()
    s = s.replace("&", " ").replace(".", " ").replace("'", "").replace("`", "")
    s = re.sub(r"[^a-z ]", " ", s)
    parts = [p for p in s.split() if p and p not in SUFFIXES]

    lead = 0
    while lead < len(parts) and len(parts[lead]) == 1:
        lead += 1
    if lead > 1 and lead < len(parts):
        parts = ["".join(parts[:lead])] + parts[lead:]
    return " ".join(parts)


def _finish(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df.copy()
    df["source"] = source
    df["team"] = df.team.astype(str).str.upper().replace(TEAM_FIX)
    df["pos"] = df.pos.astype(str).str.upper()
    df = df[df.pos.isin(("QB", "RB", "WR", "TE"))]
    df = df[df.adp.notna() & (df.adp > 0)]
    if "adp_sd" not in df:
        df["adp_sd"] = np.nan
    df["key"] = df.player.map(norm_name)
    # One row per player: keep the earliest board position if a source lists
    # somebody twice (it happens after trades).
    df = df.sort_values("adp").drop_duplicates("key", keep="first")
    # Re-rank within the four scoring positions, keeping the source's own
    # number as `adp_raw`. ESPN's raw ADP counts kickers and defences, so pick
    # 100 on their board is not pick 100 in a league that does not roster
    # them. Bots compare players by `adp` plus noise measured in picks, so the
    # column they read has to be a dense pick number in *this* league's units.
    df = df.sort_values("adp").reset_index(drop=True)
    df["adp_raw"] = df.adp.to_numpy()
    df["adp"] = np.arange(1, len(df) + 1, dtype=float)
    return df


def load(source: str = "espn", season: int = 2026, path: str | None = None,
         scoring_name: str = "Full PPR") -> pd.DataFrame:
    """Fetch a board from `source`, or read one from `path`."""
    if path:
        return read_csv(path)
    if source == "espn":
        return fetch_espn(season, scoring_name)
    if source == "fantasypros":
        return fetch_fantasypros(season)
    raise SystemExit(f"unknown ADP source {source!r}")


# --------------------------------------------------------------------------
# Joining the board to the model's players
# --------------------------------------------------------------------------

def attach(adp: pd.DataFrame, player_table: pd.DataFrame,
           undrafted_pad: float = 40.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align a board to the player table, returning (aligned, unmatched).

    Matching is on normalised name, then on name and position, because two
    different people share a name far more often than one person appears at two
    positions. Anybody on the board the engine has never heard of is reported
    rather than dropped silently -- a missing name is usually a rookie the
    model has, spelled differently, and quietly ignoring it would hand the bots
    a free pick.

    Players the engine projects but the market does not rank are placed after
    the last ranked player, ordered by the model's own view of them. They are
    the undrafted pool, and they have to be draftable: the last rounds of a
    real draft are full of them.
    """
    pt = player_table.copy()
    pt["key"] = pt.name.map(norm_name)

    by_name = adp.drop_duplicates("key").set_index("key")
    by_name_pos = adp.drop_duplicates(["key", "pos"]).set_index(["key", "pos"])

    out = pd.DataFrame(index=pt.index)
    out["adp"] = np.nan
    out["adp_sd"] = np.nan

    # Name+position first: it is the stricter of the two and wins ties.
    idx = pd.MultiIndex.from_arrays([pt.key, pt.pos])
    hit = by_name_pos.reindex(idx)
    out["adp"] = hit.adp.to_numpy()
    out["adp_sd"] = hit.adp_sd.to_numpy()

    need = out.adp.isna()
    if need.any():
        loose = by_name.reindex(pt.key[need])
        out.loc[need, "adp"] = loose.adp.to_numpy()
        out.loc[need, "adp_sd"] = loose.adp_sd.to_numpy()

    matched_keys = set(pt.key[out.adp.notna()])
    unmatched = adp[~adp.key.isin(matched_keys)].copy()

    out["ranked"] = out.adp.notna()
    out["pos"] = pt.pos.values
    out["name"] = pt.name.values
    out["team"] = pt.team.values
    return out, unmatched


def fill_undrafted(aligned: pd.DataFrame, model_rank: pd.Series,
                   gap: float = 8.0) -> pd.DataFrame:
    """Place unranked players below the board, in the model's order.

    `model_rank` is the engine's overall ordering, indexed like the player
    table. Unranked players keep that relative order but start a gap below the
    deepest ranked player, so a bot will only reach one when the board is
    genuinely exhausted.
    """
    out = aligned.copy()
    missing = out.adp.isna()
    if missing.any():
        base = float(out.adp.max() if out.adp.notna().any() else 0.0) + gap
        order = model_rank.reindex(out.index[missing]).rank(method="first")
        out.loc[missing, "adp"] = base + order.to_numpy() - 1.0
    # Anyone the board did not price also has no disagreement estimate; give
    # them the widest observed one rather than zero, since an unranked player
    # is the *least* certain thing on the board, not the most.
    wide = float(np.nanmax(out.adp_sd.to_numpy())) if out.adp_sd.notna().any() else np.nan
    out["adp_sd"] = out.adp_sd.fillna(wide)
    return out
