# VISUAL_DESIGN_LAB

## Concept: Player ownership timeline strip (V-1) — status: BUILDING (P-1 detail page)
- Question: "Who actually had this player, and when?"
- Sketch: one horizontal strip per season on the player page; weeks as cells,
  colored by rostering manager, saturated when started, muted when benched.
  Hover shows week, manager, points, slot.
- Data: LineupSlot (player, week, team_season→manager, slot, points). Ready.
- Fallback: the per-manager split table below carries the same facts.
- Narrow screens: strips scroll horizontally inside their own container.
- Misread risk: empty cells = not rostered (free agency), NOT zero points — label it.

## Concept: Draft-cost vs production quadrant (V-2) — status: SHIPPED
- Question: "Where did value actually come from in the draft?"
- Data: DraftPickValue (ready). Quadrants: steal / fair / bust / late-hit.
- Existing ADP-vs-outcome scatter partially covers this; extend rather than add.

## Concept: Weekly scoring fingerprint (V-3) — status: SHIPPED
- Small multiples, one per manager-season: 14-17 bars (weeks), median line.
  Answers "volatile or steady?" without a radar chart.

## Concept: League time machine (V-4) — status: BACKLOG (needs event extraction)
- Champions/records/streak milestones already computable from existing tables.

## Concept: Museum of Pain (V-5) — status: SHIPPED (d789726)
- Exhibits derivable from Matchup alone (closest loss, highest score in a loss,
  lowest winning score). Each exhibit links to its matchup data. No new schema.

## Concept: Season playoff race (S-1, bounded) — status: SHIPPED
- Question: "How did the season actually unfold — who was ever in it, when did
  it slip away?"
- Sketch: cumulative-wins line per manager over the season's weeks on the
  season page. Playoff teams at full color, the champion emphasized, everyone
  else muted gray — the narrative IS the divergence of the lines.
- Data: already shipped in the weekly_fingerprints blob (won flag per week) +
  standings (made_playoffs); pure frontend derivation, no backend change.
- Fallback: the standings table above carries the end state; tooltips give
  exact weekly records.
- Misread risk: cumulative wins ≠ seeding (ties/PF tiebreaks) — caption says
  "wins race, not official seeding".

## Anti-patterns adopted as rules
- No radar charts for manager identity (axes not commensurable).
- No network graph for 14 managers (matrix wins at this scale).
- Every chart: plain-language title, one-sentence takeaway, axis units,
  tabular fallback for dense data.
