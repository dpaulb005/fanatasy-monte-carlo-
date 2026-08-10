// ECharts option builders. Views render through these so chart styling stays
// consistent. Data arrives chart-shaped from the API; these only add presentation.

import type { EChartsOption } from 'echarts'
import type { ChartSeries } from '../api/client'

const AXIS_COLOR = '#9aa0aa'
const GRID = { left: 48, right: 24, top: 40, bottom: 32 }

/** Actual vs expected wins over the seasons — the luck visual. */
export function luckChartOption(labels: number[], series: ChartSeries[]): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: AXIS_COLOR } },
    grid: GRID,
    xAxis: {
      type: 'category',
      data: labels.map(String),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
    },
    yAxis: {
      type: 'value',
      name: 'Wins',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: series.map((s, i) => ({
      name: s.name,
      type: 'line',
      smooth: true,
      symbolSize: 7,
      data: s.data,
      lineStyle: { width: i === 0 ? 3 : 2, type: i === 0 ? 'solid' : 'dashed' },
    })),
  }
}

/** Per-season luck delta as a diverging bar (positive = lucky). */
export function luckDeltaOption(labels: number[], deltas: number[]): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: GRID,
    xAxis: {
      type: 'category',
      data: labels.map(String),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
    },
    yAxis: {
      type: 'value',
      name: 'Luck (W − xW)',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: [
      {
        type: 'bar',
        data: deltas.map((d) => ({
          value: d,
          itemStyle: { color: d >= 0 ? '#59a14f' : '#e15759' },
        })),
      },
    ],
  }
}

/** League scoring evolution: mean weekly score line. */
export function scoringEvolutionOption(labels: number[], series: ChartSeries[]): EChartsOption {
  const mean = series.find((s) => s.name.startsWith('Mean'))?.data ?? []
  return {
    tooltip: { trigger: 'axis' },
    grid: GRID,
    xAxis: { type: 'category', data: labels.map(String), axisLine: { lineStyle: { color: AXIS_COLOR } } },
    yAxis: {
      type: 'value',
      name: 'Points / week',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: [
      { name: 'Mean weekly score', type: 'line', smooth: true, symbolSize: 7, data: mean, lineStyle: { width: 3 } },
    ],
  }
}

/** Weekly score distribution per season as a boxplot. */
export function weeklyBoxplotOption(labels: number[], boxes: number[][]): EChartsOption {
  return {
    tooltip: { trigger: 'item' },
    grid: GRID,
    xAxis: { type: 'category', data: labels.map(String), axisLine: { lineStyle: { color: AXIS_COLOR } } },
    yAxis: {
      type: 'value',
      name: 'Team-week score',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: [{ name: 'Weekly scores', type: 'boxplot', data: boxes }],
  }
}

/** Positional share of started points per season as a stacked area. */
export function positionalShareOption(labels: number[], series: ChartSeries[]): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: AXIS_COLOR } },
    grid: GRID,
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels.map(String),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
    },
    yAxis: {
      type: 'value',
      name: '% of started points',
      max: 100,
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: series.map((s) => ({
      name: s.name,
      type: 'line',
      stack: 'total',
      areaStyle: {},
      smooth: true,
      symbol: 'none',
      data: s.data,
    })),
  }
}

/** Head-to-head win% heatmap. cell null => diagonal / no games. */
export function h2hHeatmapOption(
  labels: string[],
  cells: Array<[number, number, number]>,
): EChartsOption {
  return {
    tooltip: { position: 'top' },
    grid: { left: 90, right: 24, top: 24, bottom: 90 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 45, color: AXIS_COLOR },
      splitArea: { show: true },
    },
    yAxis: { type: 'category', data: labels, axisLabel: { color: AXIS_COLOR }, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#e15759', '#edc948', '#59a14f'] },
      textStyle: { color: AXIS_COLOR },
    },
    series: [
      {
        name: 'Win %',
        type: 'heatmap',
        data: cells,
        label: { show: false },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.4)' } },
      },
    ],
  }
}

