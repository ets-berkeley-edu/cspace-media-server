<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <h1 id="page-title" class="text-h5">{{ museumName(museum) }} Past requests</h1>
      <v-spacer />
      <v-btn-toggle
        id="request-range"
        v-model="range"
        mandatory
        density="compact"
        variant="outlined"
        divided
      >
        <v-btn v-for="r in REQUEST_RANGES" :key="r.value" :value="r.value">{{ r.title }}</v-btn>
      </v-btn-toggle>
    </div>
    <p class="mb-4">
      What Serena served and couldn't serve for this museum, read from its log. Times are UTC. The counts cover every
      request in the range; the table below lists the newest requests. Click a column's name to sort by it; hover over it
      for what it holds.
    </p>
    <LoadError :message="error" />
    <div v-if="loading" id="requests-loading" class="d-flex align-center ga-3 my-6">
      <v-progress-circular indeterminate color="primary" size="28" />
      <span>Reading Serena's log…</span>
    </div>
    <template v-if="report && !loading">
      <div class="d-flex flex-wrap ga-4 mb-4">
        <v-card id="requests-served" variant="outlined" class="summary-card">
          <v-card-title class="text-subtitle-1">Served</v-card-title>
          <v-card-text>
            <div class="text-h5">{{ servedTotal.toLocaleString('en-US') }}</div>
            <!-- Every served request in the range, by size, smallest to largest (Richard, October 14, 2026). -->
            <div v-if="report.served_by_size.length" id="requests-by-size" class="text-medium-emphasis">
              by size: {{ bySize }}
            </div>
          </v-card-text>
        </v-card>
        <v-card id="requests-unserved" variant="outlined" class="summary-card">
          <v-card-title class="text-subtitle-1">Unserved</v-card-title>
          <v-card-text>
            <div class="text-h5">{{ unservedTotal.toLocaleString('en-US') }}</div>
            <div class="text-medium-emphasis">{{ unservedReasons || 'none' }}</div>
          </v-card-text>
        </v-card>
      </div>
      <div class="d-flex flex-wrap ga-4 mb-4">
        <v-card variant="outlined" class="flex-grow-1">
          <v-card-title class="text-subtitle-1">By day</v-card-title>
          <v-card-text>
            <v-table id="requests-by-day" density="compact">
              <thead>
                <tr><th>Day (UTC)</th><th>Served</th><th>Unserved</th><th>Unserved, by reason</th></tr>
              </thead>
              <tbody>
                <tr v-for="d in report.days" :key="d.day">
                  <td class="text-no-wrap">{{ d.day }}</td>
                  <td>{{ d.served }}</td>
                  <td>{{ d.unserved_total }}</td>
                  <td>{{ Object.entries(d.unserved).map(([r, n]) => `${reasonOf(r)} ${n}`).join(', ') }}</td>
                </tr>
                <tr v-if="!report.days.length"><td colspan="4">No requests in this range.</td></tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
        <v-card variant="outlined" class="flex-grow-1">
          <v-card-title class="text-subtitle-1">Most requested</v-card-title>
          <v-card-text>
            <v-table id="requests-top-paths" density="compact">
              <thead><tr><th>Blob CSID</th><th>Size</th><th>Requests</th></tr></thead>
              <tbody>
                <tr v-for="p in topPaths" :key="p.path">
                  <td><RequestPath :path="p.path" @open="openPath(p.path)" /></td>
                  <td><SizeName :size="sizeOf(p.path)" :sizes="report.sizes" /></td>
                  <td>{{ p.requests }}</td>
                </tr>
                <tr v-if="!report.top_paths.length"><td colspan="3">No requests in this range.</td></tr>
              </tbody>
            </v-table>
          </v-card-text>
        </v-card>
      </div>
      <v-alert
        v-if="report.truncated"
        id="requests-truncated"
        type="info"
        variant="tonal"
        class="mb-4"
      >
        More than {{ report.max_lines.toLocaleString('en-US') }} requests in this range: the table lists the newest
        {{ report.max_lines.toLocaleString('en-US') }}. The counts above cover them all.
      </v-alert>
      <div class="d-flex align-center flex-wrap ga-4 mb-2">
        <v-select
          id="request-outcome"
          v-model="outcome"
          :items="OUTCOMES"
          label="Outcome"
          hide-details
          style="max-width: 180px"
        />
        <v-select
          id="request-reason"
          v-model="reason"
          :items="reasons"
          label="Reason"
          hide-details
          :disabled="outcome === 'served'"
          style="max-width: 260px"
        />
        <v-spacer />
        <v-btn
          id="export-requests"
          variant="outlined"
          :href="api.requestsExportUrl(museum, range, outcome, reason)"
          download
        >
          Export CSV
        </v-btn>
      </div>
      <v-data-table
        id="requests-table"
        :headers="headers"
        :items="shown"
        :sort-by="table.sortBy"
        must-sort
        :items-per-page="table.itemsPerPage"
        :page="table.page"
        :items-per-page-options="PAGE_SIZES"
        density="compact"
        no-data-text="No requests match."
        @update:sort-by="(v: {key: string, order: 'asc' | 'desc'}[]) => table.sortBy = v"
        @update:page="(v: number) => table.page = v"
        @update:items-per-page="(v: number) => table.itemsPerPage = v"
      >
        <!-- Vue 3 keys a template v-for on the template itself; BOA's rules also carry Vue 2's rule against it. -->
        <!-- eslint-disable-next-line vue/no-v-for-template-key -->
        <template v-for="h in headers" :key="h.key" #[`header.${h.key}`]="slot">
          <ColumnHeader v-bind="slot" :help="h.help" />
        </template>
        <template #[`item.at`]="{item}"><WhenText :at="item.at" /></template>
        <template #[`item.reason`]="{item}">{{ reasonOf(item.reason) }}</template>
        <template #[`item.path`]="{item}"><RequestPath :path="item.path" @open="openPath(item.path, item)" /></template>
        <template #[`item.size`]="{item}"><SizeName :size="sizeOf(item.path)" :sizes="report.sizes" /></template>
        <template #[`item.kind`]="{item}">{{ item.kind ? kindWord(item.kind) : '' }}</template>
        <template #[`item.signed`]="{item}">{{ item.signed ? 'yes' : '' }}</template>
      </v-data-table>
    </template>
    <FileDialog :file="file" @close="file = null" />
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {RequestLine, RequestRange, RequestsReport} from '@/api'
import {api, problem} from '@/api'
import FileDialog from '@/components/FileDialog.vue'
import type {ShownFile} from '@/components/FileDialog.vue'
import ColumnHeader from '@/components/ColumnHeader.vue'
import LoadError from '@/components/LoadError.vue'
import RequestPath from '@/components/RequestPath.vue'
import SizeName from '@/components/SizeName.vue'
import WhenText from '@/components/WhenText.vue'
import {PAGE_SIZES, REQUEST_RANGES, blobOfPath, blobPathOf, kindWord, mediaPathOf, reasonOf, sizeRank, when} from '@/words'
import {useQueryValue, useTableState} from '@/tableState'

