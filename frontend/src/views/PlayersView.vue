<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { getPlayers, ApiError, type PlayersResponse } from '../api/client'

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'DST', 'K']

const data = ref<PlayersResponse | null>(null)
const error = ref<string | null>(null)
const seasons = computed(() => data.value?.available_seasons ?? [])

// null = all-time (career mode)
const selectedSeason = ref<number | null>(null)
// '' = all positions
const position = ref('')
const search = ref('')
const sort = ref<'por' | 'points'>('por')

// Monotonic request id: a stale (slower, earlier) response must never
// overwrite the result of the latest filter state.
let requestSeq = 0

async function load() {
  error.value = null
  const seq = ++requestSeq
  try {
    const response = await getPlayers({
      season: selectedSeason.value,
      position: position.value || undefined,
      sort: sort.value,
      q: search.value.trim() || undefined,
    })
    if (seq !== requestSeq) return
    data.value = response
  } catch (err) {
    if (seq !== requestSeq) return
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(load)
watch([selectedSeason, position, sort], load)

// Debounce name search so we don't hit the API on every keystroke.
let debounceTimer: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(load, 300)
})
onBeforeUnmount(() => clearTimeout(debounceTimer))
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
    <h1>Player Explorer</h1>
    <p class="notice">
      Career fantasy value from every rostered week in league history — started and benched.
      Value = points over the league's own positional replacement level.
    </p>

    <div style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; margin: 1rem 0">
      <label>
        Season:
        <select
          v-model="selectedSeason"
          style="margin-left: 0.5rem"
        >
          <option :value="null">
            All-time (career)
          </option>
          <option
            v-for="y in seasons"
            :key="y"
            :value="y"
          >{{ y }}</option>
        </select>
      </label>

      <label>
        Position:
        <select
          v-model="position"
          style="margin-left: 0.5rem"
        >
          <option value="">
            All
          </option>
          <option
            v-for="pos in POSITIONS"
            :key="pos"
            :value="pos"
          >{{ pos }}</option>
        </select>
      </label>

      <label>
        Search:
        <input
          v-model="search"
          type="search"
          placeholder="Player name…"
          style="margin-left: 0.5rem"
        >
      </label>

      <label>
        Sort:
        <select
          v-model="sort"
          style="margin-left: 0.5rem"
        >
          <option value="por">
            Over repl.
          </option>
          <option value="points">
            Total points
          </option>
        </select>
      </label>
    </div>

    <template v-if="data">
      <table class="data-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Pos</th>
            <th>{{ data.mode === 'career' ? 'Seasons' : 'Pos rank' }}</th>
            <th>Total pts</th>
            <th>Started pts</th>
            <th>Bench pts</th>
            <th>Weeks</th>
            <th>Over repl.</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in data.players"
            :key="row.player.id"
          >
            <td>
              <RouterLink :to="`/players/${row.player.id}`">
                {{ row.player.name }}
              </RouterLink>
            </td>
            <td>{{ row.player.position }}</td>
            <td>{{ data.mode === 'career' ? row.seasons : row.position_rank }}</td>
            <td>{{ row.total_points.toFixed(0) }}</td>
            <td>{{ row.started_points.toFixed(0) }}</td>
            <td>{{ row.bench_points.toFixed(0) }}</td>
            <td>{{ row.weeks_started }}/{{ row.weeks_rostered }}</td>
            <td :style="{ color: row.points_over_replacement >= 0 ? '#59a14f' : '#e15759' }">
              {{ row.points_over_replacement > 0 ? '+' : '' }}{{ row.points_over_replacement.toFixed(0) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p
        v-if="data.players.length === 0"
        style="color: var(--text-dim)"
      >
        No players match these filters.
      </p>
      <p style="color: var(--text-dim); font-size: 0.85rem; margin-top: 0.75rem">
        {{ data.note }}
      </p>
    </template>
    <p
      v-else
      class="notice"
    >
      Loading…
    </p>
  </section>
</template>
