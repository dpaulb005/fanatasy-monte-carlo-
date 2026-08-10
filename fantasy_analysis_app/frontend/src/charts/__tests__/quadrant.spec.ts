import { describe, expect, it } from 'vitest'
import { classifyPick, cumulativeWins, medianOverallPick } from '../quadrant'

describe('medianOverallPick', () => {
  it('handles odd and even pick counts', () => {
    expect(medianOverallPick([{ overall_pick: 1 }, { overall_pick: 5 }, { overall_pick: 9 }])).toBe(
      5,
    )
    expect(medianOverallPick([{ overall_pick: 2 }, { overall_pick: 4 }])).toBe(3)
    expect(medianOverallPick([])).toBe(0)
  })
})

describe('classifyPick', () => {
  it('names all four quadrants', () => {
    expect(classifyPick(10, 50, 80)).toBe('Early hit')
    expect(classifyPick(120, 50, 80)).toBe('Late steal')
    expect(classifyPick(10, -50, 80)).toBe('Early bust')
    expect(classifyPick(120, -50, 80)).toBe('Late miss')
  })

  it('boundaries: at-median is early, PoR zero is a hit', () => {
    expect(classifyPick(80, 0, 80)).toBe('Early hit')
    expect(classifyPick(81, -0.1, 80)).toBe('Late miss')
  })
})

describe('cumulativeWins', () => {
  it('accumulates along the season week axis and carries through gaps', () => {
    const weeks = [1, 2, 3, 4]
    const team = [
      { week: 1, won: true },
      { week: 3, won: true },
      { week: 4, won: false },
    ]
    expect(cumulativeWins(weeks, team)).toEqual([1, 1, 2, 2])
  })
})
