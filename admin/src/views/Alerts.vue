<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Alerts</h1>
    <p class="mb-4">
      Every alert of the last 30 days, newest first. Click a column's name to sort by it; hover over it for what it holds.
      A refresh ID opens that refresh. Acknowledging an alert doesn't hide a problem: if it's still there, the watchdog
      raises it again the next day.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="alerts-table"
      :headers="headers"
      :items="alerts"
      :sort-by="table.sortBy"
      must-sort
      :items-per-page="table.itemsPerPage"
      :page="table.page"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      item-value="key"
      density="compact"
      no-data-text="No alerts in the last 30 days."
      @update:sort-by="(v: {key: string, order: 'asc' | 'desc'}[]) => table.sortBy = v"
      @update:page="(v: number) => table.page = v"
      @update:items-per-page="(v: number) => table.itemsPerPage = v"
    >
      <!-- Vue 3 keys a template v-for on the template itself; BOA's rules also carry Vue 2's rule against it. -->
      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="h in headers" :key="h.key" #[`header.${h.key}`]="slot">
        <ColumnHeader v-bind="slot" :help="h.help" />
      </template>
      <template #[`item.title`]="{item}">
        <strong>{{ item.title }}</strong>
        <div class="text-body-2 alert-message">
          <span v-for="(part, i) in withRefreshes(item.message)" :key="i"><RefreshLink v-if="part.refresh" :id="part.text" /><template v-else>{{ part.text }}</template></span>
        </div>
      </template>
      <template #[`item.created_at`]="{item}"><WhenText :at="item.created_at" /></template>
      <template #[`item.subject`]="{item}">
        <RefreshLink v-if="REFRESH_ID.test(item.subject)" :id="item.subject" />
        <span v-else-if="isCsid(item.subject)" class="text-no-wrap">
          <router-link class="mono" :to="{name: 'lookup', params: {museum}, query: {q: item.subject}}" :title="`Media look up: ${item.subject}`">{{ short(item.subject) }}</router-link>
          <CopyButton :value="item.subject" label="CSID" />
        </span>
        <template v-else>{{ item.subject }}</template>
      </template>
      <template #[`item.acknowledged_at`]="{item}">
        <span v-if="item.acknowledged_at">{{ item.acknowledged_by }}, <WhenText :at="item.acknowledged_at" /></span>
        <v-btn
          v-else
          size="small"
          variant="outlined"
          @click="acknowledge(item.key)"
        >
          Acknowledge
        </v-btn>
      </template>
    </v-data-table>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onActivated, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AlertItem} from '@/api'
import {api, problem} from '@/api'
import ColumnHeader from '@/components/ColumnHeader.vue'
import CopyButton from '@/components/CopyButton.vue'
import LoadError from '@/components/LoadError.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import WhenText from '@/components/WhenText.vue'
import {alertsChanged, museumName} from '@/session'
import {PAGE_SIZES, REFRESH_ID, REFRESH_IN_TEXT, isCsid, short} from '@/words'
import {useTableState} from '@/tableState'

// Sortable: when, refresh date, alert, about and acknowledged (D94); the alert sorts by its title.
const headers = [
  {title: 'Raised', key: 'created_at', help: 'When Serena raised it (UTC). Each alert is emailed to the team once.'},
  {title: 'Refresh date', key: 'refresh_date', help: 'The refresh date it belongs to: the day, in Pacific time, of the refresh it\'s about or that was due.'},
  {title: 'Alert', key: 'title', help: 'What happened, and what to do. A refresh ID in it opens that refresh.'},
  {title: 'About', key: 'subject', help: 'The refresh, Media record or date the alert is about. A refresh opens its page; a Media CSID opens Media look up, and ⧉ copies it.'},
  {title: 'Acknowledged', key: 'acknowledged_at', help: 'Who acknowledged it and when, or a button to acknowledge it once it\'s handled.'}
]

/** An alert's message, with each refresh ID in it as a link to that refresh (D157). */
function withRefreshes(message: string): {text: string, refresh: boolean}[] {
  const parts: {text: string, refresh: boolean}[] = []
  let at = 0
  for (const found of message.matchAll(REFRESH_IN_TEXT)) {
    const start = found.index ?? 0
    if (start > at) {
      parts.push({text: message.slice(at, start), refresh: false})
    }
    parts.push({text: found[0], refresh: true})
    at = start + found[0].length
  }
  if (at < message.length) {
    parts.push({text: message.slice(at), refresh: false})
  }
  return parts
}

const route = useRoute()
const table = useTableState('', 'created_at') // its place in the address (October 14, 2026)
// Kept alive, one per museum (App.vue): always this museum's, whichever page the address shows now.
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const alerts = ref<AlertItem[]>([])
const loaded = ref(false)
const error = ref('')

async function load() {
  error.value = ''
  try {
    alerts.value = (await api.alerts(museum.value)).alerts
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}

async function acknowledge(key: string) {
  try {
    await api.acknowledge(museum.value, key)
    alertsChanged.value++
  } catch (e) {
    error.value = problem(e)
  }
}

watch([museum, alertsChanged], load, {immediate: true})

// Kept alive (App.vue): coming back shows it as it was, with any new alerts.
let shown = false
onActivated(() => {
  if (shown) {
    void load()
  }
  shown = true
})
</script>

<style scoped>
.mono {
  font-family: monospace;
}
</style>
