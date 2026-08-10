<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getMuseum, ApiError, type Museum } from '../api/client'

const museum = ref<Museum | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    museum.value = await getMuseum()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
})

function gameLabel(entry: { year: number | null; week: number | null }): string {
  if (entry.year == null) return 'career'
  return entry.week == null ? `${entry.year}` : `Wk ${entry.week}, ${entry.year}`
}

function scoreLabel(entry: { score: number | null; opponent_score: number | null }): string {
  if (entry.score == null || entry.opponent_score == null) return '—'
  return `${entry.score.toFixed(1)}–${entry.opponent_score.toFixed(1)}`
}
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else-if="museum">
    <h1>Museum of Pain</h1>
    <p class="notice">
      A curated archive of the league's worst moments — every exhibit is a documented
      formula over real games, with the evidence attached.
    </p>

    <div
      v-for="exhibit in museum.exhibits"
      :key="exhibit.slug"
      style="margin-top: 2rem"
    >
      <h2>{{ exhibit.title }}</h2>
      <p style="color: var(--text-dim); font-size: 0.9rem; margin: 0.25rem 0 0.75rem">
        {{ exhibit.formula }}
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th><th>Victim</th><th>Opponent</th><th>Game</th><th>Score</th><th>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(entry, i) in exhibit.entries"
            :key="`${exhibit.slug}-${i}`"
          >
            <td>{{ i + 1 }}</td>
            <td>{{ entry.manager }}</td>
            <td>{{ entry.opponent }}</td>
            <td>{{ gameLabel(entry) }}</td>
            <td>{{ scoreLabel(entry) }}</td>
            <td style="color: #e15759">
              {{ entry.value < 1 ? entry.value.toFixed(2) : entry.value.toFixed(1) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <p
    v-else
    class="notice"
  >
    Loading…
  </p>
</template>
