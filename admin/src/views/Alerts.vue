<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Alerts</h1>
    <p class="mb-4">Every alert of the last 30 days, newest first. Acknowledging one doesn't hide a problem: if it's still there, the watchdog raises it again the next day.</p>
    <LoadError :message="error" />
    <v-table id="alerts-table" density="compact">
      <thead>
        <tr>
          <th>Refresh date</th>
          <th>Alert</th>
          <th>About</th>
          <th>Acknowledged</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="alert in alerts" :key="alert.key">
          <td>{{ alert.refresh_date }}</td>
          <td>
            <strong>{{ alert.title }}</strong>
            <div class="text-body-2">{{ alert.message }}</div>
          </td>
          <td>{{ alert.subject }}</td>
          <td>
            <span v-if="alert.acknowledged_at">{{ alert.acknowledged_by }}, {{ when(alert.acknowledged_at) }}</span>
            <v-btn
              v-else
              size="small"
              variant="outlined"
              @click="acknowledge(alert.key)"
            >
              Acknowledge
            </v-btn>
          </td>
        </tr>
      </tbody>
    </v-table>
    <p v-if="loaded && !alerts.length" class="mt-4">No alerts in the last 30 days.</p>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AlertItem} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {alertsChanged} from '@/session'
import {when} from '@/words'

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
