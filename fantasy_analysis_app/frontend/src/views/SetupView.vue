<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getSetupManagers,
  saveSetupManagers,
  ApiError,
  type SetupManagerRow,
  type SetupManagerUpdate,
} from '../api/client'

const rows = ref<SetupManagerRow[]>([])
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const saving = ref(false)

interface FormRow {
  real_name: string
  email: string
  merged_into: number | null
}

const form = ref<Record<number, FormRow>>({})

function seedForm() {
  const seeded: Record<number, FormRow> = {}
  for (const r of rows.value) {
    seeded[r.id] = {
      // Predictions are prefilled; saving accepts them, editing overrides.
      real_name: r.real_name || r.predicted_real_name,
      email: r.email,
      merged_into: r.merged_into?.id ?? r.merge_suggestion?.target.id ?? null,
    }
  }
  form.value = seeded
}

async function load() {
  try {
    rows.value = (await getSetupManagers()).managers
    seedForm()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
}

onMounted(load)

function isPredictedName(r: SetupManagerRow): boolean {
  return !r.real_name && !!r.predicted_real_name
    && form.value[r.id]?.real_name === r.predicted_real_name
}

function isSuggestedMerge(r: SetupManagerRow): boolean {
  return !r.merged_into && !!r.merge_suggestion
    && form.value[r.id]?.merged_into === r.merge_suggestion.target.id
}

const dirty = computed<SetupManagerUpdate[]>(() => {
  const changes: SetupManagerUpdate[] = []
  for (const r of rows.value) {
    const f = form.value[r.id]
    if (!f) continue
    const change: SetupManagerUpdate = { id: r.id }
    if (f.real_name.trim() !== r.real_name) change.real_name = f.real_name.trim()
    if (f.email.trim() !== r.email) change.email = f.email.trim()
    if (f.merged_into !== (r.merged_into?.id ?? null)) change.merged_into = f.merged_into
    if (Object.keys(change).length > 1) changes.push(change)
  }
  return changes
})

async function save() {
  if (!dirty.value.length) return
  saving.value = true
  notice.value = null
  error.value = null
  try {
    const result = await saveSetupManagers(dirty.value)
    notice.value =
      `Saved ${result.updated} manager${result.updated === 1 ? '' : 's'}` +
      (result.merges_changed ? `, ${result.merges_changed} merge change(s)` : '') +
      (result.analytics_recomputed ? ' — analytics recomputed.' : '.')
    await load()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  } finally {
    saving.value = false
  }
}

function seasonSummary(r: SetupManagerRow): string {
  if (!r.seasons.length) return 'no teams'
  const years = r.seasons.map((s) => s.year)
  const latest = r.seasons[r.seasons.length - 1]
  const span =
    years.length === 1 ? `${years[0]}` : `${Math.min(...years)}–${Math.max(...years)}`
  return `${span} · ${years.length} season${years.length === 1 ? '' : 's'} · "${latest.team}"`
}

function mergeOptions(r: SetupManagerRow) {
  return rows.value.filter((other) => other.id !== r.id && !other.merged_into)
}
</script>

<template>
  <section>
    <h1>League Setup</h1>
    <p class="notice">
      Map each synced ESPN account to a real person. Names and duplicate-account merges are
      prefilled with the app's best guess — review, correct, and save. Emails can't come from
      ESPN, so they're yours to fill in.
    </p>

    <section
      v-if="error"
      class="notice"
      style="border-left-color: #e15759"
    >
      {{ error }}
    </section>
    <section
      v-if="notice"
      class="notice"
      style="border-left-color: #59a14f"
    >
      {{ notice }}
    </section>

    <table
      v-if="rows.length"
      class="data-table setup-table"
    >
      <thead>
        <tr>
          <th>ESPN account</th>
          <th>Real name</th>
          <th>Email</th>
          <th>Same person as</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="r in rows"
          :key="r.id"
        >
          <td>
            <div class="account-name">
              {{ r.display_name || r.guid }}
            </div>
            <div class="account-meta">
              {{ seasonSummary(r) }}
            </div>
          </td>
          <td>
            <input
              v-model="form[r.id].real_name"
              type="text"
              placeholder="Real name"
            >
            <span
              v-if="isPredictedName(r)"
              class="chip"
            >predicted</span>
          </td>
          <td>
            <input
              v-model="form[r.id].email"
              type="email"
              placeholder="name@example.com"
            >
          </td>
          <td>
            <select v-model="form[r.id].merged_into">
              <option :value="null">
                — (own person)
              </option>
              <option
                v-for="other in mergeOptions(r)"
                :key="other.id"
                :value="other.id"
              >
                {{ other.real_name || other.predicted_real_name || other.display_name }}
              </option>
            </select>
            <span
              v-if="isSuggestedMerge(r)"
              class="chip"
            >suggested</span>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="save-bar">
      <button
        :disabled="saving || !dirty.length"
        @click="save"
      >
        {{ saving ? 'Saving…' : `Save ${dirty.length || ''} change${dirty.length === 1 ? '' : 's'}` }}
      </button>
      <span
        v-if="dirty.length"
        class="account-meta"
      >Merges and renames rebuild analytics on save.</span>
    </div>
  </section>
</template>

<style scoped>
.setup-table input,
.setup-table select {
  width: 100%;
  max-width: 16rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.setup-table td {
  vertical-align: top;
}

.account-name {
  font-weight: 600;
}

.account-meta {
  color: var(--text-dim);
  font-size: 0.8rem;
}

.chip {
  display: inline-block;
  margin-top: 0.25rem;
  padding: 0.05rem 0.45rem;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  font-size: 0.7rem;
}

.save-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin: 1rem 0 2rem;
}

.save-bar button {
  padding: 0.5rem 1.25rem;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 0.95rem;
  cursor: pointer;
}

.save-bar button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