/** Median season points by draft round — the value curve. */
export function roundValueCurveOption(labels: number[], series: ChartSeries[]): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: GRID,
    xAxis: {
      type: 'category',
      name: 'Round',
      data: labels.map(String),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
    },
    yAxis: {
      type: 'value',
      name: 'Median points',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.15)' } },
    },
    series: series.map((s) => ({
      name: s.name,
      type: 'line',
      smooth: true,
      symbolSize: 7,
      data: s.data,
      lineStyle: { width: 3 },
    })),
  }
}

/** ADP (x) vs actual season points (y). Points below the diagonal are reaches. */
export function adpScatterOption(points: number[][]): EChartsOption {
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: unknown) => {
        const d = (p as { data: number[] }).data
        return `ADP ${d[0]}<br/>Points ${d[1]}<br/>Over replacement ${d[2]}`
      },
    },
    grid: GRID,
    xAxis: {
      type: 'value',
      name: 'ADP (draft slot)',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.12)' } },
    },
    yAxis: {
      type: 'value',
      name: 'Season points',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.12)' } },
    },
    series: [
      {
        type: 'scatter',
        symbolSize: 8,
        data: points,
        itemStyle: {
          // Green = returned value over replacement, red = below.
          color: (p: unknown) => {
            const d = (p as { data: number[] }).data
            return d[2] >= 0 ? '#59a14f' : '#e15759'
          },
        },
      },
    ],
  }
}

/** Draft value quadrant: cost (overall pick, x) vs outcome (PoR, y).
 * data rows: [overall_pick, por, player_name, manager_label, quadrant]. */
export function draftQuadrantOption(
  rows: Array<[number, number, string, string, string]>,
  medianPick: number,
): EChartsOption {
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: unknown) => {
        const d = (p as { data: [number, number, string, string, string] }).data
        return `${d[2]} (${d[3]})<br/>Pick ${d[0]} — ${d[1] >= 0 ? '+' : ''}${d[1]} over repl.<br/>${d[4]}`
      },
    },
    grid: GRID,
    xAxis: {
      type: 'value',
      name: 'Overall pick',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Points over replacement',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.12)' } },
    },
    series: [
      {
        type: 'scatter',
        symbolSize: 8,
        data: rows,
        itemStyle: {
          color: (p: unknown) => {
            const d = (p as { data: [number, number] }).data
            return d[1] >= 0 ? '#59a14f' : '#e15759'
          },
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: AXIS_COLOR, type: 'dashed' },
          label: { show: false },
          data: [{ yAxis: 0 }, { xAxis: medianPick }],
        },
      },
    ],
  }
}

/** Season playoff race: cumulative wins per manager. Playoff teams in color,
 * the champion emphasized, the rest muted — the story is the divergence. */
export function seasonRaceOption(
  weeks: number[],
  teams: Array<{ label: string; totals: number[]; madePlayoffs: boolean; isChampion: boolean }>,
): EChartsOption {
  const PALETTE = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#b07aa1', '#76b7b2', '#edc948']
  let colorIdx = 0
  return {
    tooltip: { trigger: 'axis' },
    grid: GRID,
    xAxis: {
      type: 'category',
      name: 'Week',
      data: weeks.map(String),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
    },
    yAxis: {
      type: 'value',
      name: 'Cumulative wins',
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      splitLine: { lineStyle: { color: 'rgba(150,150,150,0.12)' } },
    },
    series: teams.map((t) => {
      const color = t.madePlayoffs ? PALETTE[colorIdx++ % PALETTE.length] : '#9aa0a6'
      return {
        type: 'line' as const,
        name: t.label,
        data: t.totals,
        smooth: false,
        symbol: 'none',
        lineStyle: {
          width: t.isChampion ? 3.5 : t.madePlayoffs ? 2 : 1,
          color,
          opacity: t.madePlayoffs ? 1 : 0.45,
        },
        itemStyle: { color },
        emphasis: { focus: 'series' as const },
      }
    }),
  }
}
