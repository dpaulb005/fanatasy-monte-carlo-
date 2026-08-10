// Build a shareable season "card" as a self-contained SVG string and export it
// to PNG using only native browser APIs — no image-export dependency. SVG
// serializes to canvas deterministically, so the download is reliable.

export interface ShareCardData {
  leagueName: string
  year: number
  manager: string
  record: string
  finish: string
  pointsFor: number
  luckDelta: number
  lineupEfficiency: number
  benchPointsLost: number
  awardEmoji?: string
  awardTitle?: string
  awardBlurb?: string
}

const W = 1080
const H = 1350
const BG = '#0f1115'
const SURFACE = '#1a1d24'
const TEXT = '#e6e8ec'
const DIM = '#9aa0aa'
const ACCENT = '#4e79a7'
const GOOD = '#59a14f'
const BAD = '#e15759'

function esc(s: string): string {
  return s.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c] as string)
}

function statBlock(x: number, y: number, label: string, value: string, color = TEXT): string {
  return `
    <text x="${x}" y="${y}" fill="${DIM}" font-size="26" font-family="system-ui, sans-serif" letter-spacing="1">${esc(label)}</text>
    <text x="${x}" y="${y + 56}" fill="${color}" font-size="60" font-weight="700" font-family="system-ui, sans-serif">${esc(value)}</text>`
}

export function buildCardSvg(d: ShareCardData): string {
  const luckColor = d.luckDelta >= 0 ? GOOD : BAD
  const luckStr = `${d.luckDelta >= 0 ? '+' : ''}${d.luckDelta.toFixed(1)}`
  const award = d.awardTitle
    ? `
    <rect x="80" y="1010" width="920" height="230" rx="20" fill="${SURFACE}"/>
    <text x="120" y="1085" font-size="70" font-family="system-ui, sans-serif">${esc(d.awardEmoji ?? '🏅')}</text>
    <text x="210" y="1070" fill="${TEXT}" font-size="38" font-weight="700" font-family="system-ui, sans-serif">${esc(d.awardTitle)}</text>
    <text x="210" y="1120" fill="${DIM}" font-size="28" font-family="system-ui, sans-serif">${esc(d.awardBlurb ?? '')}</text>`
    : ''

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <rect width="${W}" height="${H}" fill="${BG}"/>
    <rect x="0" y="0" width="${W}" height="12" fill="${ACCENT}"/>
    <text x="80" y="130" fill="${ACCENT}" font-size="34" font-weight="700" font-family="system-ui, sans-serif">🏈 ${esc(d.leagueName)}</text>
    <text x="80" y="185" fill="${DIM}" font-size="30" font-family="system-ui, sans-serif">${d.year} season recap</text>

    <text x="80" y="330" fill="${TEXT}" font-size="96" font-weight="800" font-family="system-ui, sans-serif">${esc(d.manager)}</text>

    <rect x="80" y="400" width="920" height="2" fill="${SURFACE}"/>

    ${statBlock(80, 500, 'RECORD', d.record)}
    ${statBlock(560, 500, 'FINISH', d.finish)}
    ${statBlock(80, 660, 'POINTS FOR', d.pointsFor.toFixed(0))}
    ${statBlock(560, 660, 'LUCK (W − xW)', luckStr, luckColor)}
    ${statBlock(80, 820, 'LINEUP EFFICIENCY', `${(d.lineupEfficiency * 100).toFixed(0)}%`)}
    ${statBlock(560, 820, 'BENCH POINTS LEFT', d.benchPointsLost.toFixed(0))}

    ${award}

    <text x="80" y="1300" fill="${DIM}" font-size="26" font-family="system-ui, sans-serif">League Lab — every stat from real data</text>
  </svg>`
}

export function downloadCardPng(svg: string, filename: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = W
      canvas.height = H
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        reject(new Error('canvas unsupported'))
        return
      }
      ctx.drawImage(img, 0, 0)
      URL.revokeObjectURL(url)
      canvas.toBlob((png) => {
        if (!png) {
          reject(new Error('export failed'))
          return
        }
        const a = document.createElement('a')
        a.href = URL.createObjectURL(png)
        a.download = filename
        a.click()
        URL.revokeObjectURL(a.href)
        resolve()
      }, 'image/png')
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('svg render failed'))
    }
    img.src = url
  })
}
