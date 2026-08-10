<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <nav class="app-nav">
    <RouterLink
      to="/"
      class="brand"
    >
      🏈 League Lab
    </RouterLink>
    <RouterLink to="/">
      Home
    </RouterLink>
    <RouterLink to="/trends">
      Trends
    </RouterLink>
    <RouterLink to="/rivalries">
      Rivalries
    </RouterLink>
    <RouterLink to="/drafts">
      Drafts
    </RouterLink>
    <RouterLink to="/drafts/patterns">
      Draft DNA
    </RouterLink>
    <RouterLink to="/drafts/suggester">
      Suggester
    </RouterLink>
    <RouterLink to="/players">
      Players
    </RouterLink>
    <RouterLink to="/hall-of-fame">
      Hall of Fame
    </RouterLink>
    <RouterLink to="/museum">
      Museum of Pain
    </RouterLink>
    <RouterLink to="/setup">
      Setup
    </RouterLink>
  </nav>
  <main class="app-main">
    <RouterView />
  </main>
</template>
