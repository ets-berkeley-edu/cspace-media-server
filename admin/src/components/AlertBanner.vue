<template>
  <div v-if="unacknowledged.length" id="alert-banner" class="pa-3">
    <v-alert
      v-for="alert in unacknowledged.slice(0, 5)"
      :key="alert.key"
      type="warning"
      density="compact"
      class="mb-2"
    >
      <strong>{{ alert.title }}</strong> · {{ alert.night }} · {{ alert.subject }}
      <div class="text-body-2">{{ alert.message }}</div>
      <template #append>
        <v-btn
          class="acknowledge"
          size="small"
          variant="outlined"
          :loading="busy === alert.key"
          @click="acknowledge(alert.key)"
        >
          Acknowledge
        </v-btn>
      </template>
    </v-alert>
    <router-link v-if="unacknowledged.length > 5" :to="{name: 'alerts', params: {museum}}">
      and {{ unacknowledged.length - 5 }} more
    </router-link>
  </div>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AlertItem} from '@/api'
import {api} from '@/api'
import {alertsChanged} from '@/session'

const route = useRoute()
const museum = computed(() => String(route.params.museum || ''))
const alerts = ref<AlertItem[]>([])
const busy = ref('')
const unacknowledged = computed(() => alerts.value.filter(a => !a.acknowledged_at))

async function load() {
  try {
    alerts.value = museum.value ? (await api.alerts(museum.value)).alerts : []
  } catch {
    alerts.value = [] // the page itself reports a problem reaching Serena; the banner stays out of the way
  }
}

async function acknowledge(key: string) {
  busy.value = key
  try {
    await api.acknowledge(museum.value, key)
    alertsChanged.value++
  } finally {
    busy.value = ''
  }
}

watch([museum, alertsChanged], load, {immediate: true})
</script>
