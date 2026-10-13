<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Past refreshes</h1>
    <p class="mb-4">
      This museum's daily refreshes of the last 30 days, newest first. Click a column's name to sort by it. Open a refresh
      to see its servable list, its checks and what an admin can do.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="refreshes-table"
      :headers="headers"
      :items="refreshes"
      :sort-by="[{key: 'updated_at', order: 'desc'}]"
      must-sort
      :items-per-page="25"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      item-value="refresh_id"
      density="compact"
      no-data-text="No refreshes in the last 30 days."
    >
      <template #[`item.refresh_id`]="{item}">
        <router-link :to="{name: 'refresh', params: {museum, refreshId: item.refresh_id}}">{{ item.refresh_id }}</router-link>
      </template>
      <template #[`item.refresh_date`]="{item}">
        {{ item.refresh_date }}<span v-if="item.admin_refresh_date"> (admin refresh, list for {{ item.admin_refresh_date }})</span>
      </template>
      <template #[`item.updated_at`]="{item}">{{ when(item.updated_at) }}</template>
    </v-data-table>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {RefreshSummary} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {PAGE_SIZES, stateOf, when} from '@/words'

// Every column has a meaningful order (D94); the state sorts by its label, as shown.
const headers = [
  {title: 'Refresh', key: 'refresh_id'},
  {title: 'Refresh date', key: 'refresh_date'},
  {title: 'State', key: 'state', value: (item: RefreshSummary) => stateOf(item.state)},
  {title: 'Rows', key: 'rows'},
  {title: 'Last change', key: 'updated_at'}
]

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const refreshes = ref<RefreshSummary[]>([])
const loaded = ref(false)
const error = ref('')

watch(museum, async m => {
  loaded.value = false
  error.value = ''
  try {
    refreshes.value = (await api.refreshes(m)).refreshes
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}, {immediate: true})
</script>
