<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Past refreshes</h1>
    <p class="mb-4">
      This museum's daily refreshes of the last 30 days, newest first. Click a column's name to sort by it; hover over it for what it holds. Open a refresh
      to see its servable list, its checks and what an admin can do.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="refreshes-table"
      :headers="headers"
      :items="refreshes"
      :sort-by="table.sortBy"
      must-sort
      :items-per-page="table.itemsPerPage"
      :page="table.page"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      item-value="refresh_id"
      density="compact"
      no-data-text="No refreshes in the last 30 days."
      @update:sort-by="(v: {key: string, order: 'asc' | 'desc'}[]) => table.sortBy = v"
      @update:page="(v: number) => table.page = v"
      @update:items-per-page="(v: number) => table.itemsPerPage = v"
    >
      <!-- Vue 3 keys a template v-for on the template itself; BOA's rules also carry Vue 2's rule against it. -->
      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="h in headers" :key="h.key" #[`header.${h.key}`]="slot">
        <ColumnHeader v-bind="slot" :help="h.help" />
      </template>
      <template #[`item.refresh_id`]="{item}">
        <router-link :to="{name: 'refresh', params: {museum, refreshId: item.refresh_id}}">{{ item.refresh_id }}</router-link>
      </template>
      <template #[`item.refresh_date`]="{item}">
        {{ item.refresh_date }}<span v-if="item.admin_refresh_date"> (admin refresh, list for {{ item.admin_refresh_date }})</span>
      </template>
      <template #[`item.state`]="{item}"><RefreshState :state="item.state" /><OverrideMark :override="item.override" /></template>
      <template #[`item.updated_at`]="{item}"><WhenText :at="item.updated_at" /></template>
    </v-data-table>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onActivated, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {RefreshSummary} from '@/api'
import {api, problem} from '@/api'
import ColumnHeader from '@/components/ColumnHeader.vue'
import LoadError from '@/components/LoadError.vue'
import OverrideMark from '@/components/OverrideMark.vue'
import RefreshState from '@/components/RefreshState.vue'
import WhenText from '@/components/WhenText.vue'
import {PAGE_SIZES, stateOf} from '@/words'
import {useTableState} from '@/tableState'

// Every column has a meaningful order (D94); the state sorts by its label, as shown.
const headers = [
  {title: 'Refresh', key: 'refresh_id', help: 'The refresh\'s ID: <museum>-<refresh date>-<number>. Opens its page.'},
  {title: 'Refresh date', key: 'refresh_date', help: 'The day, in Pacific time, whose servable list it brings in. An admin refresh says which day\'s list it used.'},
  {title: 'State', key: 'state', value: (item: RefreshSummary) => stateOf(item.state), help: 'How far it got: Updated is done; a failed check or update says so, and its page says what an admin can do. A shield: an admin overrode the delta threshold.'},
  {title: 'Rows', key: 'rows', help: 'Rows in its servable list: one per Blob the ETL lists.'},
  {title: 'Last change', key: 'updated_at', help: 'When its state last changed (UTC).'}
]

const route = useRoute()
const table = useTableState('', 'updated_at') // its place in the address (October 14, 2026)
// Kept alive, one per museum (App.vue): always this museum's, whichever page the address shows now.
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const refreshes = ref<RefreshSummary[]>([])
const loaded = ref(false)
const error = ref('')

async function load() {
  const m = museum.value
  loaded.value = false
  error.value = ''
  try {
    refreshes.value = (await api.refreshes(m)).refreshes
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
