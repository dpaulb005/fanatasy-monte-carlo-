<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
// Registers the ECharts modules we use. Importing here (not in main.ts) keeps
// the charting library out of the initial bundle for chart-free routes.
import '../charts/echarts'

const props = defineProps<{ option: EChartsOption; height?: string }>()
const style = computed(() => ({ height: props.height ?? '320px', width: '100%' }))
</script>

<template>
  <VChart
    :option="option"
    :style="style"
    autoresize
  />
</template>
