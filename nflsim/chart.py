"""A static image of the board, for when a terminal table will not travel.

The chart is a distribution plot, not a bar chart, and that is the whole point.
A bar chart of projected points asserts that the projection is a number. It is
not -- it is the mean of ten thousand simulated seasons, and the useful
information is how wide those seasons are and how much two players overlap. So
each player gets his interquartile range, his tenth-to-ninetieth range, and a
marker at the mean, and the reader can see immediately that the fourth-ranked
back's range covers the first-ranked back's.

Rendered on a single light ground rather than adapting to a viewer theme: a PNG
has one background and pretending otherwise produces an image that is unreadable
in half of the places it gets pasted.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Validated with the dataviz palette checker against this surface: lightness
# band, chroma floor, adjacent-pair CVD separation and contrast all pass.
# Position also appears in every row label, so identity is never colour alone --
# which is what makes the blue/green pair legal for tritan readers.
POS_COLOR = {"QB": "#7A5AF8", "RB": "#0E9F6E", "WR": "#2E86DE", "TE": "#C2410C"}

SURFACE = "#FCFCFB"
INK = "#1A1A17"
INK_MUTED = "#6B6B63"
INK_FAINT = "#A8A89E"
GRID = "#E6E5E0"


def _rc():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "text.color": INK,
        "axes.edgecolor": GRID,
    })
    return plt


def top_players(df: pd.DataFrame, out: str | Path, n: int = 30,
                scoring_name: str = "Full PPR", n_sims: int = 0,
                league_desc: str = "12-team", by: str = "vor") -> Path:
    """Ranked distribution chart of the top `n` players.

    `df` is the frame `analysis.add_value` produces: it needs `player`, `pos`,
    `team`, `points`, `p10`, `p25`, `p75`, `p90` and whatever `by` sorts on.
    """
    plt = _rc()
    ranked = df.nlargest(n, by).reset_index(drop=True)
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    # Matplotlib's y axis counts upward, so the frame is reversed to put rank 1
    # at the top. The rank column is assigned *before* that flip -- deriving it
    # from the row position afterwards numbers the best player last.
    d = ranked.iloc[::-1].reset_index(drop=True)

    row_h = 0.285
    fig_h = 2.0 + row_h * len(d)
    fig, ax = plt.subplots(figsize=(12.0, fig_h))
    # The label gutter has to hold the longest name at full size without
    # touching the team column -- "Jaxon Smith-Njigba" is the one that decides
    # it, and at a narrower margin it runs straight through "WR · SEA".
    fig.subplots_adjust(left=0.305, right=0.885, top=1 - 1.15 / fig_h,
                        bottom=0.62 / fig_h)
    y = np.arange(len(d))

    lo, hi = float(d.p10.min()), float(d.p90.max())
    span = hi - lo
    # Start just below the shortest floor rather than at zero: none of these
    # players is anywhere near zero, and the empty run to the origin would eat
    # a third of the width without carrying anything.
    x0 = lo - span * 0.04
    x1 = hi + span * 0.02

    step = 50 if span < 300 else 100
    ticks = np.arange(np.ceil(x0 / step) * step, x1, step)
    for t in ticks:
        ax.axvline(t, color=GRID, lw=0.8, zorder=0)

    # x in axes fractions, y in data units: lets the label and value columns
    # sit at fixed positions while the bars stay on the points scale.
    lab = ax.get_yaxis_transform()

    for i, r in d.iterrows():
        c = POS_COLOR.get(r.pos, INK_MUTED)
        # Two nested ranges: the outer is the 10th-90th, the inner the
        # interquartile. Thin marks, and the inner one carries more weight
        # because it is where four seasons in five land.
        ax.plot([r.p10, r.p90], [i, i], color=c, lw=2.0, alpha=0.30,
                solid_capstyle="round", zorder=2)
        ax.plot([r.p25, r.p75], [i, i], color=c, lw=6.0, alpha=0.55,
                solid_capstyle="round", zorder=3)
        # The mean, ringed in the surface colour so it stays legible where it
        # overlaps the interquartile band.
        ax.plot([r.points], [i], "o", ms=8.5, color=c, mec=SURFACE, mew=2.0,
                zorder=4)
        # Both numbers, because the rows are ordered by the second one. With
        # only the projection showing, the list reads as mis-sorted -- a
        # quarterback at 309 sitting below a back at 245 looks like a bug
        # rather than the entire point of value over replacement.
        ax.text(1.075, i, f"{r.points:,.0f}", transform=lab, va="center",
                ha="right", fontsize=10, color=INK)
        if by == "vor" and "vor" in d:
            ax.text(1.155, i, f"{r.vor:,.0f}", transform=lab, va="center",
                    ha="right", fontsize=9.5, color=INK_MUTED)

    # The row labels are drawn by hand rather than as tick labels, because a
    # tick label is one string in one colour and this needs three pieces at two
    # weights: the rank recedes, the name carries, the team recedes again.
    ax.set_yticks([])
    for i, r in d.iterrows():
        ax.text(-0.415, i, f"{int(r['rank'])}", transform=lab, va="center",
                ha="right", fontsize=9, color=INK_FAINT)
        ax.text(-0.395, i, str(r.player), transform=lab, va="center",
                ha="left", fontsize=10.5, color=INK)
        ax.text(-0.016, i, f"{r.pos} · {r.team}", transform=lab, va="center",
                ha="right", fontsize=8.6, color=INK_MUTED)

    ax.set_xlim(x0, x1)
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{int(t):,}" for t in ticks], fontsize=9,
                       color=INK_MUTED)
    ax.tick_params(axis="x", length=0, pad=5)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    sims = f"{n_sims:,} simulated seasons" if n_sims else "simulated seasons"
    fig.text(0.012, 1 - 0.34 / fig_h, "Projected fantasy points, 2026 season",
             ha="left", va="center", fontsize=16, fontweight="bold", color=INK)
    fig.text(0.012, 1 - 0.62 / fig_h,
             f"Top {len(d)} by value over replacement  ·  {scoring_name}  ·  "
             f"{league_desc}  ·  {sims}",
             ha="left", va="center", fontsize=10, color=INK_MUTED)

    # Legend is always present for four categories, and every row is also
    # labelled with its position, so identity is never colour alone.
    handles = [plt.Line2D([], [], marker="o", ls="", ms=8, color=POS_COLOR[p],
                          mec=SURFACE, mew=1.6, label=p)
               for p in ("QB", "RB", "WR", "TE") if (d.pos == p).any()]
    fig.legend(handles=handles, loc="upper right", frameon=False, ncol=4,
               fontsize=10, handletextpad=0.35, columnspacing=1.3,
               bbox_to_anchor=(0.985, 1 - 0.30 / fig_h))

    head = "proj" + ("        VOR" if by == "vor" and "vor" in d else "")
    ax.text(1.155 if (by == "vor" and "vor" in d) else 1.075, len(d) - 0.55,
            head, transform=lab, va="center", ha="right", fontsize=8.6,
            color=INK_FAINT)

    fig.text(0.012, 0.20 / fig_h,
             "Thick bar: middle half of simulated seasons.   Thin bar: 10th to "
             "90th percentile.   Dot: mean.",
             ha="left", va="center", fontsize=9, color=INK_FAINT)

    out = Path(out)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out
