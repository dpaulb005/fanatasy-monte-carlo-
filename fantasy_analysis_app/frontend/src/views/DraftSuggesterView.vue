<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getDraftSuggestions, ApiError, type DraftSuggestions } from '../api/client'

const teams = ref(12)
const slot = ref(1)
const pick = ref(1)
const position = ref('')

const data = ref<DraftSuggestions | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST']

// The user's snake picks, for one-click "jump to my pick".
const myPicks = computed(() => {
  const rounds = data.value?.rounds ?? 15
  const picks: number[] = []
  for (let r = 1; r <= rounds; r++) {
    const inRound = r % 2 === 1 ? slot.value : teams.value + 1 - slot.value
    picks.push((r - 1) * teams.value + inRound)
  }
  return picks
})

let timer: ReturnType<typeof setTimeout> | undefined

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await getDraftSuggestions({
      pick: pick.value,
      teams: teams.value,
      slot: slot.value,
      position: position.value || undefined,
      roster: mine.value.map((player) => player.name),
    })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  } finally {
    loading.value = false
  }
}

function scheduleLoad() {
  clearTimeout(timer)
  timer = setTimeout(load, 250)
}

onMounted(load)
watch([teams, slot, pick, position], scheduleLoad)

// CI bar geometry: map a pick number onto the shown board window.
const barScale = computed(() => {
  const players = data.value?.players ?? []
  if (!players.length) return { min: 1, max: 100 }
  const min = Math.min(pick.value, ...players.map((p) => p.ci80[0]))
  const max = Math.max(...players.map((p) => p.ci80[1]), pick.value + 5)
  return { min, max }
})

function xPct(value: number): number {
  const { min, max } = barScale.value
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
}

function availabilityClass(p: number | null): string {
  if (p === null) return ''
  if (p >= 0.7) return 'avail-high'
  if (p >= 0.3) return 'avail-mid'
  return 'avail-low'
}

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

// Draft Day mode: mark players off the board as the real draft happens.
// State survives refresh via localStorage (one draft at a time).
interface Marked {
  name: string
  position: string
  proj: number | null
}

const draftMode = ref(false)
const taken = ref<Marked[]>([])
const mine = ref<Marked[]>([])

function loadDraftState() {
  try {
    const raw = localStorage.getItem('draft-day-state')
    if (raw) {
      const s = JSON.parse(raw)
      // Accept the older shape (plain names) without losing a live draft.
      const revive = (arr: (string | Marked)[]) =>
        (arr ?? []).map((x) =>
          typeof x === 'string' ? { name: x, position: '—', proj: null } : x,
        )
      taken.value = revive(s.taken)
      mine.value = revive(s.mine)
      draftMode.value = s.active ?? false
    }
  } catch {
    /* corrupted state: start fresh */
  }
}
loadDraftState()

watch([taken, mine, draftMode], () => {
  localStorage.setItem(
    'draft-day-state',
    JSON.stringify({ taken: taken.value, mine: mine.value, active: draftMode.value }),
  )
  if (draftMode.value) {
    // The next overall pick is however many are off the board, plus one.
    pick.value = taken.value.length + mine.value.length + 1
    scheduleLoad()
  }
}, { deep: true })

function toMarked(name: string): Marked {
  const row = (data.value?.players ?? []).find((p) => p.player_name === name)
  return { name, position: row?.position ?? '—', proj: row?.projected_points ?? null }
}

function markGone(name: string) {
  if (!taken.value.some((m) => m.name === name)) taken.value = [...taken.value, toMarked(name)]
}

function markMine(name: string) {
  if (!mine.value.some((m) => m.name === name)) mine.value = [...mine.value, toMarked(name)]
}

function undoMark(name: string) {
  taken.value = taken.value.filter((m) => m.name !== name)
  mine.value = mine.value.filter((m) => m.name !== name)
}

function resetDraft() {
  taken.value = []
  mine.value = []
  pick.value = 1
}