const OUTCOMES = [{value: '', title: 'All'}, {value: 'served', title: 'Served'}, {value: 'unserved', title: 'Unserved'}]

const SIZE_HELP = 'The size asked for: a derivative (Thumbnail, Medium, …) or the original file; sorts smallest to largest. (invalid): not one of this museum\'s sizes, either a mistake or a size only other museums serve.'

const HEADERS = [
  {title: 'Time', key: 'at', help: 'When the request reached Serena (UTC).'},
  {title: 'Outcome', key: 'outcome', help: 'Served: Serena sent the file. Unserved: it sent the unavailable image instead, for the reason beside it.'},
  {title: 'Reason', key: 'reason', help: 'Why an unserved request wasn\'t served. Media look up says more for any one file.'},
  {title: 'Blob CSID', key: 'path', help: 'The file asked for, by its Blob CSID, shortened. Hover for the request\'s path; click it to see the file; ⧉ copies the path. A path that isn\'t a Blob path Serena serves shows the path itself, with "(not a Blob path)".'},
  {title: 'Size', key: 'size', help: SIZE_HELP},
  {title: 'Kind', key: 'kind', help: 'The file\'s kind, from the servable list: blank only when Serena doesn\'t know the file.'},
  {title: 'Cache', key: 'cache', help: 'Hit: served from Serena\'s cached copy. Miss: fetched from CollectionSpace just then, and cached.'},
  {title: 'Signed link', key: 'signed', help: 'Yes: a restricted file served on a portal\'s signed link.'}
]

