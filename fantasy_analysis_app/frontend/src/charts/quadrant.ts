// Draft value quadrant: cost (overall pick) vs outcome (points over
// replacement). Pure helpers, unit-tested; the chart option lives in
// options.ts. Quadrant boundaries: the season's median pick and PoR = 0.

export type Quadrant = 'Early hit' | 'Late steal' | 'Early bust' | 'Late miss'

export function medianOverallPick(picks: Array<{ overall_pick: number }>): number {
  if (picks.length === 0) return 0
  const sorted = picks.map((p) => p.overall_pick).sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2
}

export function classifyPick(
  overallPick: number,
  pointsOverReplacement: number,
  medianPick: number,
): Quadrant {
  const early = overallPick <= medianPick
  const hit = pointsOverReplacement >= 0
  if (early && hit) return 'Early hit'
  if (!early && hit) return 'Late steal'
  if (early && !hit) return 'Early bust'
  return 'Late miss'
}

// --- Season race (S-1) helpers ---

export interface RaceWeek {
  week: number
  won: boolean
}

/** Cumulative wins aligned to the season's week axis; weeks a team didn't
 * play (byes) carry the previous total forward. */
export function cumulativeWins(seasonWeeks: number[], teamWeeks: RaceWeek[]): number[] {
  const wonByWeek = new Map(teamWeeks.map((w) => [w.week, w.won]))
  const totals: number[] = []
  let running = 0
  for (const week of seasonWeeks) {
    if (wonByWeek.get(week)) running += 1
    totals.push(running)
  }
  return totals
}