const myRoster = computed(() => {
  const byPos: Record<string, string[]> = {}
  for (const m of mine.value) {
    ;(byPos[m.position] ??= []).push(m.name)
  }
  return Object.entries(byPos).sort()
})

// Risk posture (Haugh & Singal sign rule): if my average projected points per
// pick beats the room's average so far, protect the lead with floor picks;
// if I'm behind, variance is my friend — chase ceiling. Needs a few picks of
// signal before it speaks.
const riskPosture = computed(() => {
  const mineProj = mine.value.filter((m) => m.proj !== null)
  const fieldProj = [...taken.value, ...mine.value].filter((m) => m.proj !== null)
  if (mineProj.length < 2 || fieldProj.length < 6) return null
  const avg = (arr: Marked[]) => arr.reduce((s, m) => s + (m.proj ?? 0), 0) / arr.length
  const edge = avg(mineProj) - avg(fieldProj)
  if (edge >= 5) {
    return {
      lens: 'safe' as Lens,
      text: `You're outdrafting the room (+${edge.toFixed(0)} proj pts/pick). Protect it — favor floor.`,
    }
  }
  if (edge <= -5) {
    return {
      lens: 'upside' as Lens,
      text: `You're behind the room (${edge.toFixed(0)} proj pts/pick). Variance is your friend — chase ceiling.`,
    }
  }
  return {
    lens: 'board' as Lens,
    text: `Dead even with the room (${edge >= 0 ? '+' : ''}${edge.toFixed(0)} pts/pick). Draft the board.`,
  }
})

// Strategy lens: re-rank the visible board by what the drafter cares about.
type Lens = 'board' | 'sim-value' | 'title-equity' | 'roster-fit' | 'upside' | 'safe' | 'edge'
const lens = ref<Lens>('board')

const lensPlayers = computed(() => {
  const offBoard = new Set([...taken.value, ...mine.value].map((m) => m.name))
  const rows = (data.value?.players ?? []).filter((p) => !offBoard.has(p.player_name))
  if (lens.value === 'sim-value') {
    rows.sort((a, b) => (b.monte_carlo?.vor ?? -9999) - (a.monte_carlo?.vor ?? -9999))
  } else if (lens.value === 'title-equity') {
    rows.sort(
      (a, b) => (b.monte_carlo?.p_position_1 ?? -1) - (a.monte_carlo?.p_position_1 ?? -1),
    )
  } else if (lens.value === 'roster-fit') {
    rows.sort(
      (a, b) =>
        (b.monte_carlo?.roster_fit?.average_tail_lift ?? -1) -
        (a.monte_carlo?.roster_fit?.average_tail_lift ?? -1),
    )
  } else if (lens.value === 'upside') {
    rows.sort((a, b) => (b.expert?.upside ?? -1) - (a.expert?.upside ?? -1))
  } else if (lens.value === 'safe') {
    rows.sort((a, b) => (a.expert?.risk ?? 99) - (b.expert?.risk ?? 99))
  } else if (lens.value === 'edge') {
    rows.sort((a, b) => (b.expert?.edge ?? -999) - (a.expert?.edge ?? -999))
  }
  return rows
})

const gapChips = computed(() => {
  const gap = data.value?.gap_forecast
  if (!gap) return []
  return Object.entries(gap.expected_taken)
    .filter(([, n]) => n >= 0.5)
    .sort((a, b) => b[1] - a[1])
    .map(([pos, n]) => `${pos} ~${n.toFixed(1)} gone`)
})

const tierWarnings = computed(() => {
  const gap = data.value?.gap_forecast
  if (!gap) return []
  return Object.entries(gap.tier_survival)
    .filter(([, t]) => t.p_any_next < 0.6)
    .map(
      ([pos, t]) =>
        `${pos} tier ${t.tier}: ${Math.round(t.p_any_next * 100)}% chance one survives`,
    )
})

