<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { getH2HPair, ApiError, type H2HPair } from '../api/client'
import StatTile from '../components/StatTile.vue'

const props = defineProps<{ a: string; b: string }>()
const pair = ref<H2HPair | null>(null)
const error = ref<string | null>(null)

async function load(a: string, b: string) {
  error.value = null
  try {
    pair.value = await getH2HPair(a, b)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(() => load(props.a, props.b))
watch(
  () => [props.a, props.b],
  ([a, b]) => load(a, b),
)

const leader = computed(() => {
  if (!pair.value) return null
  const r = pair.value.record
  if (r.a_wins > r.b_wins) return pair.value.manager_a.label
  if (r.b_wins > r.a_wins) return pair.value.manager_b.label
  return 'Even'
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
  <section v-else-if="pair">
    <RouterLink
      to="/rivalries"
      style="color: var(--accent)"
    >
      ← All rivalries
    </RouterLink>
    <h1>
      <RouterLink :to="`/managers/${pair.manager_a.id}`">
        {{ pair.manager_a.label }}
      </RouterLink>
      vs
      <RouterLink :to="`/managers/${pair.manager_b.id}`">
        {{ pair.manager_b.label }}
      </RouterLink>
    </h1>

    <div class="stat-grid">
      <StatTile
        label="All-time series"
        :value="`${pair.record.a_wins}–${pair.record.b_wins}${pair.record.ties ? '–' + pair.record.ties : ''}`"
      />
      <StatTile
        label="Series leader"
        :value="leader ?? '—'"
      />
      <StatTile
        v-if="pair.record.playoff_meetings !== undefined"
        label="Playoff meetings"
        :value="pair.record.playoff_meetings"
      />
      <StatTile
        v-if="pair.record.largest_margin !== undefined"
        label="Largest blowout"
        :value="pair.record.largest_margin.toFixed(1)"
      />
    </div>

    <table
      v-if="pair.record.a_points !== undefined"
      class="data-table"
      style="max-width: 480px"
    >
      <thead>
        <tr><th>Manager</th><th>Wins</th><th>Total points</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>{{ pair.manager_a.label }}</td>
          <td>{{ pair.record.a_wins }}</td>
          <td>{{ pair.record.a_points?.toFixed(0) }}</td>
        </tr>
        <tr>
          <td>{{ pair.manager_b.label }}</td>
          <td>{{ pair.record.b_wins }}</td>
          <td>{{ pair.record.b_points?.toFixed(0) }}</td>
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
