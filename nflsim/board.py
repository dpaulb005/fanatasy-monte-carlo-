"""Terminal rendering: draft board, projections, team outlook.

Falls back to plain aligned text when `rich` is not installed, so the tool
works on a bare interpreter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH = True
except ImportError:                                   # pragma: no cover
    _RICH = False

POS_STYLE = {"QB": "bright_magenta", "RB": "bright_green",
             "WR": "bright_cyan", "TE": "bright_yellow"}
TIER_STYLE = ["bold white", "bright_white", "white", "grey70", "grey58", "grey42"]


# The board carries more columns than an 80-column default can hold, and rich
# drops columns silently when it runs out of room -- the player names were the
# first thing to disappear. Ask for the width the table actually needs, while
# still using a wider terminal when there is one.
MIN_WIDTH = 132


def _console():
    if not _RICH:
        return None
    con = Console()
    if con.width < MIN_WIDTH:
        con = Console(width=MIN_WIDTH)
    return con


def _fmt(v, nd=1):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:,.{nd}f}"


def draft_board(df: pd.DataFrame, n: int = 60, scoring_name: str = "Full PPR",
                league_desc: str = "12-team") -> None:
    """The board, ordered by value over replacement and split into tiers."""
    if not _RICH:
        cols = ["overall_rank", "tier", "player", "pos", "team", "points",
                "p10", "p90", "vor", "games"]
        print(df[cols].head(n).to_string(index=False))
        return

    con = _console()
    t = Table(
        title=f"2026 Draft Board  ·  {scoring_name}  ·  {league_desc}  ·  ranked by VOR",
        box=box.SIMPLE_HEAVY, header_style="bold", title_style="bold",
        pad_edge=False,
    )
    t.add_column("#", justify="right", style="grey58", width=3)
    t.add_column("Tr", justify="center", width=2)
    t.add_column("Player", min_width=21, no_wrap=True)
    t.add_column("Pos", justify="center", width=4)
    t.add_column("Tm", justify="center", width=3)
    t.add_column("Proj", justify="right", width=6)
    t.add_column("VOR", justify="right", width=6)
    t.add_column("Floor", justify="right", width=6, style="grey58")
    t.add_column("Ceil", justify="right", width=6, style="grey58")
    t.add_column("PPG", justify="right", width=5)
    t.add_column("G", justify="right", width=4)
    t.add_column("Boom", justify="right", width=5, style="grey58")
    t.add_column("Bust", justify="right", width=5, style="grey58")

    prev_tier = None
    for _, r in df.head(n).iterrows():
        if prev_tier is not None and r.tier != prev_tier:
            t.add_section()
        prev_tier = r.tier
        pos_st = POS_STYLE.get(r.pos, "white")
        t.add_row(
            str(int(r.overall_rank)),
            f"[{TIER_STYLE[min(int(r.tier) - 1, len(TIER_STYLE) - 1)]}]{int(r.tier)}[/]",
            f"{r.player}" + ("  [grey42]R[/]" if r.get("rookie") else ""),
            f"[{pos_st}]{r.pos}[/]",
            str(r.team),
            _fmt(r.points, 0),
            f"[bold]{_fmt(r.vor, 0)}[/]",
            _fmt(r.p10, 0),
            _fmt(r.p90, 0),
            _fmt(r.ppg, 1),
            _fmt(r.games, 1),
            f"{r.boom*100:.0f}%" if np.isfinite(r.get("boom", np.nan)) else "-",
            f"{r.bust*100:.0f}%" if np.isfinite(r.get("bust", np.nan)) else "-",
        )
    con.print(t)


def positional(df: pd.DataFrame, pos: str, n: int = 24,
               scoring_name: str = "Full PPR") -> None:
    """Position-by-position projections with the underlying stat line."""
    sub = df[df.pos == pos].sort_values("points", ascending=False).head(n)
    if sub.empty:
        return
    if not _RICH:
        print(sub.to_string(index=False))
        return

    con = _console()
    t = Table(title=f"{pos} projections  ·  {scoring_name}",
              box=box.SIMPLE_HEAVY, header_style="bold", title_style="bold")
    t.add_column("#", justify="right", width=3, style="grey58")
    t.add_column("Player", min_width=20)
    t.add_column("Tm", justify="center", width=3)
    t.add_column("Pts", justify="right", width=6)
    t.add_column("PPG", justify="right", width=5)
    t.add_column("G", justify="right", width=4)
    t.add_column("p10", justify="right", width=6, style="grey58")
    t.add_column("p90", justify="right", width=6, style="grey58")

    if pos == "QB":
        stat_cols = [("PaYd", "pass_yds", 0), ("PaTD", "pass_td", 1),
                     ("Int", "ints", 1), ("RuYd", "rush_yds", 0), ("RuTD", "rush_td", 1)]
    elif pos == "RB":
        stat_cols = [("Car", "carries", 0), ("RuYd", "rush_yds", 0), ("RuTD", "rush_td", 1),
                     ("Tgt", "targets", 0), ("Rec", "rec", 0), ("ReYd", "rec_yds", 0)]
    else:
        stat_cols = [("Tgt", "targets", 0), ("Rec", "rec", 0), ("ReYd", "rec_yds", 0),
                     ("ReTD", "rec_td", 1)]
    for label, _, _ in stat_cols:
        t.add_column(label, justify="right", width=max(len(label) + 1, 5))

    for i, (_, r) in enumerate(sub.iterrows(), 1):
        row = [
            str(i),
            f"{r.player}" + ("  [grey42]R[/]" if r.get("rookie") else ""),
            str(r.team), _fmt(r.points, 0), _fmt(r.ppg, 1), _fmt(r.games, 1),
            _fmt(r.p10, 0), _fmt(r.p90, 0),
        ]
        row += [_fmt(r[c], nd) for _, c, nd in stat_cols]
        t.add_row(*row)
    con.print(t)


def teams(ts: pd.DataFrame, coach_tab: pd.DataFrame | None = None) -> None:
    """Projected team wins and scoring, with the coaching inputs behind them."""
    if not _RICH:
        print(ts.to_string(index=False))
        return
    con = _console()
    t = Table(title="Team outlook", box=box.SIMPLE_HEAVY, header_style="bold",
              title_style="bold")
    for c, j, w in [("Tm", "center", 4), ("Wins", "right", 6), ("p10", "right", 5),
                    ("p90", "right", 5), ("Pts/G", "right", 6)]:
        t.add_column(c, justify=j, width=w)
    if coach_tab is not None:
        for c in ("Coach", "PROE", "Pace", "4th"):
            t.add_column(c, justify="left" if c == "Coach" else "right")

    cm = coach_tab.set_index("team") if coach_tab is not None else None
    for _, r in ts.iterrows():
        row = [r.team, _fmt(r.wins, 1), _fmt(r.wins_p10, 0), _fmt(r.wins_p90, 0),
               _fmt(r.points_pg, 1)]
        if cm is not None and r.team in cm.index:
            c = cm.loc[r.team]
            new = "  [grey42]new[/]" if c.get("new") else ""
            row += [f"{c.coach}{new}", f"{c.proe*100:+.1f}%",
                    f"{c.pace:.1f}s", f"{c.go_oe*100:+.1f}%"]
        elif cm is not None:
            row += ["-", "-", "-", "-"]
        t.add_row(*row)
    con.print(t)


def summary_note(df: pd.DataFrame, n_sims: int, scoring_name: str) -> None:
    if not _RICH:
        return
    con = _console()
    con.print(
        f"\n[grey58]{n_sims:,} simulated seasons · {scoring_name} · "
        f"Proj = mean season points · Floor/Ceil = 10th/90th percentile · "
        f"VOR = points above replacement · Boom/Bust = share of seasons above "
        f"the positional 75th / below the 25th percentile of starters[/]"
    )