const calibrationChips = computed(() => {
  const cal = data.value?.calibration
  if (!cal) return []
  const chips: string[] = []
  for (const [pos, c] of Object.entries(cal.by_position ?? {})) {
    const dir = c.bias > 0 ? 'late' : 'early'
    chips.push(`${pos}: ${Math.abs(c.bias).toFixed(1)} ${dir} ±${c.sigma.toFixed(0)}`)
  }
  if (!chips.length && cal.overall) {
    chips.push(`overall: bias ${cal.overall.bias.toFixed(1)} ±${cal.overall.sigma.toFixed(0)}`)
  }
  return chips
})
</script>

<template>
  <section>
    <h1>Draft Suggester</h1>
    <p class="notice">
      A live decision board combining this league's real draft behavior with nflsim's shared
      season simulations. Market availability answers who will reach you; joint-distribution
      metrics answer who creates scarce value, positional-title equity, and upside with your
      roster. Simulation is model evidence, not certainty.
    </p>

    <div class="controls">
      <label>Teams <input
        v-model.number="teams"
        type="number"
        min="2"
        max="20"
      ></label>
      <label>Your slot <input
        v-model.number="slot"
        type="number"
        min="1"
        :max="teams"
      ></label>
      <label>At pick <input
        v-model.number="pick"
        type="number"
        min="1"
      ></label>
      <label>Position
        <select v-model="position">
          <option value="">
            All
          </option>
          <option
            v-for="p in POSITIONS"
            :key="p"
            :value="p"
          >{{ p }}</option>
        </select>
      </label>
    </div>

    <div class="my-picks">
      Your picks:
      <button
        v-for="p in myPicks.slice(0, 8)"
        :key="p"
        class="pick-chip"
        :class="{ active: p === pick }"
        @click="pick = p"
      >
        {{ p }}
      </button>
    </div>

    <section
      v-if="error"
      class="notice"
      style="border-left-color: #e15759"
    >
      {{ error }}
    </section>

    <template v-if="data">
      <p class="context-line">
        ADP season <strong>{{ data.adp_season }}</strong> · round {{ data.round }} ·
        <template v-if="data.next_pick">
          your next pick is <strong>#{{ data.next_pick }}</strong> ·
        </template>
        <template v-if="data.projection_season">
          projections {{ data.projection_season }} ·
        </template>
        value history through {{ data.value_season ?? '—' }}
        <template v-if="data.simulation_model">
          · nflsim {{ data.simulation_model.season }}
          <strong>{{ data.simulation_model.simulations.toLocaleString() }}</strong> seasons
          ({{ data.simulation_model.scoring }})
        </template>
        <span
          v-for="chip in calibrationChips"
          :key="chip"
          class="cal-chip"
        >{{ chip }}</span>
      </p>

      <p
        v-if="data.simulation_model && data.simulation_model.board_matches === 0"
        class="notice sim-warning"
      >
        The nflsim snapshot is loaded, but none of this board's player identities match it.
        Sync current-season ADP/projections before using simulation lenses; no values have been
        guessed across unmatched names.
      </p>

      <div
        v-if="gapChips.length || tierWarnings.length"
        class="gap-strip"
      >
        <span class="gap-title">Between your picks:</span>
        <span
          v-for="chip in gapChips"
          :key="chip"
          class="gap-chip"
        >{{ chip }}</span>
        <span
          v-for="w in tierWarnings"
          :key="w"
          class="gap-chip warn"
        >⚠︎ {{ w }}</span>
      </div>

      <div class="board-controls">
        <label class="lens-label">
          Lens:
          <select v-model="lens">
            <option value="board">Board order</option>
            <option
              v-if="data.simulation_model"
              value="sim-value"
            >Simulated scarce value</option>
            <option
              v-if="data.simulation_model"
              value="title-equity"
            >Position-title equity</option>
            <option
              v-if="data.simulation_model && mine.length"
              value="roster-fit"
            >Joint roster upside</option>
            <option value="upside">Upside</option>
            <option value="safe">Safety</option>
            <option value="edge">Expert edge</option>
          </select>
        </label>
        <button
          class="mode-btn"
          :class="{ active: draftMode }"
          @click="draftMode = !draftMode"
        >
          {{ draftMode ? '● Draft Day mode on' : 'Draft Day mode' }}
        </button>
        <button
          v-if="draftMode && (taken.length || mine.length)"
          class="mode-btn subtle"
          @click="resetDraft"
        >
          Reset ({{ taken.length + mine.length }} picks)
        </button>
      </div>

      <div
        v-if="draftMode && riskPosture"
        class="my-roster posture"
      >
        <strong>Risk posture:</strong>
        <span class="roster-group">{{ riskPosture.text }}</span>
        <button
          v-if="riskPosture.lens !== lens"
          class="mode-btn"
          @click="lens = riskPosture.lens"
        >
          Switch lens → {{ riskPosture.lens }}
        </button>
      </div>
      <div
        v-if="draftMode && myRoster.length"
        class="my-roster"
      >
        <strong>My roster:</strong>
        <span
          v-for="[pos, names] in myRoster"
          :key="pos"
          class="roster-group"
        >
          {{ pos }}: {{ names.join(', ') }}
        </span>
      </div>
      <div
        v-if="draftMode && taken.length"
        class="my-roster"
      >
        <strong>Recently gone</strong> <span class="roster-group">(click to undo):</span>
        <button
          v-for="m in taken.slice(-6)"
          :key="m.name"
          class="mode-btn subtle"
          @click="undoMark(m.name)"
        >
          {{ m.name }} ↩
        </button>
      </div>

      <table class="data-table suggest-table">
        <thead>
          <tr>
            <th v-if="draftMode" />
            <th>Player</th>
            <th>Pos</th>
            <th title="Expert sheet tier (letter) for the latest season">
              Tier
            </th>
            <th>ADP</th>
            <th class="range-col">
              Expected pick (80% CI)
            </th>
            <th>Avail. now</th>
            <th>Avail. next</th>
            <th title="Season projection with an 80% interval from this league's historical projection error">
              Projection
            </th>
            <th title="nflsim mean and 10th–90th percentile range across coherent simulated seasons">
              Sim range
            </th>
            <th title="Probability of finishing first at the position; replacement value is recalculated inside every simulated season">
              Pos. #1 · VOR
            </th>
            <th title="Average joint upper-tail lift with players already on your roster; above 1 means they boom together more often than independence predicts">
              Roster fit
            </th>
            <th title="Market ADP minus expert overall rank — positive means the room may let a ranked player fall">
              Edge
            </th>
            <th title="Expert risk / upside grades (0-10)">
              Risk · Up
            </th>
            <th title="Realized points over replacement last season">
              Last yr
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in lensPlayers"
            :key="p.player_name"
          >
            <td
              v-if="draftMode"
              class="mark-cell"
            >
              <button
                class="mark-btn gone"
                title="Drafted by another team"
                @click="markGone(p.player_name)"
              >
                ✕
              </button>
              <button
                class="mark-btn mine"
                title="My pick"
                @click="markMine(p.player_name)"
              >
                ★
              </button>
            </td>
            <td>
              {{ p.player_name }}
              <span
                v-if="p.league_history?.burned?.length"
                class="flag burned"
                :title="`Burned: ${p.league_history.burned.join(', ')} — they won't want him again`"
              >🔥</span>
              <span
                v-if="p.league_history?.loyal?.length"
                class="flag loyal"
                :title="`Their guy: ${p.league_history.loyal.join(', ')} — expect a reach`"
              >♥</span>
            </td>
            <td>{{ p.position }}</td>
            <td>
              <span
                v-if="p.expert?.tier"
                class="tier-chip"
              >{{ p.expert.tier }}</span>
              <span v-else>—</span>
            </td>
            <td>{{ p.adp.toFixed(0) }}</td>
            <td class="range-col">
              <div class="ci-track">
                <div
                  class="ci-span"
                  :style="{ left: `${xPct(p.ci80[0])}%`, width: `${Math.max(1, xPct(p.ci80[1]) - xPct(p.ci80[0]))}%` }"
                />
                <div
                  class="ci-mid"
                  :style="{ left: `${xPct(p.expected_pick)}%` }"
                />
                <div
                  class="ci-pick"
                  :style="{ left: `${xPct(data.pick)}%` }"
                />
              </div>
              <span class="ci-label">{{ p.ci80[0].toFixed(0) }}–{{ p.ci80[1].toFixed(0) }},
                exp {{ p.expected_pick.toFixed(0) }}</span>
            </td>
            <td :class="availabilityClass(p.p_available_now)">
              {{ pct(p.p_available_now) }}
            </td>
            <td :class="availabilityClass(p.p_available_next)">
              {{ pct(p.p_available_next) }}
            </td>
            <td>
              <template v-if="p.projected_points !== null">
                <strong>{{ p.projected_points.toFixed(0) }}</strong>
                <span
                  v-if="p.projected_range"
                  class="rank-dim"
                > {{ p.projected_range[0].toFixed(0) }}…{{ p.projected_range[1].toFixed(0) }}</span>
              </template>
              <span v-else>—</span>
            </td>
            <td>
              <template v-if="p.monte_carlo?.points != null">
                <strong>{{ p.monte_carlo.points.toFixed(0) }}</strong>
                <span class="rank-dim">
                  {{ p.monte_carlo.range[0]?.toFixed(0) }}…{{ p.monte_carlo.range[1]?.toFixed(0) }}
                </span>
              </template>
              <span v-else>—</span>
            </td>
            <td>
              <template v-if="p.monte_carlo?.p_position_1 != null">
                <strong>{{ pct(p.monte_carlo.p_position_1) }}</strong>
                <span class="rank-dim"> · {{ p.monte_carlo.vor?.toFixed(0) ?? '—' }}</span>
              </template>
              <span v-else>—</span>
            </td>
            <td>
              <template v-if="p.monte_carlo?.roster_fit?.average_tail_lift != null">
                <strong>{{ p.monte_carlo.roster_fit.average_tail_lift.toFixed(2) }}×</strong>
                <span class="rank-dim">
                  ρ {{ p.monte_carlo.roster_fit.average_correlation?.toFixed(2) ?? '—' }}
                </span>
              </template>
              <span v-else>—</span>
            </td>
            <td :class="{ 'edge-pos': (p.expert?.edge ?? 0) >= 5, 'edge-neg': (p.expert?.edge ?? 0) <= -5 }">
              {{ p.expert?.edge != null ? (p.expert.edge >= 0 ? '+' : '') + p.expert.edge.toFixed(0) : '—' }}
            </td>
            <td>
              <template v-if="p.expert?.risk != null">
                <span :class="p.expert.risk >= 6 ? 'risk-high' : ''">{{ p.expert.risk.toFixed(1) }}</span>
                ·
                <span :class="(p.expert.upside ?? 0) >= 8 ? 'upside-high' : ''">{{ p.expert.upside?.toFixed(1) }}</span>
              </template>
              <span v-else>—</span>
            </td>
            <td>
              {{ p.last_season ? p.last_season.points_over_replacement.toFixed(0) : '—' }}
              <span
                v-if="p.last_season"
                class="rank-dim"
              >({{ p.position }}{{ p.last_season.position_rank }})</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="notice">
        The vertical line in each bar is pick #{{ data.pick }}. A bar entirely left of it means
        the board says they're gone; availability percentages quantify exactly that. "Avail.
        next" is at your following snake pick — under ~40% means don't wait.
        Simulated VOR uses a different replacement score in every season. Roster fit is joint
        upper-tail lift, so 1.20× means the pair exceeds both players' boom thresholds 20% more
        often than their separate rates imply; it is not a causal estimate.
      </p>
    </template>
  </section>
