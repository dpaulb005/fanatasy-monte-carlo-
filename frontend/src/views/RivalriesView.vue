<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getH2HMatrix, ApiError, type H2HMatrix } from '../api/client'
import BaseChart from '../components/BaseChart.vue'
import { h2hHeatmapOption } from '../charts/options'

const router = useRouter()
const data = ref<H2HMatrix | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    data.value = await getH2HMatrix()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
})

// Click a heatmap cell -> open that rivalry pair page.
function onCellClick(params: { data?: number[] }) {
  const managers = data.value?.managers
  if (!managers || !params.data) return
  const [col, row] = params.data // [opponent index, manager index]
  const a = managers[row]?.id
  const b = managers[col]?.id
  if (a && b && a !== b) router.push(`/rivalries/${a}/${b}`)
}

const option = computed(() => {
  if (!data.value) return null
  const labels = data.value.managers.map((m) => m.label)
  const cells: Array<[number, number, number]> = []
  data.value.matrix.forEach((row, i) => {
    row.forEach((cell, j) => {
      if (cell && cell.win_pct !== null) {
        // x = opponent (col j), y = manager (row i)
        cells.push([j, i, Math.round(cell.win_pct * 100)])
      }
    })
  })
  return h2hHeatmapOption(labels, cells)
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
  <section v-else-if="option">
    <h1>Rivalries</h1>
    <p class="notice">
      Head-to-head win rate for each manager (row) against every opponent (column). Greener = the
      row manager owns the matchup. Click a cell to open the rivalry.
    </p>
    <BaseChart
      :option="option"
      height="520px"
      @click="onCellClick"
    />
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>
