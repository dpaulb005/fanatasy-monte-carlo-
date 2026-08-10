<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useLeagueStore } from '../stores/league'
import StatTile from '../components/StatTile.vue'

const store = useLeagueStore()

onMounted(() => {
  if (!store.overview) store.load()
})
</script>

<template>
  <section>
    <h1>{{ store.overview?.league.name ?? 'League Lab' }}</h1>

    <p
      v-if="store.loading"
      class="notice"
    >
      Loading league…
    </p>
    <p
      v-else-if="store.error"
      class="notice"
      style="border-left-color: #e15759"
    >
      Could not reach the API: {{ store.error }}. Is the backend running and analytics computed?
    </p>

    <template v-else-if="store.overview">
      <div class="stat-grid">
        <StatTile
          label="Seasons"
          :value="store.overview.seasons.length"
        />
        <StatTile
          label="Managers"
          :value="store.managers.length"
        />
        <StatTile
          label="Reigning champ"
          :value="store.overview.seasons[0]?.champion?.manager?.label ?? '—'"
        />
      </div>

      <h2 style="margin-top: 2rem">
        Champions
      </h2>
      <table class="data-table">
        <thead>
          <tr><th>Season</th><th>Champion</th><th>Manager</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="s in store.overview.seasons"
            :key="s.year"
          >
            <td>
              <RouterLink :to="`/seasons/${s.year}`">
                {{ s.year }}
              </RouterLink>
            </td>
            <td>{{ s.champion?.team ?? '—' }}</td>
            <td>
              <RouterLink
                v-if="s.champion?.manager"
                :to="`/managers/${s.champion.manager.id}`"
              >
                {{ s.champion.manager.label }}
              </RouterLink>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <h2 style="margin-top: 2rem">
        All-time leaderboard
      </h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>Manager</th><th>W</th><th>L</th><th>Win%</th>
            <th>Titles</th><th>Playoffs</th><th>Luck</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in store.managers"
            :key="row.manager.id"
          >
            <td>
              <RouterLink :to="`/managers/${row.manager.id}`">
                {{ row.manager.label }}
              </RouterLink>
            </td>
            <td>{{ row.wins }}</td>
            <td>{{ row.losses }}</td>
            <td>{{ (row.win_pct * 100).toFixed(1) }}%</td>
            <td>{{ row.championships }}</td>
            <td>{{ row.playoff_appearances }}</td>
            <td :style="{ color: row.total_luck_delta >= 0 ? '#59a14f' : '#e15759' }">
              {{ row.total_luck_delta > 0 ? '+' : '' }}{{ row.total_luck_delta.toFixed(1) }}
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
</template>
