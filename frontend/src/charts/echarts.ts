// Central ECharts registration — import only the pieces we use so the bundle
// stays small (tree-shakeable core API). Chart types are added here as views
// need them (heatmap, boxplot, scatter, etc. arrive in later phases).

import { use } from 'echarts/core'
import { BarChart, BoxplotChart, HeatmapChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([
  BarChart,
  LineChart,
  BoxplotChart,
  HeatmapChart,
  ScatterChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DatasetComponent,
  VisualMapComponent,
  CanvasRenderer,
])

// Stable per-manager color assignment: every manager keeps the same color on
// every chart/page. Palette is a brand-neutral, colorblind-considerate set;
// swap per the dataviz skill when brand colors are chosen.
const MANAGER_PALETTE = [
  '#4e79a7',
  '#f28e2b',
  '#59a14f',
  '#e15759',
  '#b07aa1',
  '#76b7b2',
  '#edc948',
  '#ff9da7',
  '#9c755f',
  '#bab0ac',
  '#86bcb6',
  '#d37295',
]

export function managerColor(managerId: number): string {
  const index = Math.abs(managerId) % MANAGER_PALETTE.length
  return MANAGER_PALETTE[index]
}
