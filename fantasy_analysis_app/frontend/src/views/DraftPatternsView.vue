<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { getDraftPatterns, ApiError, type DraftPatterns, type DraftPatternPick } from '../api/client'

const patterns = ref<DraftPatterns | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    patterns.value = await getDraftPatterns()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Unknown error'
  }
})

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST']

function posClass(position: string): string {
  return POSITIONS.includes(position) ? `pos-${position.toLowerCase()}` : 'pos-other'
}

function posLetter(position: string): string {
  return position === 'DST' ? 'D' : position.charAt(0)
}

function pickTitle(p: DraftPatternPick): string {
  const parts = [
    `R${p.round} · #${p.overall_pick} · ${p.player_name} (${p.position})`,
    `${p.season_points.toFixed(0)} pts, ${p.points_over_replacement >= 0 ? '+' : ''}${p.points_over_replacement.toFixed(0)} over replacement`,
  ]
  if (p.adp_delta !== null) {
    parts.push(p.adp_delta <= 0 ? `reached ${-p.adp_delta} ahead of ADP` : `fell ${p.adp_delta} past ADP`)
  }
  if (p.is_keeper) parts.push('keeper')
  return parts.join(' — ')
}

type SortKey = 'name' | 'value' | 'reach'
const sortBy = ref<SortKey>('name')

const managers = computed(() => {
  const rows = [...(patterns.value?.managers ?? [])]
  if (sortBy.value === 'value') {
    rows.sort((a, b) => b.profile.avg_draft_por - a.profile.avg_draft_por)
  } else if (sortBy.value === 'reach') {
    rows.sort((a, b) => (b.profile.reach_rate ?? -1) - (a.profile.reach_rate ?? -1))
  }
  return rows
})

