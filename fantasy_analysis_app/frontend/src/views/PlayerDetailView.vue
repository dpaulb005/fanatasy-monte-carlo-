<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  getPlayerDetail,
  ApiError,
  type PlayerDetail,
  type PlayerWeekEntry,
} from '../api/client'
import StatTile from '../components/StatTile.vue'

const props = defineProps<{ id: string }>()
const detail = ref<PlayerDetail | null>(null)
const error = ref<string | null>(null)

async function load(id: string) {
  error.value = null
  detail.value = null
  try {
    detail.value = await getPlayerDetail(id)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(() => load(props.id))
watch(() => props.id, load)

// Fixed palette; one distinct color per manager, assigned by manager id order.
const PALETTE = [
  '#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#b07aa1',
  '#76b7b2', '#edc948', '#ff9da7', '#9c755f', '#bab0ac',
]
const FALLBACK_COLOR = '#8a8f98' // rostered but manager unknown

// Single source of truth: every manager seen anywhere on the page, sorted by
// id, with a stable palette color. Legend and strip cells both derive from it.
const legend = computed(() => {
  if (!detail.value) return []
  const seen = new Map<number, string>()
  for (const row of detail.value.managers) {
    if (!seen.has(row.manager.id)) seen.set(row.manager.id, row.manager.label)
  }
  for (const season of detail.value.weekly) {
    for (const w of season.weeks) {
      if (w.manager && !seen.has(w.manager.id)) seen.set(w.manager.id, w.manager.label)
    }
  }
  return [...seen.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([id, label], i) => ({ id, label, color: PALETTE[i % PALETTE.length] ?? FALLBACK_COLOR }))
})

const managerColors = computed(() => new Map(legend.value.map((m) => [m.id, m.color])))

interface StripCell {
  week: number
  color: string
  opacity: number
  title: string
}

// Weeks 1..17 (extended if the data has later weeks), gaps filled as "not rostered".
function stripFor(year: number, weeks: PlayerWeekEntry[]): StripCell[] {
  const byWeek = new Map(weeks.map((w) => [w.week, w]))
  const maxWeek = Math.max(17, ...weeks.map((w) => w.week))
  const cells: StripCell[] = []
  for (let week = 1; week <= maxWeek; week++) {
    const entry = byWeek.get(week)
    if (!entry) {
      cells.push({
        week,
        color: 'var(--surface-2)',
        opacity: 1,
        title: `Wk ${week}, ${year} — not on a roster`,
      })
    } else {
      cells.push({
        week,
        color: entry.manager ? (managerColors.value.get(entry.manager.id) ?? FALLBACK_COLOR) : FALLBACK_COLOR,
        opacity: entry.started ? 1 : 0.4,
        title: `Wk ${week} — ${entry.points.toFixed(1)} pts, ${entry.started ? 'started' : 'benched'}, ${entry.manager?.label ?? 'unknown manager'}`,
      })
    }
  }
  return cells
}

const bestWeekLabel = computed(() => {
  const bw = detail.value?.career.best_week
  if (!bw) return '—'
  return `${bw.points.toFixed(1)} pts — wk ${bw.week}, ${bw.year}`
})
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else-if="detail">
    <h1>
      {{ detail.player.name }}
      <span style="color: var(--text-dim); font-size: 1.1rem; font-weight: normal">
        {{ detail.player.position }}
      </span>
    </h1>

    <div class="stat-grid">
      <StatTile
        label="Career points"
        :value="detail.career.total_points.toFixed(0)"
      />
      <StatTile
        label="Over replacement"
        :value="`${detail.career.points_over_replacement > 0 ? '+' : ''}${detail.career.points_over_replacement.toFixed(0)}`"
      />
      <StatTile
        label="Best pos rank"
        :value="detail.career.best_position_rank == null
          ? '—'
          : `${detail.player.position}${detail.career.best_position_rank}`"
      />
      <StatTile
        label="Weeks started/rostered"
        :value="`${detail.career.weeks_started}/${detail.career.weeks_rostered}`"
      />
      <StatTile
        label="Best week"
        :value="bestWeekLabel"
      />
    </div>

    <h2 style="margin-top: 2rem">
      Season by season
    </h2>
    <table class="data-table">
      <thead>
        <tr>
          <th>Year</th><th>Pos</th><th>Pos rank</th><th>Total pts</th>
          <th>Started pts</th><th>Bench pts</th><th>Weeks</th><th>Over repl.</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="s in detail.seasons"
          :key="s.year"
        >
          <td>
            <RouterLink :to="`/seasons/${s.year}`">
              {{ s.year }}
            </RouterLink>
          </td>
          <td>{{ s.position }}</td>
          <td>{{ s.position_rank }}</td>
          <td>{{ s.total_points.toFixed(0) }}</td>
          <td>{{ s.started_points.toFixed(0) }}</td>
          <td>{{ s.bench_points.toFixed(0) }}</td>
          <td>{{ s.weeks_started }}/{{ s.weeks_rostered }}</td>
          <td :style="{ color: s.points_over_replacement >= 0 ? '#59a14f' : '#e15759' }">
            {{ s.points_over_replacement > 0 ? '+' : '' }}{{ s.points_over_replacement.toFixed(0) }}
          </td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin-top: 2rem">
      Value by manager
    </h2>
    <p class="notice">
      A manager is credited only for the weeks this player was on their roster — mid-season
      moves split the season.
    </p>
    <table class="data-table">
      <thead>
        <tr>
          <th>Year</th><th>Manager</th><th>Points</th>
          <th>Started</th><th>Benched</th><th>Weeks</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(m, i) in detail.managers"
          :key="`${m.year}-${m.manager.id}-${i}`"
        >
          <td>{{ m.year }}</td>
          <td>
            <RouterLink :to="`/managers/${m.manager.id}`">
              {{ m.manager.label }}
            </RouterLink>
          </td>
          <td>{{ m.total_points.toFixed(0) }}</td>
          <td>{{ m.started_points.toFixed(0) }}</td>
          <td>{{ m.bench_points.toFixed(0) }}</td>
          <td>{{ m.weeks_started }}/{{ m.weeks_rostered }}</td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin-top: 2rem">
      Ownership timeline
    </h2>
    <div
      v-if="legend.length"
      class="timeline-legend"
    >
      <span
        v-for="entry in legend"
        :key="entry.id"
        class="legend-item"
      >
        <span
          class="legend-swatch"
          :style="{ background: entry.color }"
        />
        {{ entry.label }}
      </span>
    </div>
    <div
      v-for="season in detail.weekly"
      :key="season.year"
      class="timeline-row"
    >
      <span class="timeline-year">{{ season.year }}</span>
      <div class="timeline-scroll">
        <div class="timeline-strip">
          <div
            v-for="cell in stripFor(season.year, season.weeks)"
            :key="cell.week"
            class="week-cell"
            :style="{ background: cell.color, opacity: cell.opacity }"
            :title="cell.title"
          />
        </div>
      </div>
    </div>
    <p style="color: var(--text-dim); font-size: 0.85rem; margin-top: 0.5rem">
      Gray = not on a roster (free agency), muted = benched.
    </p>

    <template v-if="detail.draft_picks.length">
      <h2 style="margin-top: 2rem">
        Draft history
      </h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>Year</th><th>Pick</th><th>Overall</th><th>Keeper</th><th>Manager</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="pick in detail.draft_picks"
            :key="`${pick.year}-${pick.overall_pick}`"
          >
            <td>{{ pick.year }}</td>
            <td>{{ pick.round }}.{{ pick.round_pick }}</td>
            <td>{{ pick.overall_pick }}</td>
            <td>{{ pick.is_keeper ? 'Yes' : '—' }}</td>
            <td>
              <RouterLink
                v-if="pick.manager"
                :to="`/managers/${pick.manager.id}`"
              >
                {{ pick.manager.label }}
              </RouterLink>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>

<style scoped>
.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  color: var(--text-dim);
  font-size: 0.85rem;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.legend-swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
}

.timeline-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.4rem;
}

.timeline-year {
  width: 3rem;
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 0.85rem;
}

.timeline-scroll {
  overflow-x: auto;
  min-width: 0;
}

.timeline-strip {
  display: flex;
  gap: 3px;
  width: max-content;
}

.week-cell {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  flex-shrink: 0;
}
</style>
