<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Alerts</h1>
    <p class="mb-4">
      Every alert of the last 30 days, newest first. Click a column's name to sort by it. Acknowledging one doesn't hide a
      problem: if it's still there, the watchdog raises it again the next day.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="alerts-table"
      :headers="headers"
      :items="alerts"
      :sort-by="[{key: 'created_at', order: 'desc'}]"
      :items-per-page="25"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      item-value="key"
      density="compact"
      no-data-text="No alerts in the last 30 days."
    >
      <template #[`item.title`]="{item}">
        <strong>{{ item.title }}</strong>
        <div class="text-body-2">{{ item.message }}</div>
      </template>
      <template #[`item.created_at`]="{item}">{{ when(item.created_at) }}</template>
      <template #[`item.acknowledged_at`]="{item}">
        <span v-if="item.acknowledged_at">{{ item.acknowledged_by }}, {{ when(item.acknowledged_at) }}</span>
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
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AlertItem} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {alertsChanged} from '@/session'
import {PAGE_SIZES, when} from '@/words'

// Sortable: when, refresh date, alert, about and acknowledged (D94); the alert sorts by its title.
const headers = [
  {title: 'Raised', key: 'created_at'},
  {title: 'Refresh date', key: 'refresh_date'},
  {title: 'Alert', key: 'title'},
  {title: 'About', key: 'subject'},
  {title: 'Acknowledged', key: 'acknowledged_at'}
]

const route = useRoute()
const museum = computed(() => String(route.params.museum))
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
</script>
