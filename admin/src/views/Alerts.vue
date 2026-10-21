<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Alerts</h1>
    <p class="mb-4">
      Every alert of the last 30 days, newest first. Click a column's name to sort by it; hover over it for what it holds.
      A refresh ID opens that refresh. "Waiting" shows only the alerts not yet acknowledged; each has a red bar at its
      left edge. Acknowledging an alert doesn't hide a problem: if it's still there, the watchdog raises it again the
      next day.
    </p>
    <LoadError :message="error" />
    <div class="d-flex align-center flex-wrap ga-2 mb-3">
      <!-- All or only the waiting ones (D212); the bell and the banner open Waiting (D213). -->
      <v-btn-toggle
        id="alerts-show"
        v-model="show"
        mandatory
        density="compact"
        variant="outlined"
        color="primary"
        aria-label="Show"
      >
        <v-btn id="alerts-show-all" value="all">All</v-btn>
        <v-btn id="alerts-show-waiting" value="waiting">Waiting ({{ waitingAlerts.length }})</v-btn>
      </v-btn-toggle>
      <v-spacer />
      <v-btn
        v-if="waitingAlerts.length >= 2"
        id="acknowledge-all"
        variant="outlined"
        @click="confirming = true"
      >
        Acknowledge all ({{ waitingAlerts.length }})
      </v-btn>
    </div>
    <v-data-table
      id="alerts-table"
      :headers="headers"
      :items="listed"
      :row-props="rowProps"
      :sort-by="table.sortBy"
      must-sort
      :items-per-page="table.itemsPerPage"
      :page="table.page"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      item-value="key"
      density="compact"
      :no-data-text="show === 'waiting' ? 'No alerts waiting.' : 'No alerts in the last 30 days.'"
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
        <!-- A recall of several records is about "<n> Media records": it opens Recalls (Richard, October 14, 2026). -->
        <router-link v-else-if="/^[\d,]+ Media records$/.test(item.subject)" :to="{name: 'recalls', params: {museum}}">{{ item.subject }}</router-link>
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
    <!-- Acknowledge all (D207 to D211, D215 to D218): asks first, listing what it acknowledges; each alert is a link to
         its row. Only the list scrolls, so the title, the reminder and the buttons stay in view (D216). -->
    <v-dialog v-model="confirming" max-width="640">
      <v-card id="acknowledge-all-dialog">
        <v-card-title>{{ askedTitle }}</v-card-title>
        <v-card-text>
          <p v-if="asked.length < waitingAlerts.length" id="acknowledge-all-limit" class="mb-2">
            {{ waitingAlerts.length }} alerts are waiting, and one click acknowledges at most {{ MAX_ACKNOWLEDGE_ALL }}.
            These are the newest {{ asked.length }}: then click "Acknowledge all" again for the rest.
          </p>
          <p v-else class="mb-2">These are the {{ asked.length }} alerts waiting to be acknowledged, on every page of the table:</p>
          <p class="text-medium-emphasis mb-2">
            Acknowledging doesn't hide a problem: if it's still there, the watchdog raises it again the next day. Each one
            is in the audit log.
          </p>
          <ul
            id="acknowledge-all-list"
            class="pl-6"
            tabindex="0"
            aria-label="The alerts it acknowledges"
          >
            <li v-for="a in asked" :key="a.key">
              <a :href="`#alert-${a.key}`" class="alert-jump" @click.prevent="jumpTo(a.key)">{{ a.title }}</a>
              · <span v-if="isCsid(a.subject)" class="text-no-wrap"><span class="mono">{{ short(a.subject) }}</span><CopyButton :value="a.subject" label="CSID" /></span><template v-else>{{ a.subject }}</template>
              · <span class="text-no-wrap">{{ raised(a.created_at) }}</span>
            </li>
          </ul>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="confirming = false">Cancel</v-btn>
          <v-btn
            id="confirm-acknowledge-all"
            color="primary"
            variant="flat"
            :loading="acknowledging"
            @click="acknowledgeAll"
          >
            {{ asked.length < waitingAlerts.length ? `Acknowledge the newest ${asked.length}` : `Acknowledge ${asked.length}` }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, nextTick, onActivated, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AlertItem} from '@/api'
import {api, problem} from '@/api'
import ColumnHeader from '@/components/ColumnHeader.vue'
import CopyButton from '@/components/CopyButton.vue'
import LoadError from '@/components/LoadError.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import WhenText from '@/components/WhenText.vue'
import {alertsChanged, museumName} from '@/session'
import {PAGE_SIZES, REFRESH_ID, REFRESH_IN_TEXT, isCsid, short, when} from '@/words'
import {useQueryValue, useTableState} from '@/tableState'

