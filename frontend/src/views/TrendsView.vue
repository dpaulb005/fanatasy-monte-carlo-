<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getTrends, ApiError, type LeagueTrends } from '../api/client'
import BaseChart from '../components/BaseChart.vue'
import {
  scoringEvolutionOption,
  weeklyBoxplotOption,
  positionalShareOption,
} from '../charts/options'

const trends = ref<LeagueTrends | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    trends.value = await getTrends()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
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
  <section v-else-if="trends">
    <h1>League Trends</h1>

    <h2>Scoring evolution</h2>
    <p class="notice">
      Mean weekly team score per season — is the league getting higher-scoring?
    </p>
    <BaseChart
      :option="scoringEvolutionOption(trends.scoring_evolution.labels, trends.scoring_evolution.series)"
    />

    <h2 style="margin-top: 1.5rem">
      Weekly score distribution
    </h2>
    <p class="notice">
      Spread of team-week scores per season (ceiling, floor, and the middle 50%).
    </p>
    <BaseChart
      :option="weeklyBoxplotOption(trends.weekly_distribution.labels, trends.weekly_distribution.boxes)"
    />

    <h2 style="margin-top: 1.5rem">
      Positional scarcity
    </h2>
    <p class="notice">
      Share of started points by position — where does the scoring come from?
    </p>
    <BaseChart
      :option="positionalShareOption(trends.positional_share.labels, trends.positional_share.series)"
    />
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>
