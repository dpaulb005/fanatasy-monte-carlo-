<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  getManager,
  getAwards,
  ApiError,
  type ManagerProfile,
  type LeagueAwards,
} from '../api/client'
import { buildCardSvg, downloadCardPng, type ShareCardData } from '../composables/shareCard'
import { awardEmoji, awardBlurb } from '../composables/awards'

const props = defineProps<{ id: string }>()
const profile = ref<ManagerProfile | null>(null)
const awards = ref<LeagueAwards | null>(null)
const leagueName = ref('League Lab')
const selectedYear = ref<number | null>(null)
const error = ref<string | null>(null)

async function load(id: string) {
  error.value = null
  try {
    const [p, a] = await Promise.all([getManager(id), getAwards()])
    profile.value = p
    awards.value = a
    selectedYear.value = p.seasons.length ? p.seasons[p.seasons.length - 1].year : null
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(() => load(props.id))
watch(() => props.id, load)

const cardData = computed<ShareCardData | null>(() => {
  if (!profile.value || selectedYear.value === null) return null
  const season = profile.value.seasons.find((s) => s.year === selectedYear.value)
  if (!season) return null
  // Find a headline award this manager won that season.
  const seasonAwards = awards.value?.seasons.find((s) => s.year === selectedYear.value)
  const won = seasonAwards?.awards.find((a) => a.winner?.id === profile.value?.manager.id)
  return {
    leagueName: leagueName.value,
    year: season.year,
    manager: profile.value.manager.label,
    record: `${season.wins}-${season.losses}${season.ties ? '-' + season.ties : ''}`,
    finish: `#${season.final_standing}`,
    pointsFor: season.points_for,
    luckDelta: season.luck_delta,
    lineupEfficiency: season.lineup_efficiency,
    benchPointsLost: season.bench_points_lost,
    awardEmoji: won ? awardEmoji(won.slug) : undefined,
    awardTitle: won?.title,
    awardBlurb: won ? awardBlurb(won) : undefined,
  }
})

const svg = computed(() => (cardData.value ? buildCardSvg(cardData.value) : ''))

const years = computed(() => profile.value?.seasons.map((s) => s.year) ?? [])

async function download() {
  if (!svg.value || !cardData.value) return
  await downloadCardPng(svg.value, `${cardData.value.manager}-${cardData.value.year}.png`)
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
  <section v-else-if="profile">
    <RouterLink
      :to="`/managers/${id}`"
      style="color: var(--accent)"
    >
      ← Back to profile
    </RouterLink>
    <h1>Season card</h1>
    <p class="notice">
      A shareable "Wrapped"-style recap card. Pick a season and download the PNG.
    </p>

    <div style="display: flex; gap: 1rem; align-items: center; margin: 1rem 0">
      <label>
        Season:
        <select
          v-model.number="selectedYear"
          style="margin-left: 0.5rem"
        >
          <option
            v-for="y in years"
            :key="y"
            :value="y"
          >{{ y }}</option>
        </select>
      </label>
      <button
        class="btn"
        @click="download"
      >
        Download PNG
      </button>
    </div>

    <!-- Inline SVG preview. The SVG is generated locally by buildCardSvg, which
         escapes every interpolated string, so this is not user-injectable. -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      class="card-preview"
      v-html="svg"
    />
    <!-- eslint-enable vue/no-v-html -->
  </section>
  <section
    v-else
    class="notice"
  >
    Loading…
  </section>
</template>

<style scoped>
.card-preview :deep(svg) {
  width: 100%;
  max-width: 420px;
  height: auto;
  border-radius: 12px;
  border: 1px solid var(--border);
}
.btn {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.55rem 1.1rem;
  font-size: 0.95rem;
  cursor: pointer;
}
</style>
