import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  ApiError,
  getLeagueOverview,
  getManagers,
  type LeagueOverview,
  type ManagerCareerRow,
} from '../api/client'

// League-level state: overview + the career table (loaded once, reused).
export const useLeagueStore = defineStore('league', () => {
  const overview = ref<LeagueOverview | null>(null)
  const managers = ref<ManagerCareerRow[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [ov, mgrs] = await Promise.all([getLeagueOverview(), getManagers()])
      overview.value = ov
      managers.value = mgrs
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : 'Unknown error'
    } finally {
      loading.value = false
    }
  }

  return { overview, managers, loading, error, load }
})
