<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  getLeagueOverview,
  getSeasonDraft,
  ApiError,
  type SeasonDraft,
} from '../api/client'
import BaseChart from '../components/BaseChart.vue'
import { roundValueCurveOption, adpScatterOption, draftQuadrantOption } from '../charts/options'
import { classifyPick, medianOverallPick } from '../charts/quadrant'

const years = ref<number[]>([])
const selectedYear = ref<number | null>(null)
const draft = ref<SeasonDraft | null>(null)
const error = ref<string | null>(null)

async function loadDraft(year: number) {
  try {
    draft.value = await getSeasonDraft(year)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(async () => {
  try {
    const ov = await getLeagueOverview()
    years.value = ov.seasons.map((s) => s.year)
    selectedYear.value = years.value[0] ?? null
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
})

watch(selectedYear, (y) => {
  if (y) loadDraft(y)
})

// Manager filter applies to the quadrant chart and the steals table.
const managerFilter = ref('')
const managerOptions = computed(() => {
  const labels = new Set<string>()
  for (const p of draft.value?.picks ?? []) {
    if (p.manager) labels.add(p.manager.label)
  }
  return [...labels].sort()
})
const filteredPicks = computed(() =>
  (draft.value?.picks ?? []).filter(
    (p) => !managerFilter.value || p.manager?.label === managerFilter.value,
  ),
)

// Quadrant boundaries come from the FULL season (median pick, PoR 0) so a
// filtered view keeps the same frame of reference.
const quadrantOption = computed(() => {
  const all = draft.value?.picks ?? []
  const median = medianOverallPick(all)
  const rows = filteredPicks.value.map(
    (p): [number, number, string, string, string] => [
      p.overall_pick,
      p.points_over_replacement,
      p.player_name,
      p.manager?.label ?? '—',
      classifyPick(p.overall_pick, p.points_over_replacement, median),
    ],
  )
  return draftQuadrantOption(rows, median)
})

// Best value picks (highest points over replacement) for the "steals" table.
const topPicks = computed(() =>
  [...filteredPicks.value]
    .sort((a, b) => b.points_over_replacement - a.points_over_replacement)
    .slice(0, 10),
)
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else>
    <h1>Draft Intelligence</h1>
    <p class="notice">
      Retrospective draft value: how each pick actually panned out. Value is points over the
      league's own positional replacement level — history, not prediction.
    </p>

    <label style="display: inline-block; margin: 1rem 0">
      Season:
      <select
        v-model.number="selectedYear"
        style="margin-left: 0.5rem"
      >
        <option
          v-for="y in years"
          :key="y"
          :value="y"
        >{{ y }}</option>
      </select>
    </label>

    <template v-if="draft">
      <h2>Value by round</h2>
      <BaseChart
        :option="roundValueCurveOption(draft.round_value_curve.labels, draft.round_value_curve.series)"
        height="260px"
      />

      <h2 style="margin-top: 1.5rem">
        ADP vs outcome
      </h2>
      <p class="notice">
        Each dot is a pick: drafted slot (x) vs points scored (y). Green returned starter value,
        red fell below replacement.
      </p>
      <BaseChart :option="adpScatterOption(draft.scatter)" />

      <h2 style="margin-top: 1.5rem">
        Draft value quadrant
      </h2>
      <p class="notice">
        Where value actually came from: pick cost (x) vs points over replacement (y).
        The dashed cross marks the season's median pick and replacement level, splitting picks
        into early hits, late steals, early busts, and late misses.
      </p>
      <label style="display: inline-block; margin: 0 0 0.5rem">
        Manager:
        <select
          v-model="managerFilter"
          style="margin-left: 0.5rem"
        >
          <option value="">
            All
          </option>
          <option
            v-for="label in managerOptions"
            :key="label"
            :value="label"
          >{{ label }}</option>
        </select>
      </label>
      <BaseChart :option="quadrantOption" />

      <h2 style="margin-top: 1.5rem">
        Biggest steals
      </h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>Player</th><th>Pos</th><th>Pick</th><th>Manager</th>
            <th>Points</th><th>Over repl.</th><th>ADP Δ</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in topPicks"
            :key="p.overall_pick"
          >
            <td>{{ p.player_name }}</td>
            <td>{{ p.position }}</td>
            <td>{{ p.round }}.{{ p.round_pick }}</td>
            <td>
              <RouterLink
                v-if="p.manager"
                :to="`/managers/${p.manager.id}`"
              >
                {{ p.manager.label }}
              </RouterLink>
              <span v-else>—</span>
            </td>
            <td>{{ p.season_points.toFixed(0) }}</td>
            <td style="color: #59a14f">
              +{{ p.points_over_replacement.toFixed(0) }}
            </td>
            <td>{{ p.adp_delta !== null ? p.adp_delta.toFixed(0) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
</template>
