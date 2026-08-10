<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  getManager,
  getManagerScouting,
  ApiError,
  type ManagerProfile,
  type ScoutingReport,
} from '../api/client'
import BaseChart from '../components/BaseChart.vue'
import StatTile from '../components/StatTile.vue'
import { luckChartOption, luckDeltaOption } from '../charts/options'

const props = defineProps<{ id: string }>()
const profile = ref<ManagerProfile | null>(null)
const scouting = ref<ScoutingReport | null>(null)
const error = ref<string | null>(null)

async function load(id: string) {
  error.value = null
  try {
    const [profileData, scoutingData] = await Promise.all([
      getManager(id),
      getManagerScouting(id).catch(() => null),
    ])
    profile.value = profileData
    scouting.value = scoutingData
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

function traitDisplay(trait: { key: string; value: number }): string {
  if (trait.key === 'discipline') return `${(trait.value * 100).toFixed(1)}%`
  if (trait.key === 'self_sabotage') return `${(trait.value * 100).toFixed(0)}% of losses`
  if (trait.key === 'fortune') return `${trait.value > 0 ? '+' : ''}${trait.value.toFixed(1)} wins`
  return trait.value.toFixed(1)
}

onMounted(() => load(props.id))
watch(() => props.id, load)
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else-if="profile">
    <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 1rem">
      <h1>{{ profile.manager.label }}</h1>
      <RouterLink
        :to="`/managers/${id}/card`"
        style="color: var(--accent)"
      >
        📇 Season card
      </RouterLink>
    </div>

    <div
      v-if="profile.career"
      class="stat-grid"
    >
      <StatTile
        label="Record"
        :value="`${profile.career.wins}-${profile.career.losses}`"
      />
      <StatTile
        label="Win %"
        :value="`${(profile.career.win_pct * 100).toFixed(1)}%`"
      />
      <StatTile
        label="Titles"
        :value="profile.career.championships"
      />
      <StatTile
        label="Playoffs"
        :value="profile.career.playoff_appearances"
      />
      <StatTile
        label="Longest W streak"
        :value="profile.career.longest_win_streak"
      />
    </div>

    <template v-if="scouting">
      <h2 style="margin-top: 2rem">
        Scouting report
      </h2>
      <p
        v-if="!scouting.qualified"
        class="notice"
      >
        Sample too small — percentile ranks need at least
        {{ scouting.min_seasons }} seasons ({{ scouting.seasons }} played).
      </p>
      <div
        v-else
        style="display: grid; gap: 0.6rem; max-width: 640px"
      >
        <div
          v-for="trait in scouting.traits"
          :key="trait.key"
          :title="trait.definition"
        >
          <div style="display: flex; justify-content: space-between; font-size: 0.9rem">
            <span>{{ trait.label }}</span>
            <span style="color: var(--text-dim)">{{ traitDisplay(trait) }}</span>
          </div>
          <div style="background: var(--surface-2); border-radius: 4px; height: 8px">
            <div
              :style="{
                width: `${Math.max((trait.percentile ?? 0) * 100, 2)}%`,
                background: (trait.percentile ?? 0) >= 0.5 ? '#59a14f' : '#e15759',
                height: '8px',
                borderRadius: '4px',
              }"
            />
          </div>
        </div>
        <p style="color: var(--text-dim); font-size: 0.8rem; margin: 0.25rem 0 0">
          Bars are league percentiles among the {{ scouting.pool_size }} managers with
          {{ scouting.min_seasons }}+ seasons. Hover a trait for its definition.
        </p>
      </div>
    </template>

    <h2 style="margin-top: 2rem">
      Actual vs expected wins
    </h2>
    <BaseChart :option="luckChartOption(profile.luck_chart.labels, profile.luck_chart.series)" />

    <h2 style="margin-top: 1.5rem">
      Season luck
    </h2>
    <BaseChart
      :option="luckDeltaOption(
        profile.seasons.map((s) => s.year),
        profile.seasons.map((s) => s.luck_delta),
      )"
      height="240px"
    />

    <h2 style="margin-top: 1.5rem">
      Season by season
    </h2>
    <table class="data-table">
      <thead>
        <tr>
          <th>Year</th><th>W-L</th><th>PF</th><th>xWins</th>
          <th>Luck</th><th>Lineup eff</th>
          <th title="Losses where a legal lineup already on the roster would have won">
            Bench losses
          </th>
          <th>Finish</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="s in profile.seasons"
          :key="s.year"
        >
          <td>{{ s.year }}</td>
          <td>{{ s.wins }}-{{ s.losses }}</td>
          <td>{{ s.points_for.toFixed(0) }}</td>
          <td>{{ s.expected_wins.toFixed(1) }}</td>
          <td :style="{ color: s.luck_delta >= 0 ? '#59a14f' : '#e15759' }">
            {{ s.luck_delta > 0 ? '+' : '' }}{{ s.luck_delta.toFixed(1) }}
          </td>
          <td>{{ (s.lineup_efficiency * 100).toFixed(1) }}%</td>
          <td :style="{ color: s.bench_losses > 0 ? '#e15759' : 'inherit' }">
            {{ s.bench_losses }}
          </td>
          <td>{{ s.final_standing }}</td>
        </tr>
      </tbody>
    </table>
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>
