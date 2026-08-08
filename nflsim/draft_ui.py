"""Terminal front end for the draft: the clock, the board, the results.

Kept apart from `draft.py` so the simulation has no opinion about how it is
displayed, and can be driven from a script or a test without a console.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .board import POS_STYLE, _RICH, _console, _fmt
from .draft import DraftConfig, DraftState, pick_sigma

if _RICH:                                             # pragma: no cover
    from rich import box
    from rich.table import Table


# --------------------------------------------------------------------------
# What you see when you are on the clock
# --------------------------------------------------------------------------

def available_board(state: DraftState, proj: pd.DataFrame, n: int = 18,
                    engine=None) -> pd.DataFrame:
    """Best available, ordered by the model, priced against the market.

    `wait` is the column to draft from: the chance a player is still there when
    this seat picks again. It comes from the same noise the bots use, so it is
    consistent with the room you are actually sitting in -- a player whose ADP
    falls five picks after your next one is not safe, because five picks is
    well inside the deviation.

    It is a marginal probability and it ignores the need and run bonuses, which
    only ever pull a position *forward*. So it is an upper bound: if it says a
    tight end is 60% to last, he is 60% at best.
    """
    avail = state.available()
    df = proj.reindex(avail.index).copy()
    df["adp"] = avail.adp
    df["adp_delta"] = avail.adp - state.pick_no
    nxt = state.next_pick()
    if nxt > 0:
        sigma = pick_sigma(avail.adp.to_numpy(dtype=float),
                           avail.adp_sd.to_numpy(dtype=float), state.cfg)
        z = (nxt - avail.adp.to_numpy(dtype=float)) / np.maximum(sigma, 1e-6)
        df["wait"] = np.clip(0.5 * (1.0 - _erf(z / np.sqrt(2.0))), 0.0, 1.0)
    else:
        df["wait"] = np.nan

    if engine is not None:
        gains = engine.gains(state, proj)
        df["gain"] = gains.reindex(df.index)
        # Order by what the pick is worth to *this* roster, which is the whole
        # reason the column exists. Anyone outside the shortlist keeps his VOR
        # ordering below the players that were scored.
        return df.sort_values(["gain", "vor"], ascending=False).head(n)
    return df.sort_values("vor", ascending=False).head(n)


def _erf(x):
    """Error function without scipy, via a numerically stable rational fit."""
    # Abramowitz & Stegun 7.1.26, |error| < 1.5e-7.
    s = np.sign(x)
    x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return s * y


def show_clock(state: DraftState, proj: pd.DataFrame, n: int = 18,
               engine=None) -> pd.DataFrame:
    """Print the on-the-clock view and return what was shown."""
    df = available_board(state, proj, n, engine)
    roster = (proj.reindex(state.pool.index[state.roster])
              if state.roster else proj.iloc[:0])
    nxt = state.next_pick()
    header = (f"Pick {state.pick_no}  ·  round {state.rnd}  ·  "
              f"your next pick: {nxt if nxt > 0 else 'last'}")

    if not _RICH:
        print("\n" + header)
        cols = [c for c in ["player", "pos", "team", "points", "gain", "vor",
                            "p10", "p90", "adp", "adp_delta", "wait"]
                if c in df]
        print(df[cols].to_string())
        if len(roster):
            print("your roster: " + ", ".join(
                f"{r.player} ({r.pos})" for _, r in roster.iterrows()))
        return df

    con = _console()
    t = Table(title=header, box=box.SIMPLE_HEAVY, header_style="bold",
              title_style="bold", pad_edge=False)
    t.add_column("#", justify="right", style="grey58", width=3)
    t.add_column("Player", min_width=21, no_wrap=True)
    t.add_column("Pos", justify="center", width=4)
    t.add_column("Tm", justify="center", width=3)
    t.add_column("Proj", justify="right", width=6)
    has_gain = "gain" in df
    if has_gain:
        t.add_column("Gain", justify="right", width=6)
    t.add_column("VOR", justify="right", width=6, style="grey58")
    t.add_column("Floor", justify="right", width=6, style="grey58")
    t.add_column("Ceil", justify="right", width=6, style="grey58")
    t.add_column("ADP", justify="right", width=6)
    t.add_column("Val", justify="right", width=6)
    t.add_column("Wait", justify="right", width=5)

    for i, (_, r) in enumerate(df.iterrows(), start=1):
        # Value is the market's gift: positive means he has fallen past where
        # the room would normally take him.
        val = r.adp_delta
        val_st = "bright_green" if val >= 6 else ("red" if val <= -12 else "white")
        wait = r.get("wait", np.nan)
        wait_st = "grey58" if not np.isfinite(wait) else (
            "bright_green" if wait > 0.7 else "yellow" if wait > 0.35 else "red")
        row = [
            str(i),
            f"{r.player}" + ("  [grey42]R[/]" if r.get("rookie") else ""),
            f"[{POS_STYLE.get(r.pos, 'white')}]{r.pos}[/]",
            str(r.team),
            _fmt(r.points, 0),
        ]
        if has_gain:
            row.append(f"[bold]{_fmt(r.get('gain'), 0)}[/]")
        row += [
            _fmt(r.vor, 0),
            _fmt(r.p10, 0), _fmt(r.p90, 0),
            _fmt(r.adp, 0),
            f"[{val_st}]{val:+.0f}[/]",
            "-" if not np.isfinite(wait) else f"[{wait_st}]{wait*100:.0f}%[/]",
        ]
        t.add_row(*row)
    con.print(t)

    if len(roster):
        con.print("  [grey58]your roster:[/] " + "  ".join(
            f"[{POS_STYLE.get(r.pos, 'white')}]{r.pos}[/] {r.player}"
            for _, r in roster.iterrows()))
    return df


def prompt(state: DraftState, proj: pd.DataFrame, engine=None) -> int | None:
    """Ask for a pick. Accepts a shown row number, or part of a name."""
    shown = show_clock(state, proj, engine=engine)
    avail = state.available()
    while True:
        try:
            raw = input("  pick (number, name, or blank for best available): ").strip()
        except EOFError:
            return None
        if not raw:
            return int(np.flatnonzero(state.pool.index == shown.index[0])[0])
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            gi = shown.index[int(raw) - 1]
            return int(np.flatnonzero(state.pool.index == gi)[0])
        hit = avail[avail.name.str.lower().str.contains(raw.lower(), regex=False)]
        if len(hit) == 1:
            return int(np.flatnonzero(state.pool.index == hit.index[0])[0])
        if len(hit) == 0:
            print(f"  no available player matching {raw!r}")
        else:
            print("  ambiguous: " + ", ".join(hit.name.head(8)))


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

def show_league(table: pd.DataFrame, n_sims: int) -> None:
    """The post-draft league table, ordered by title odds."""
    if not _RICH:
        print(table.to_string(index=False))
        return
    con = _console()
    t = Table(title="After the draft  ·  every roster scored on the same "
                    f"{n_sims:,} simulated seasons",
              box=box.SIMPLE_HEAVY, header_style="bold", title_style="bold",
              pad_edge=False)
    t.add_column("#", justify="right", style="grey58", width=3)
    t.add_column("Team", min_width=14, no_wrap=True)
    t.add_column("Starters", justify="right", width=8)
    t.add_column("Floor", justify="right", width=7, style="grey58")
    t.add_column("Ceil", justify="right", width=7, style="grey58")
    t.add_column("Bench", justify="right", width=7, style="grey58")
    t.add_column("Title", justify="right", width=6)
    t.add_column("Playoff", justify="right", width=7)
    t.add_column("Last", justify="right", width=5, style="grey58")
    t.add_column("Finish", justify="right", width=6)

    for _, r in table.iterrows():
        you = "(you)" in r.team
        st = "bold bright_white" if you else "white"
        t.add_row(
            str(int(r.seed)),
            f"[{st}]{r.team}[/]",
            _fmt(r.points, 0), _fmt(r.p10, 0), _fmt(r.p90, 0), _fmt(r.bench, 0),
            f"[bold]{r.p_title*100:.1f}%[/]",
            f"{r.p_playoff*100:.1f}%",
            f"{r.p_last*100:.1f}%",
            f"{r.mean_finish:.1f}",
        )
    con.print(t)


def league_note(n_sims: int, strategy: str | None) -> None:
    """The caveats, printed where they cannot be missed.

    Two of these are load-bearing. The finish probabilities come from the same
    model that chose the players, so a seat drafting the model's board is being
    marked by its own examiner and will always look strong -- the number to
    read is the gap between seats, not its level. And lineups are set after the
    season is known, which pays depth more than a real manager ever collects.
    """
    lines = [
        "Lineups are optimal in hindsight (best-ball), so every total is high; "
        "the comparison between rosters survives it, the absolute number does not.",
        "Rosters are scored on the same replications, so a stack swings together "
        "-- that widens a team's range without moving its mean.",
    ]
    if strategy in ("value", "vor"):
        lines.insert(0,
            "Your seat drafted this model's own board and is then graded by it. "
            "That circularity flatters the result; treat it as a practice room, "
            "not a forecast of your edge.")
    if n_sims < 2000:
        lines.append(f"Only {n_sims:,} simulated seasons: title odds this thin "
                     "move by several points run to run.")
    if _RICH:
        con = _console()
        for ln in lines:
            con.print(f"  [grey58]· {ln}[/]")
    else:
        for ln in lines:
            print(f"  · {ln}")


def show_roster(picks: pd.DataFrame, team_idx: int, proj: pd.DataFrame,
                title: str) -> None:
    """One team's draft, pick by pick, with what the market thought."""
    sub = picks[picks.team_idx == team_idx]
    if not _RICH:
        print(f"\n{title}")
        print(sub.to_string(index=False))
        return
    con = _console()
    t = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold",
              title_style="bold", pad_edge=False)
    t.add_column("Rd", justify="right", width=3, style="grey58")
    t.add_column("Pick", justify="right", width=4, style="grey58")
    t.add_column("Player", min_width=21, no_wrap=True)
    t.add_column("Pos", justify="center", width=4)
    t.add_column("Tm", justify="center", width=3)
    t.add_column("Proj", justify="right", width=6)
    t.add_column("VOR", justify="right", width=6)
    t.add_column("ADP", justify="right", width=6)
    t.add_column("Val", justify="right", width=6)
    if "vor_lost" in sub:
        t.add_column("Left", justify="right", width=6, style="grey58")

    for _, r in sub.iterrows():
        p = proj.loc[r.gindex] if r.gindex in proj.index else None
        val = r.adp_delta
        val_st = "bright_green" if val >= 6 else ("red" if val <= -12 else "white")
        row = [
            str(int(r["round"])), str(int(r["pick"])),
            str(r.player),
            f"[{POS_STYLE.get(r.pos, 'white')}]{r.pos}[/]",
            str(r.nfl),
            _fmt(p.points, 0) if p is not None else "-",
            _fmt(p.vor, 0) if p is not None else "-",
            _fmt(r.adp, 0),
            f"[{val_st}]{val:+.0f}[/]",
        ]
        if "vor_lost" in sub:
            lost = r.vor_lost
            row.append(f"{lost:.0f}" if np.isfinite(lost) and lost > 0.5 else "-")
        t.add_row(*row)
    con.print(t)


def show_source_note(source: str, board_size: int, unmatched: int,
                     asof: str | None) -> None:
    bits = [f"ADP source: {source}", f"{board_size} players priced"]
    if asof:
        bits.append(f"as of {asof}")
    if unmatched:
        bits.append(f"{unmatched} board entries the model does not carry")
    line = "  ·  ".join(bits)
    if _RICH:
        _console().print(f"[grey58]{line}[/]")
    else:
        print(line, file=sys.stderr)
