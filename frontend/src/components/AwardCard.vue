<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { AwardEntry } from '../api/client'
import { awardEmoji, awardBlurb } from '../composables/awards'

const props = defineProps<{ award: AwardEntry }>()
const emoji = computed(() => awardEmoji(props.award.slug))
const blurb = computed(() => awardBlurb(props.award))
</script>

<template>
  <div class="award-card">
    <div class="award-emoji">
      {{ emoji }}
    </div>
    <div class="award-body">
      <div class="award-title">
        {{ award.title }}
      </div>
      <div class="award-winner">
        <RouterLink
          v-if="award.winner"
          :to="`/managers/${award.winner.id}`"
        >
          {{ award.winner.label }}
        </RouterLink>
        <span v-else>—</span>
      </div>
      <div class="award-blurb">
        {{ blurb }}
      </div>
    </div>
  </div>
</template>