const pct = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(0)}%`)
const signed = (v: number | null, digits = 1) =>
  v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
</script>

<template>
  <section
    v-if="error"
    class="notice"
    style="border-left-color: #e15759"
  >
    {{ error }}
  </section>
  <section v-else-if="patterns">
    <h1>Draft DNA</h1>
    <p class="notice">
      Every manager's drafts as a sequence — each cell is one pick, colored by position — plus
      the tendencies that fall out of them: opening signature, position timing, and reach-vs-value
      habits against public ADP (Δ beyond ±{{ patterns.adp_swing_threshold }} slots counts).
    </p>

    <div class="dna-legend">
      <span
        v-for="pos in POSITIONS"
        :key="pos"
        class="legend-item"
      >
        <span
          class="dna-cell legend-swatch"
          :class="posClass(pos)"
        >{{ posLetter(pos) }}</span>
        {{ pos }}
      </span>
      <span class="legend-item">
        <span class="dna-cell legend-swatch pos-other keeper">K</span>
        keeper (dashed)
      </span>
    </div>

    <h2>Tendencies</h2>
    <table class="data-table">
      <thead>
        <tr>
          <th>Manager</th>
          <th>Opening signature</th>
          <th>First QB</th>
          <th>First TE</th>
          <th>vs ADP</th>
          <th>Reach%</th>
          <th>Value%</th>
          <th>Avg value / draft</th>
          <th title="Share of drafted players who met or beat their draft-time projection">
            Beats proj.
          </th>
          <th title="Positional runs this manager started · runs joined as a panic reach (≥5 slots ahead of ADP)">
            Runs
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="m in managers"
          :key="m.manager.id"
        >
          <td>
            <RouterLink :to="`/managers/${m.manager.id}`">
              {{ m.manager.label }}
            </RouterLink>
          </td>
          <td>
            {{ m.profile.opening.signature || '—' }}
            <span
              v-if="m.profile.opening.count"
              class="dim"
            >({{ m.profile.opening.count }}/{{ m.profile.opening.drafts }})</span>
          </td>
          <td>{{ m.profile.avg_first_round.QB ? `rd ${m.profile.avg_first_round.QB}` : '—' }}</td>
          <td>{{ m.profile.avg_first_round.TE ? `rd ${m.profile.avg_first_round.TE}` : '—' }}</td>
          <td>{{ signed(m.profile.avg_adp_delta) }}</td>
          <td>{{ pct(m.profile.reach_rate) }}</td>
          <td>{{ pct(m.profile.value_rate) }}</td>
          <td>{{ signed(m.profile.avg_draft_por, 0) }}</td>
          <td>{{ pct(m.profile.projection?.beat_rate ?? null) }}</td>
          <td>
            {{ m.profile.runs?.started ?? 0 }} started
            <span
              v-if="m.profile.runs?.panic_joins"
              class="dim"
            >· {{ m.profile.runs.panic_joins }} panic</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="notice">
      vs ADP is the average slots a pick was made after consensus (negative = habitual reacher).
      Value per draft is total points over replacement the draft class returned. Keepers are
      excluded from tendencies.
    </p>

    <template v-if="patterns.projection?.scale">
      <h2>Projection steals &amp; busts</h2>
      <p class="notice">
        Drafted players vs their draft-time projection — the league's best and worst calls,
        {{ patterns.projection.matched_picks }} picks matched.
      </p>
      <div class="proj-tables">
        <table class="data-table">
          <thead>
            <tr><th>Steal</th><th>Yr</th><th>Manager</th><th>Proj</th><th>Actual</th><th>Δ</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="e in patterns.projection.steals"
              :key="`s-${e.year}-${e.player_name}`"
            >
              <td>{{ e.player_name }} <span class="dim">{{ e.position }} r{{ e.round }}</span></td>
              <td>{{ e.year }}</td>
              <td>{{ e.manager }}</td>
              <td>{{ e.projected.toFixed(0) }}</td>
              <td>{{ e.actual.toFixed(0) }}</td>
              <td style="color: #59a14f">
                +{{ e.delta.toFixed(0) }}
              </td>
            </tr>
          </tbody>
        </table>
        <table class="data-table">
          <thead>
            <tr><th>Bust</th><th>Yr</th><th>Manager</th><th>Proj</th><th>Actual</th><th>Δ</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="e in patterns.projection.busts"
              :key="`b-${e.year}-${e.player_name}`"
            >
              <td>{{ e.player_name }} <span class="dim">{{ e.position }} r{{ e.round }}</span></td>
              <td>{{ e.year }}</td>
              <td>{{ e.manager }}</td>
              <td>{{ e.projected.toFixed(0) }}</td>
              <td>{{ e.actual.toFixed(0) }}</td>
              <td style="color: #e15759">
                {{ e.delta.toFixed(0) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-if="patterns.position_runs?.longest?.length">
      <h2>Longest position runs</h2>
      <p class="notice">
        {{ patterns.position_runs.total }} runs of {{ patterns.position_runs.min_length }}+
        consecutive same-position picks across all drafts. The first pick starts the run;
        joins flagged "panic" reached ≥{{ patterns.adp_swing_threshold }} slots ahead of ADP
        to chase it.
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>Run</th><th>Yr</th><th>Picks</th><th>Started by</th><th>The chase</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in patterns.position_runs.longest"
            :key="`${r.year}-${r.start_pick}`"
          >
            <td><strong>{{ r.length }}× {{ r.position }}</strong></td>
            <td>{{ r.year }}</td>
            <td>#{{ r.start_pick }}–{{ r.start_pick + r.length - 1 }}</td>
            <td>{{ r.picks[0].manager }}</td>
            <td class="run-chase">
              <span
                v-for="p in r.picks.slice(1)"
                :key="p.overall_pick"
                :title="`#${p.overall_pick} ${p.player_name}`"
                :class="{ 'panic-join': p.panic }"
              >{{ p.manager }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <h2>
      Sequences
      <label class="sort-label">
        Sort:
        <select v-model="sortBy">
          <option value="name">Name</option>
          <option value="value">Draft value</option>
          <option value="reach">Reach rate</option>
        </select>
      </label>
    </h2>

    <article
      v-for="m in managers"
      :key="m.manager.id"
      class="dna-card"
    >
      <h3>
        <RouterLink :to="`/managers/${m.manager.id}`">
          {{ m.manager.label }}
        </RouterLink>
        <span class="dim">
          {{ m.profile.opening.signature ? `opens ${m.profile.opening.signature}` : '' }}
        </span>
      </h3>
      <div
        v-for="d in m.drafts"
        :key="d.year"
        class="dna-row"
      >
        <span class="dna-year">{{ d.year }} <span class="dim">slot {{ d.slot }}</span></span>
        <div class="dna-strip">
          <span
            v-for="p in d.picks"
            :key="p.overall_pick"
            class="dna-cell"
            :class="[posClass(p.position), { keeper: p.is_keeper }]"
            :title="pickTitle(p)"
          >{{ posLetter(p.position) }}</span>
        </div>
        <span
          class="dna-por"
          :class="d.draft_por >= 0 ? 'pos-good' : 'pos-bad'"
        >{{ signed(d.draft_por, 0) }}</span>
      </div>
    </article>
  </section>
</template>

<style scoped>
/* Position colors validated (dataviz six checks) against both surfaces.
   QB/RB/WR/TE carry hue; K/DST are deliberately neutral. Every cell also
   carries its position letter, so color is never the only channel. */
:root,
.dna-card,
.dna-legend {
  --pos-qb: #e66767;
  --pos-rb: #199e70;
  --pos-wr: #3987e5;
  --pos-te: #eda100;
  --pos-k: #9aa0aa;
  --pos-dst: #7d8590;
  --pos-ink: #0f1115;
}

@media (prefers-color-scheme: light) {
  :root,
  .dna-card,
  .dna-legend {
    --pos-qb: #d03b3b;
    --pos-rb: #1baf7a;
    --pos-wr: #2a78d6;
    --pos-te: #eda100;
    --pos-k: #8a8f98;
    --pos-dst: #5a616b;
  }
}

.run-chase span {
  margin-right: 0.6rem;
  white-space: nowrap;
}

.run-chase .panic-join {
  color: #e15759;
  font-weight: 600;
}

.run-chase .panic-join::after {
  content: " ⚡";
}

.proj-tables {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(24rem, 1fr));
  gap: 1rem;
  align-items: start;
}

