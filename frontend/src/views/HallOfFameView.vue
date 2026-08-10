<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  getAwards,
  getRecords,
  ApiError,
  type LeagueAwards,
  type RecordBook,
} from '../api/client'
import AwardCard from '../components/AwardCard.vue'

const awards = ref<LeagueAwards | null>(null)
const records = ref<RecordBook | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    ;[awards.value, records.value] = await Promise.all([getAwards(), getRecords()])
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
  <section v-else-if="awards && records">
    <h1>Hall of Fame &amp; Shame</h1>
    <p class="notice">
      Season superlatives and all-time records — every one derived from real data.
    </p>

    <template v-if="awards.all_time.length">
      <h2>All-time</h2>
      <div class="award-grid">
        <AwardCard
          v-for="a in awards.all_time"
          :key="a.slug"
          :award="a"
        />
      </div>
    </template>

    <template
      v-for="season in awards.seasons"
      :key="season.year"
    >
      <h2 style="margin-top: 2rem">
        {{ season.year }}
      </h2>
      <div class="award-grid">
        <AwardCard
          v-for="a in season.awards"
          :key="a.slug"
          :award="a"
        />
      </div>
    </template>

    <h2 style="margin-top: 2.5rem">
      Record book
    </h2>
    <div class="record-columns">
      <div>
        <h3>Most points (season)</h3>
        <ol>
          <li
            v-for="r in records.most_points_season"
            :key="r.manager.id + '' + r.year"
          >
            <RouterLink :to="`/managers/${r.manager.id}`">
              {{ r.manager.label }}
            </RouterLink>
            — {{ r.value.toFixed(0) }} ({{ r.year }})
          </li>
        </ol>
      </div>
      <div>
        <h3>Luckiest seasons</h3>
        <ol>
          <li
            v-for="r in records.luckiest_seasons"
            :key="r.manager.id + '' + r.year"
          >
            <RouterLink :to="`/managers/${r.manager.id}`">
              {{ r.manager.label }}
            </RouterLink>
            — +{{ r.value.toFixed(1) }} ({{ r.year }})
          </li>
        </ol>
      </div>
      <div>
        <h3>Biggest bench disasters</h3>
        <ol>
          <li
            v-for="r in records.biggest_bench_disasters"
            :key="r.manager.id + '' + r.year"
          >
            <RouterLink :to="`/managers/${r.manager.id}`">
              {{ r.manager.label }}
            </RouterLink>
            — {{ r.value.toFixed(0) }} ({{ r.year }})
          </li>
        </ol>
      </div>
    </div>
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>
