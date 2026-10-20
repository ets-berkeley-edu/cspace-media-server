<template>
  <div v-if="unacknowledged.length" id="alert-banner" class="alert-banner d-flex align-center px-4 py-2">
    <span class="text-truncate"><strong>{{ unacknowledged.length }} alert{{ unacknowledged.length === 1 ? '' : 's' }}:</strong> <span id="alert-banner-title">{{ unacknowledged[0].title }}</span></span>
    <v-spacer />
    <v-btn
      id="open-alerts"
      size="small"
      variant="outlined"
      :to="{name: 'alerts', params: {museum}, query: {show: 'waiting'}}"
      @click="markMenuNavigation"
    >
      Open alerts
    </v-btn>
  </div>
</template>

<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, watch} from 'vue'
import {useRoute} from 'vue-router'
import {api} from '@/api'
import {markMenuNavigation} from '@/navigation'
import {alertsChanged, waiting} from '@/session'

// One line, only while an alert waits to be acknowledged: how many, the newest one's title, and a way to the Alerts
// page, where they're acknowledged, showing the waiting ones (D213). The app bar's bell shows the same count (D137).
const route = useRoute()
const museum = computed(() => String(route.params.museum || ''))
const unacknowledged = computed(() => waiting.museum === museum.value ? waiting.alerts : [])

async function load() {
  const asked = museum.value
  try {
    const alerts = asked ? (await api.alerts(asked, true)).alerts : []
    waiting.alerts = alerts.filter(a => !a.acknowledged_at).sort((a, b) => b.created_at.localeCompare(a.created_at))
  } catch {
    waiting.alerts = [] // the page itself reports a problem reaching Serena; the banner stays out of the way
  }
  waiting.museum = asked
}

// Alerts the watchdog raises in the background show up without a refresh: on every page change, and every minute
// while the tab is visible.
const EVERY_MS = 60_000
let timer: ReturnType<typeof setInterval> | undefined

function whenVisible() {
  if (document.visibilityState === 'visible') {
    void load()
  }
}

watch([museum, alertsChanged, () => route.fullPath], load, {immediate: true})
onMounted(() => {
  timer = setInterval(whenVisible, EVERY_MS)
  document.addEventListener('visibilitychange', whenVisible)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  document.removeEventListener('visibilitychange', whenVisible)
})
</script>

<style scoped>
.alert-banner {
  background: rgb(var(--v-theme-warning), 0.12);
  border-bottom: 1px solid rgb(var(--v-theme-warning), 0.4);
  gap: 4px;
}
</style>
