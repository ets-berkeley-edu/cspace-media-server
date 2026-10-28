<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <h1 id="page-title" class="text-h5">{{ museumName(museum) }} Audit log</h1>
      <v-spacer />
      <v-btn
        id="export-audit"
        variant="outlined"
        :href="api.auditExportUrl(museum)"
        download
      >
        Export CSV
      </v-btn>
    </div>
    <p class="mb-4">
      Every admin action, the ETL's calls that change something and each refresh's outcome, of the last 30 days,
      newest first. Click a column's name to sort by it; hover over it for what it holds. "Export CSV" saves every entry
      this museum keeps, for as long as its audit retention (on the Settings page). The file holds admins' usernames and
      reasons: keep it as carefully as the log.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="audit-table"
      :headers="headers"
      :items="entries"
      :sort-by="table.sortBy"
      must-sort
      :items-per-page="table.itemsPerPage"
      :page="table.page"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      density="compact"
      no-data-text="Nothing recorded in the last 30 days."
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
      <template #[`item.action`]="{item}">{{ actionWords(item.action) }}</template>
      <template #[`item.target`]="{item}">
        <span class="audit-target">
          <RefreshLink v-if="REFRESH_ID.test(item.target)" :id="item.target" />
          <span v-else-if="isCsid(item.target)" class="text-no-wrap">
            <router-link class="mono" :to="{name: 'lookup', params: {museum}, query: {q: item.target}}" :title="`Media look up: ${item.target}`">{{ short(item.target) }}</router-link>
            <CopyButton :value="item.target" label="CSID" />
          </span>
          <router-link v-else-if="item.action === 'settings_change'" class="mono" :to="{name: 'settings', params: {museum}}">{{ item.target }}</router-link>
          <router-link v-else-if="alertStillListed(item)" :to="{name: 'alerts', params: {museum}}">{{ targetOf(item.action, item.target) }}</router-link>
          <template v-else>{{ targetOf(item.action, item.target) }}</template>
        </span>
      </template>
      <template #[`item.details`]="{item}">
        <div class="audit-details">
          <div v-for="line in detailLines(item.details)" :key="line.label">
            {{ line.label }}:
            <RefreshLink v-if="line.label === 'Refresh' && REFRESH_ID.test(line.value)" :id="line.value" />
            <span v-else-if="line.full" class="text-no-wrap"><span class="mono" :title="line.full">{{ line.value }}</span><CopyButton :value="line.full" :label="line.label" /></span>
            <template v-else>{{ line.value }}</template>
          </div>
        </div>
      </template>
    </v-data-table>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onActivated, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {AuditEntry} from '@/api'
import {api, problem} from '@/api'
import ColumnHeader from '@/components/ColumnHeader.vue'
import CopyButton from '@/components/CopyButton.vue'
import LoadError from '@/components/LoadError.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import WhenText from '@/components/WhenText.vue'
import {PAGE_SIZES, REFRESH_ID, actionWords, detailLines, isCsid, short, targetOf} from '@/words'
import {useTableState} from '@/tableState'

// Sortable: time, by, action and target; the details aren't (D94). "By", not "Admin": the ETL and Serena act too.
const headers = [
  {title: 'When (UTC)', key: 'at', help: 'When it happened, in UTC.'},
  {title: 'By', key: 'by', help: 'Who did it: an admin (their CollectionSpace username), the ETL, or Serena (a refresh\'s outcome, or a recall a refresh ended).'},
  {title: 'Action', key: 'action', help: 'What was done.'},
  {title: 'Target', key: 'target', help: 'What it was done to: a Media CSID (opens Media look up; ⧉ copies it), a refresh (opens it), a setting, or an alert (opens Alerts while it\'s there, for 30 days).'},
  {title: 'Details', key: 'details', sortable: false, help: 'The rest: reasons, counts, values before and after. ⧉ copies a whole SHA-256.'}
]

const route = useRoute()
const table = useTableState('', 'at') // its place in the address (October 14, 2026)
// Kept alive, one per museum (App.vue): always this museum's, whichever page the address shows now.
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const entries = ref<AuditEntry[]>([])
const loaded = ref(false)
const error = ref('')

// An acknowledged alert opens the Alerts page only while that page still lists it: the last 30 days (D158). Its key
// starts with its refresh date, the day it was raised; the acknowledgement's time stands in for a key without one.
const DAYS_LISTED = 30
function alertStillListed(entry: AuditEntry): boolean {
  if (entry.action !== 'alert_acknowledge') {
    return false
  }
  const day = entry.target.split('#')[0]
  const raised = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(day) ? `${day}T12:00:00Z` : entry.at)
  return Date.now() - raised < DAYS_LISTED * 24 * 60 * 60 * 1000
}

async function load() {
  const m = museum.value
  loaded.value = false
  error.value = ''
  try {
    entries.value = (await api.audit(m)).entries
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}

watch(museum, load, {immediate: true})

// Kept alive (App.vue): coming back shows it as it was, with anything new since.
let shown = false
onActivated(() => {
  if (shown) {
    void load()
  }
  shown = true
})
</script>

<style scoped>
.audit-target,
.audit-details {
  overflow-wrap: anywhere;
}
.mono {
  font-family: monospace;
}
</style>
