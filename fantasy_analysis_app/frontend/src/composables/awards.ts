// Shared presentation helpers for awards, used by AwardCard and the share card.
import type { AwardEntry } from '../api/client'

export const AWARD_EMOJI: Record<string, string> = {
  heartbreak: '💔',
  daylight_robbery: '🦝',
  benchwarmer: '🪑',
  glass_cannon: '🎢',
  sacko: '🚽',
  paper_champion: '📄',
  luckiest_berth: '🍀',
  draft_whisperer: '🧙',
  cursed_pick: '☠️',
  most_loyal: '💍',
}

export function awardEmoji(slug: string): string {
  return AWARD_EMOJI[slug] ?? '🏅'
}

export function awardBlurb(award: AwardEntry): string {
  const c = award.context
  switch (award.slug) {
    case 'heartbreak':
      return `Scored ${c.score} in week ${c.week} — and still lost to ${c.opponent_score}.`
    case 'daylight_robbery':
      return `Won week ${c.week} with a measly ${c.score} vs ${c.opponent_score}.`
    case 'benchwarmer':
      return `Left ${c.bench_points_lost} points rotting on the bench.`
    case 'glass_cannon':
      return `Weekly scoring swung by ±${c.weekly_score_stddev} points.`
    case 'sacko':
      return `Finished dead last (#${c.final_standing}).`
    case 'paper_champion':
      return `Best expected wins (${c.expected_wins}) but finished #${c.final_standing}.`
    case 'luckiest_berth':
      return `Snuck into the playoffs +${c.luck_delta} wins above expected.`
    case 'draft_whisperer':
      return `Drafted ${c.points_over_replacement} points over replacement.`
    case 'cursed_pick':
      return `A round ${c.round} pick that missed the round median by ${c.round_expectation_delta}.`
    case 'most_loyal':
      return `Rostered ${c.player} across ${(c.seasons as number[]).length} seasons.`
    default:
      return ''
  }
}
