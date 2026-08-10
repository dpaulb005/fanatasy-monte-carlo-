import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// Views are lazy-loaded so each page is its own chunk (code splitting).
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
  {
    path: '/seasons/:year',
    name: 'season',
    component: () => import('../views/SeasonView.vue'),
    props: true,
  },
  {
    path: '/managers/:id',
    name: 'manager',
    component: () => import('../views/ManagerView.vue'),
    props: true,
  },
  {
    path: '/managers/:id/card',
    name: 'manager-card',
    component: () => import('../views/ManagerCardView.vue'),
    props: true,
  },
  { path: '/rivalries', name: 'rivalries', component: () => import('../views/RivalriesView.vue') },
  {
    path: '/rivalries/:a/:b',
    name: 'rivalry-pair',
    component: () => import('../views/RivalryPairView.vue'),
    props: true,
  },
  { path: '/drafts', name: 'drafts', component: () => import('../views/DraftsView.vue') },
  {
    path: '/drafts/patterns',
    name: 'draft-patterns',
    component: () => import('../views/DraftPatternsView.vue'),
  },
  {
    path: '/drafts/suggester',
    name: 'draft-suggester',
    component: () => import('../views/DraftSuggesterView.vue'),
  },
  { path: '/setup', name: 'setup', component: () => import('../views/SetupView.vue') },
  { path: '/players', name: 'players', component: () => import('../views/PlayersView.vue') },
  {
    path: '/players/:id',
    name: 'player',
    component: () => import('../views/PlayerDetailView.vue'),
    props: true,
  },
  { path: '/trends', name: 'trends', component: () => import('../views/TrendsView.vue') },
  {
    path: '/hall-of-fame',
    name: 'hall-of-fame',
    component: () => import('../views/HallOfFameView.vue'),
  },
  { path: '/museum', name: 'museum', component: () => import('../views/MuseumView.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