</template>

<style scoped>
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin: 1rem 0 0.5rem;
  align-items: end;
}

.controls label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
  color: var(--text-dim);
}

.controls input,
.controls select {
  width: 6rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.my-picks {
  margin: 0.5rem 0 1rem;
  font-size: 0.85rem;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.pick-chip {
  padding: 0.15rem 0.6rem;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.8rem;
}

.pick-chip.active {
  border-color: var(--accent);
  color: var(--accent);
}

.context-line {
  font-size: 0.9rem;
  color: var(--text-dim);
}

.cal-chip {
  display: inline-block;
  margin-left: 0.5rem;
  padding: 0.05rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.75rem;
}

.range-col {
  min-width: 14rem;
}

.ci-track {
  position: relative;
  height: 10px;
  background: var(--surface-2);
  border-radius: 5px;
  overflow: hidden;
}

.ci-span {
  position: absolute;
  top: 2px;
  bottom: 2px;
  background: var(--accent);
  opacity: 0.45;
  border-radius: 3px;
}

.ci-mid {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 3px;
  margin-left: -1px;
  background: var(--accent);
}

.ci-pick {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--text);
}

.ci-label {
  font-size: 0.75rem;
  color: var(--text-dim);
}

.rank-dim {
  color: var(--text-dim);
  font-size: 0.8rem;
}

.gap-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.75rem 0 0.25rem;
  font-size: 0.85rem;
}