.dna-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1rem;
  margin: 0.75rem 0 1.25rem;
  color: var(--text-dim);
  font-size: 0.85rem;
  align-items: center;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.legend-swatch {
  flex: none;
  width: 20px;
}

.dna-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  margin: 0.75rem 0;
}

.dna-card h3 {
  margin: 0 0 0.5rem;
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
}

.dna-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 4px 0;
}

.dna-year {
  flex: none;
  width: 7.5rem;
  font-size: 0.85rem;
}

.dna-strip {
  display: flex;
  flex: 1;
  gap: 2px; /* the spacer: identity never rests on color alone */
  min-width: 0;
}

.dna-cell {
  flex: 1;
  min-width: 0;
  height: 26px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--pos-ink);
  cursor: default;
}

@media (prefers-color-scheme: light) {
  .pos-qb.dna-cell,
  .pos-wr.dna-cell,
  .pos-dst.dna-cell {
    color: #ffffff;
  }
}

.pos-qb { background: var(--pos-qb); }
.pos-rb { background: var(--pos-rb); }
.pos-wr { background: var(--pos-wr); }
.pos-te { background: var(--pos-te); }
.pos-k { background: var(--pos-k); }
.pos-dst { background: var(--pos-dst); }
.pos-other { background: var(--pos-k); }

.keeper {
  outline: 2px dashed var(--text);
  outline-offset: -3px;
}

.dna-por {
  flex: none;
  width: 3.5rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 0.85rem;
}

.pos-good { color: #59a14f; }
.pos-bad { color: #e15759; }

.dim {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 0.8rem;
}

.sort-label {
  font-size: 0.85rem;
  font-weight: 400;
  margin-left: 1rem;
  color: var(--text-dim);
}

.sort-label select {
  margin-left: 0.4rem;
}

@media (max-width: 700px) {
  .dna-year {
    width: 4.5rem;
  }

  .dna-cell {
    font-size: 0;
  } /* too narrow for letters; tooltip + table still carry identity */
}
</style>