const route = useRoute()
const table = useTableState('', 'at') // its place in the address (October 14, 2026)
// Kept alive, one per museum (App.vue): always this museum's, whichever page the address shows now.
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
// The range (24 hours to start, D106) and the filters are in the address too (October 14, 2026).
const range = useQueryValue<RequestRange>('range', '24h', ['1h', '24h', '7d'])
const outcome = useQueryValue<string>('outcome', '')
const reason = useQueryValue<string>('reason', '')
const report = ref<RequestsReport | null>(null)
// The Signed link column only where a request can have one: a museum with signed access, Cinefiles (October 14, 2026).
// The Size column sorts by size, smallest to largest, then any other name (Richard, October 14, 2026).
const headers = computed(() => HEADERS.filter(h => h.key !== 'signed' || report.value?.signed_links).map(h => h.key === 'size'
  ? {...h, value: (line: RequestLine) => sizeKey(line.path)} : h))
const loading = ref(false)
const error = ref('')
const file = ref<ShownFile | null>(null)

// A path opens its file in a dialog, with "Media look up" and "Dismiss" (D145).
function openPath(path: string, line?: RequestLine) {
  const found = blobOfPath(path)
  const media = mediaPathOf(path)
  if (!found && !media) {
    return
  }
  const size = found ? found.size : media!.size
  const outcome = line ? (line.outcome === 'served' ? 'served' : `unserved, ${reasonOf(line.reason)}`) : ''
  file.value = {
    title: size === 'original' ? `Original ${kindWord(line?.kind)}` : size,
    name: path,
    // A Media URL (pull request 15, D179): the Media record's listed Blob at that size.
    url: found ? api.blobPreviewUrl(museum.value, found.blob, size) : api.previewUrl(museum.value, media!.media, size),
    lookup: path,
    note: line ? `This request, ${when(line.at)}: ${outcome}.` : undefined
  }
}

/** A path's size: the name asked for, or '' for a path that isn't a Blob or Media path. */
function sizeOf(path: string): string {
  return blobPathOf(path)?.size || mediaPathOf(path)?.size || ''
}

function sizeKey(path: string): string {
  const size = sizeOf(path)
  return `${String(sizeRank(size, report.value?.sizes || [])).padStart(3, '0')} ${size}`
}

// "Thumbnail 9 · Medium 4 · original 1": each size and its count kept together on a line.
const bySize = computed(() => (report.value?.served_by_size || [])
  .map(s => `${s.size || 'not recorded'}\u00a0${s.requests.toLocaleString('en-US')}`).join(' · '))
const topPaths = computed(() => report.value?.top_paths || [])
const servedTotal = computed(() => (report.value?.days || []).reduce((n, d) => n + d.served, 0))
const unservedTotal = computed(() => (report.value?.days || []).reduce((n, d) => n + d.unserved_total, 0))
// The range's unserved requests by reason, most first.
const unservedReasons = computed(() => {
  const counts: Record<string, number> = {}
  for (const day of report.value?.days || []) {
    for (const [r, n] of Object.entries(day.unserved)) {
      counts[r] = (counts[r] || 0) + n
    }
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([r, n]) => `${reasonOf(r)} ${n.toLocaleString('en-US')}`).join(' · ')
})

const reasons = computed(() => {
  const found = new Set((report.value?.lines || []).filter(l => l.reason).map(l => l.reason))
  return [{value: '', title: 'Any'}, ...[...found].sort().map(r => ({value: r, title: reasonOf(r)}))]
})

const shown = computed<RequestLine[]>(() => (report.value?.lines || []).filter(line =>
  (!outcome.value || line.outcome === outcome.value) && (!reason.value || line.reason === reason.value)))

watch(outcome, value => {
  if (value === 'served') {
    reason.value = ''
  }
})

watch([museum, range], async ([m, r], before) => {
  loading.value = true
  error.value = ''
  if (before?.[1] !== undefined) {
    reason.value = '' // a new range has its own reasons; the address's, on first load, stays
  }
  try {
    report.value = await api.requests(m, r)
  } catch (e) {
    report.value = null
    error.value = problem(e)
  } finally {
    loading.value = false
  }
}, {immediate: true})
</script>

<style scoped>
.summary-card {
  min-width: 240px;
}
</style>
