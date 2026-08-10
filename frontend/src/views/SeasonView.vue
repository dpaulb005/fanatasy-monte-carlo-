<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { getSeason, ApiError, type SeasonDetail } from '../api/client'
import BaseChart from '../components/BaseChart.vue'
import { seasonRaceOption } from '../charts/options'
import { cumulativeWins } from '../charts/quadrant'

const props = defineProps<{ year: string }>()
const season = ref<SeasonDetail | null>(null)
const error = ref<string | null>(null)

// The playoff race: cumulative wins per manager from the fingerprints blob,
// with playoff teams in color and the champion emphasized.
const raceOption = computed(() => {
  const fp = season.value?.fingerprints
  if (!fp) return null
  const playoffLabels = new Set(
    (season.value?.standings ?? []).filter((s) => s.made_playoffs).map((s) => s.manager.label),
  )
  const championLabel = season.value?.champion?.manager.label
  const teams = fp.teams.map((t) => ({
    label: t.manager,
    totals: cumulativeWins(fp.weeks, t.weeks),
    madePlayoffs: playoffLabels.has(t.manager),
    isChampion: t.manager === championLabel,
  }))
  return seasonRaceOption(fp.weeks, teams)
})

async function load(year: string) {
  error.value = null
  try {
    season.value = await getSeason(year)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(() => load(props.year))
watch(() => props.year, load)
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else-if="season">
    <h1>Season {{ season.year }}</h1>
    <p
      v-if="season.champion"
      class="notice"
    >
      🏆 Champion: <strong>{{ season.champion.team }}</strong> ({{ season.champion.manager.label }})
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th>#</th><th>Team</th><th>Manager</th><th>W-L</th>
          <th>PF</th><th>PA</th><th>xWins</th><th>Luck</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in season.standings"
          :key="row.rank"
          :style="{ opacity: row.made_playoffs ? 1 : 0.6 }"
        >
          <td>{{ row.rank }}</td>
          <td>{{ row.team }}</td>
          <td>
            <RouterLink :to="`/managers/${row.manager.id}`">
              {{ row.manager.label }}
            </RouterLink>
          </td>
          <td>{{ row.wins }}-{{ row.losses }}</td>
          <td>{{ row.points_for.toFixed(0) }}</td>
          <td>{{ row.points_against.toFixed(0) }}</td>
          <td>{{ row.expected_wins.toFixed(1) }}</td>
          <td :style="{ color: row.luck_delta >= 0 ? '#59a14f' : '#e15759' }">
            {{ row.luck_delta > 0 ? '+' : '' }}{{ row.luck_delta.toFixed(1) }}
          </td>
        </tr>
      </tbody>
    </table>

    <template v-if="raceOption">
      <h2 style="margin-top: 2rem">
        The playoff race
      </h2>
      <p style="color: var(--text-dim); font-size: 0.9rem; margin: 0.25rem 0 0.75rem">
        Cumulative wins week by week — playoff teams in color, the champion in bold,
        everyone else in gray. (A wins race, not official seeding — ties and points
        tiebreaks aren't shown.)
      </p>
      <BaseChart
        :option="raceOption"
        height="300px"
      />
    </template>

    <template v-if="season.fingerprints">
      <h2 style="margin-top: 2rem">
        Weekly fingerprints
      </h2>
      <p style="color: var(--text-dim); font-size: 0.9rem; margin: 0.25rem 0 0.75rem">
        Each manager's week-by-week scores (green = won, red = lost); the dashed line is the
        league's weekly median ({{ season.fingerprints.league_median.toFixed(0) }}).
        Steady or streaky at a glance.
      </p>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1rem">
        <div
          v-for="team in season.fingerprints.teams"
          :key="team.manager"
        >
          <div style="font-size: 0.85rem; margin-bottom: 2px">
            {{ team.final_standing }}. {{ team.manager }}
          </div>
          <div style="position: relative; display: flex; align-items: flex-end; gap: 2px; height: 56px">
            <div
              :style="{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: `${(season.fingerprints.league_median / season.fingerprints.max_score) * 56}px`,
                borderTop: '1px dashed var(--text-dim)',
              }"
            />
            <div
              v-for="w in team.weeks"
              :key="w.week"
              :title="`Wk ${w.week}: ${w.score.toFixed(1)} (${w.won ? 'W' : 'L'})`"
              :style="{
                flex: 1,
                height: `${Math.max((w.score / season.fingerprints.max_score) * 56, 2)}px`,
                background: w.won ? '#59a14f' : '#e15759',
                borderRadius: '1px',
              }"
            />
          </div>
        </div>
      </div>
    </template>
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>
