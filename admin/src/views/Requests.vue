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
      request in the range; the table below lists the newest requests. Click a column's name to sort by it.
    </p>
    <LoadError :message="error" />
    <div v-if="loading" id="requests-loading" class="d-flex align-center ga-3 my-6">
      <v-progress-circular indeterminate color="primary" size="28" />
      <span>Reading Serena's log…</span>
    </div>
    <template v-if="report && !loading">
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
              <thead><tr><th>Path</th><th>Requests</th></tr></thead>
              <tbody>
                <tr v-for="p in report.top_paths" :key="p.path">
                  <td class="request-path">
                    <FileLink v-if="blobOfPath(p.path)" @open="openPath(p.path)">{{ p.path }}</FileLink>
                    <template v-else>{{ p.path }}</template>
                  </td>
                  <td>{{ p.requests }}</td>
                </tr>
                <tr v-if="!report.top_paths.length"><td colspan="2">No requests in this range.</td></tr>
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
        :sort-by="[{key: 'at', order: 'desc'}]"
        must-sort
        :items-per-page="25"
        :items-per-page-options="PAGE_SIZES"
        density="compact"
        no-data-text="No requests match."
      >
        <template #[`item.at`]="{item}"><span class="text-no-wrap">{{ when(item.at) }}</span></template>
        <template #[`item.reason`]="{item}">{{ reasonOf(item.reason) }}</template>
        <template #[`item.path`]="{item}">
          <span class="request-path" :title="item.path">
            <FileLink v-if="blobOfPath(item.path)" @open="openPath(item.path, item)">{{ middlePath(item.path) }}</FileLink>
            <template v-else>{{ middlePath(item.path) }}</template>
          </span>
        </template>
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
import FileLink from '@/components/FileLink.vue'
import LoadError from '@/components/LoadError.vue'
import {PAGE_SIZES, REQUEST_RANGES, blobOfPath, kindWord, middlePath, reasonOf, when} from '@/words'

const OUTCOMES = [{value: '', title: 'All'}, {value: 'served', title: 'Served'}, {value: 'unserved', title: 'Unserved'}]

const headers = [
  {title: 'Time', key: 'at'},
  {title: 'Outcome', key: 'outcome'},
  {title: 'Reason', key: 'reason'},
  {title: 'Path', key: 'path'},
  {title: 'Kind', key: 'kind'},
  {title: 'Cache', key: 'cache'},
  {title: 'Signed link', key: 'signed'}
]

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const range = ref<RequestRange>('24h') // D106
const outcome = ref('')
const reason = ref('')
const report = ref<RequestsReport | null>(null)
const loading = ref(false)
const error = ref('')
const file = ref<ShownFile | null>(null)

// A path opens its file in a dialog, with "Media look up" and "Dismiss" (D145).
function openPath(path: string, line?: RequestLine) {
  const found = blobOfPath(path)
  if (!found) {
    return
  }
  const outcome = line ? (line.outcome === 'served' ? 'served' : `unserved, ${reasonOf(line.reason)}`) : ''
  file.value = {
    title: found.size === 'original' ? `Original ${kindWord(line?.kind)}` : found.size,
    name: path,
    url: api.blobPreviewUrl(museum.value, found.blob, found.size),
    lookup: path,
    note: line ? `This request, ${when(line.at)}: ${outcome}.` : undefined
  }
}

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

watch([museum, range], async ([m, r]) => {
  loading.value = true
  error.value = ''
  reason.value = ''
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
.request-path {
  white-space: nowrap;
}
</style>