// Sortable: when, refresh date, alert, about and acknowledged (D94); the alert sorts by its title.
const headers = [
  {title: 'Raised', key: 'created_at', help: 'When Serena raised it (UTC). Each alert is emailed to the team once.'},
  {title: 'Refresh date', key: 'refresh_date', help: 'The refresh date it belongs to: the day, in Pacific time, of the refresh it\'s about or that was due.'},
  {title: 'Alert', key: 'title', help: 'What happened, and what to do. A refresh ID in it opens that refresh.'},
  {title: 'About', key: 'subject', help: 'The refresh, Media record or date the alert is about. A refresh opens its page; a Media CSID opens Media look up, and ⧉ copies it; a recall\'s "<n> Media records" opens Recalls.'},
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

// All or Waiting (D212), in the address as show=waiting. The bell and the banner link with it (D213); any other way
// in has none, so it shows All. The page is kept alive, so it follows the address each time it's shown.
const show = useQueryValue('show', 'all', ['all', 'waiting'] as const)
const waitingAlerts = computed(() => alerts.value.filter(a => !a.acknowledged_at))
const listed = computed(() => show.value === 'waiting' ? waitingAlerts.value : alerts.value)
watch(show, () => {
  table.page = 1
  marked.value = ''
})
watch(() => route.fullPath, () => {
  if (route.name === 'alerts' && String(route.params.museum) === ownMuseum) {
    show.value = route.query.show === 'waiting' ? 'waiting' : 'all'
  }
})

// A waiting alert's row has a red bar down its left edge (D214); the row a dialog link opened is marked (D215).
const marked = ref('')
function rowProps({item}: {item: AlertItem}) {
  return {id: `alert-${item.key}`, class: [item.acknowledged_at ? '' : 'waiting', item.key === marked.value ? 'marked' : '']}
}

// Acknowledge all (D207 to D211): the alerts shown as waiting when the dialog opened, on every page of the table.
const confirming = ref(false)
const acknowledging = ref(false)
const asked = ref<AlertItem[]>([])
// One click acknowledges at most this many, the newest (D218): Serena takes no more in one request.
const MAX_ACKNOWLEDGE_ALL = 500
watch(confirming, open => {
  if (open) {
    asked.value = [...waitingAlerts.value].sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, MAX_ACKNOWLEDGE_ALL)
  }
})
const askedTitle = computed(() => asked.value.length < waitingAlerts.value.length
  ? `Acknowledge the newest ${asked.value.length} of ${waitingAlerts.value.length} alerts?`
  : `Acknowledge ${asked.value.length} alerts?`)
// When a listed alert was raised (D217): its time, and its date too unless it's today (UTC, as the table shows).
function raised(at: string): string {
  const text = when(at).replace(/:\d\d UTC$/, ' UTC')
  return text.startsWith(new Date().toISOString().slice(0, 10)) ? text.slice(11) : text
}

async function acknowledgeAll() {
  acknowledging.value = true
  try {
    await api.acknowledgeAll(museum.value, asked.value.map(a => a.key))
    confirming.value = false
    alertsChanged.value++
  } catch (e) {
    confirming.value = false
    error.value = problem(e)
  } finally {
    acknowledging.value = false
  }
}

// As the table sorts (Vuetify's sortItems): case aside, empty first, numbers as numbers, then by collation.
const collator = new Intl.Collator('en', {sensitivity: 'accent', usage: 'sort'})
function compare(x: unknown, y: unknown): number {
  const a = x === null || x === undefined ? x : String(x).toLocaleLowerCase()
  const b = y === null || y === undefined ? y : String(y).toLocaleLowerCase()
  if (a === b) {
    return 0
  }
  if (!a) {
    return b ? -1 : 0
  }
  if (!b) {
    return 1
  }
  if (!isNaN(Number(a)) && !isNaN(Number(b))) {
    return Number(a) - Number(b)
  }
  return collator.compare(a, b)
}

/** A dialog link (D215): closes the dialog and shows that alert's row, on its page, in the current view and sort. */
async function jumpTo(key: string) {
  confirming.value = false
  const sort = table.sortBy[0] || {key: 'created_at', order: 'desc'}
  const field = sort.key as keyof AlertItem
  const order = [...listed.value].sort((a, b) => sort.order === 'desc' ? compare(b[field], a[field]) : compare(a[field], b[field]))
  const at = order.findIndex(a => a.key === key)
  if (at >= 0 && table.itemsPerPage > 0) {
    table.page = Math.floor(at / table.itemsPerPage) + 1
  }
  marked.value = key
  await nextTick()
  const row = document.getElementById(`alert-${key}`)
  if (row) {
    row.setAttribute('tabindex', '-1')
    row.scrollIntoView({block: 'center'})
    row.focus()
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
/* A waiting alert (D214): a bar in the banner's colour down the row's left edge. The row a link opened (D215). */
#alerts-table :deep(tr.waiting > td:first-child) {
  box-shadow: inset 4px 0 0 rgb(var(--v-theme-error));
}
#alerts-table :deep(tr.marked > td) {
  background: rgba(var(--v-theme-primary), 0.08);
}
/* Acknowledge all's list: about 12 lines, then it scrolls on its own (D216). In a window too short for that, the
   list shrinks, not the card around it scrolling, so the title, the reminder and the buttons stay in view. */
#acknowledge-all-dialog {
  display: flex;
  flex-direction: column;
}
#acknowledge-all-dialog > :deep(.v-card-text) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
#acknowledge-all-list {
  flex: 0 1 auto;
  min-height: 3rem;
  max-height: 18rem;
  overflow-y: auto;
}
</style>
