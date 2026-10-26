<template>
  <!-- From the cache or CollectionSpace (issue #96, mockup version 43): the worker's daily counts, not the page's range.
       Collapsed (to start), the totals since counting began; opened, by day, week, month or year. -->
  <v-card id="cache-counts" variant="outlined" class="mb-4">
    <div class="d-flex align-center flex-wrap ga-2 px-4 pt-3">
      <button
        id="cache-counts-toggle"
        type="button"
        class="disclose text-subtitle-1"
        :aria-expanded="open"
        aria-controls="cache-counts-body"
        @click="toggle"
      >
        <v-icon :icon="open ? mdiChevronDown : mdiChevronRight" size="small" />
        From the cache or CollectionSpace
      </button>
      <v-spacer />
      <v-btn-toggle
        v-if="open"
        id="cache-counts-by"
        v-model="by"
        mandatory
        density="compact"
        variant="outlined"
        divided
      >
        <v-btn v-for="p in PERIODS" :key="p.value" :value="p.value">{{ p.title }}</v-btn>
      </v-btn-toggle>
    </div>
    <v-card-text>
      <LoadError :message="error" />
      <template v-if="counts">
        <div id="cache-counts-totals" class="d-flex flex-wrap align-center ga-4">
          <span v-if="counts.since"><strong>Since {{ longDay(counts.since) }}:</strong> {{ n(served) }} served</span>
          <span v-else>No counts yet.</span>
          <span><span class="key hit" />from the cache {{ n(counts.totals.hits) }} ({{ share(counts.totals.hits, served) }})</span>
          <span><span class="key miss" />from CollectionSpace {{ n(counts.totals.misses) }} ({{ share(counts.totals.misses, served) }})</span>
          <span>unserved {{ n(counts.totals.unserved) }}</span>
          <SplitBar :hits="counts.totals.hits" :misses="counts.totals.misses" class="totals-bar" />
        </div>
        <p v-if="counts.live_unavailable" id="cache-counts-live" class="text-medium-emphasis mt-2 mb-0">
          Today's counts couldn't be read from the log: {{ counts.live_unavailable }}
        </p>
        <div v-if="open" id="cache-counts-body">
          <p class="text-medium-emphasis mt-3 mb-2">
            Not the range above: Serena counts each day (UTC) an hour after it ends and keeps the counts; today's are read
            from the log now. Weeks start on Monday. <span class="key hit" />From the cache: served from Serena's copy (a
            hit). <span class="key miss" />From CollectionSpace: fetched just then (a miss), and cached.
          </p>
          <v-table id="cache-counts-table" density="compact">
            <thead>
              <tr>
                <th>{{ PERIODS.find(p => p.value === counts!.by)?.column }}</th>
                <th>Served</th><th>From the cache</th><th>From CollectionSpace</th><th>From the cache, %</th>
                <th class="bar-column"><span class="d-sr-only">Share</span></th><th>Unserved</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in counts.rows" :key="r.period">
                <td class="text-no-wrap">
                  {{ periodName(r, counts.by) }}
                  <span v-if="r.live" class="text-medium-emphasis">({{ counts.by === 'day' ? 'today, so far' : 'so far' }})</span>
                  <span v-else-if="r.partial" class="text-medium-emphasis">(from {{ shortDay(counts.since!) }})</span>
                </td>
                <td>{{ n(r.hits + r.misses) }}</td>
                <td>{{ n(r.hits) }}</td>
                <td>{{ n(r.misses) }}</td>
                <td>{{ share(r.hits, r.hits + r.misses) }}</td>
                <td><SplitBar :hits="r.hits" :misses="r.misses" /></td>
                <td>{{ n(r.unserved) }}</td>
              </tr>
              <tr v-if="!counts.rows.length"><td colspan="7">No counts yet.</td></tr>
            </tbody>
          </v-table>
        </div>
      </template>
    </v-card-text>
  </v-card>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {mdiChevronDown, mdiChevronRight} from '@mdi/js'
import type {CountsPeriod, PeriodCount, RequestCounts} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import SplitBar from '@/components/SplitBar.vue'
import {useQueryValue} from '@/tableState'

const props = defineProps<{museum: string}>()

const PERIODS: {value: CountsPeriod, title: string, column: string}[] = [
  {value: 'day', title: 'Day', column: 'Day (UTC)'},
  {value: 'week', title: 'Week', column: 'Week (UTC)'},
  {value: 'month', title: 'Month', column: 'Month (UTC)'},
  {value: 'year', title: 'Year', column: 'Year (UTC)'}
]
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
                'November', 'December']
// Whether the card is open is remembered in this browser, like a filter; storage may be unavailable (private mode).
const OPEN_KEY = 'serena.cacheCountsOpen'

const by = useQueryValue<CountsPeriod>('counts', 'day', ['day', 'week', 'month', 'year'])
const open = ref(readOpen())
const counts = ref<RequestCounts | null>(null)
const error = ref('')
const served = computed(() => (counts.value?.totals.hits || 0) + (counts.value?.totals.misses || 0))

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY) === 'true'
  } catch {
    return false
  }
}

function toggle() {
  open.value = !open.value
  try {
    window.localStorage.setItem(OPEN_KEY, String(open.value))
  } catch {
    // not remembered; the card still opens
  }
}

const n = (value: number) => value.toLocaleString('en-US')
const share = (part: number, whole: number) => whole ? `${Math.round(100 * part / whole)}%` : '–'
const shortDay = (day: string) => `${MONTHS[Number(day.slice(5, 7)) - 1].slice(0, 3)} ${Number(day.slice(8, 10))}`
const longDay = (day: string) => `${shortDay(day)}, ${day.slice(0, 4)}`

/** "2026-10-25", "2026-W43 (Oct 19 – Oct 25)", "October 2026" or "2026". */
function periodName(row: PeriodCount, period: CountsPeriod): string {
  if (period === 'week') {
    return `${row.period} (${shortDay(row.first_day)} – ${shortDay(row.last_day)})`
  }
  if (period === 'month') {
    return `${MONTHS[Number(row.period.slice(5, 7)) - 1]} ${row.period.slice(0, 4)}`
  }
  return row.period
}

watch([() => props.museum, by], async ([museum, period]) => {
  error.value = ''
  try {
    counts.value = await api.requestCounts(museum, period)
  } catch (e) {
    counts.value = null
    error.value = problem(e)
  }
}, {immediate: true})
</script>

<style scoped>
.disclose {
  align-items: center;
  background: none;
  border: 0;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
  gap: 4px;
  padding: 0;
}
.totals-bar {
  flex: 1 1 160px;
  max-width: 320px;
}
.bar-column {
  min-width: 140px;
}
</style>