.sim-warning {
  border-left-color: #edc948;
}

.gap-title {
  color: var(--text-dim);
  font-weight: 600;
}

.gap-chip {
  padding: 0.2rem 0.65rem;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}

.gap-chip.warn {
  color: #e15759;
  border-color: #e15759;
}

.lens-label {
  display: inline-block;
  margin: 0.5rem 0 0;
  font-size: 0.85rem;
  color: var(--text-dim);
}

.tier-chip {
  display: inline-block;
  min-width: 1.5rem;
  text-align: center;
  padding: 0.05rem 0.4rem;
  border-radius: 7px;
  background: var(--accent-soft, rgba(10, 132, 255, 0.16));
  color: var(--accent);
  font-weight: 700;
  font-size: 0.8rem;
}

.flag {
  font-size: 0.8rem;
  cursor: help;
  margin-left: 0.15rem;
}

.flag.loyal {
  color: #e15759;
}

.edge-pos {
  color: #59a14f;
  font-weight: 600;
}

.edge-neg {
  color: #e15759;
}

.risk-high {
  color: #e15759;
}

.board-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 0.5rem 0 0;
  flex-wrap: wrap;
}

.mode-btn {
  padding: 0.35rem 0.9rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
  cursor: pointer;
  font-size: 0.85rem;
}

.mode-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft, rgba(10, 132, 255, 0.16));
}

.mode-btn.subtle {
  color: var(--text-dim);
}

.my-roster {
  margin-top: 0.6rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: var(--radius, 12px);
  background: var(--surface);
  font-size: 0.88rem;
  display: flex;
  gap: 0.9rem;
  flex-wrap: wrap;
}

.roster-group {
  color: var(--text-dim);
}

.mark-cell {
  white-space: nowrap;
}

.mark-btn {
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  cursor: pointer;
  font-size: 0.75rem;
  margin-right: 0.25rem;
  color: var(--text-dim);
}

.mark-btn.gone:hover {
  color: #e15759;
  border-color: #e15759;
}

.mark-btn.mine:hover {
  color: #59a14f;
  border-color: #59a14f;
}

.upside-high {
  color: #59a14f;
  font-weight: 600;
}

.avail-high {
  color: #59a14f;
}

.avail-mid {
  color: #edc948;
}

.avail-low {
  color: #e15759;
}
</style>
