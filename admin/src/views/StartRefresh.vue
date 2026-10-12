<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(String(route.params.museum)) }}: Start a refresh</h1>
    <p class="mb-4">
      An admin refresh, for a failed refresh: when the servable list didn't reach Serena, or needs replacing. Run the
      servable list script on the ETL server, then choose the list it makes. Serena closes the museum's open refresh, if
      there is one, starts a new refresh with the list, checks it as it checks every servable list and, if it passes,
      runs the servability update. If it fails, nothing changes and the refresh shows why.
    </p>
    <v-alert
      v-if="error"
      id="start-refresh-error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ error }}
    </v-alert>
    <v-form id="start-refresh-form" style="max-width: 640px" @submit.prevent="start">
      <v-file-input
        id="file"
        v-model="file"
        label="The servable list (.tsv or .tsv.gz)"
        accept=".tsv,.gz,.txt"
      />
      <v-text-field
        id="refresh-date"
        v-model="refreshDate"
        type="date"
        :max="today"
        label="The refresh date the servable list is for"
      />
      <v-textarea
        id="reason"
        v-model="reason"
        label="Reason"
        hint="Recorded in the refresh and the audit log. No personal data, please."
        persistent-hint
        rows="2"
        counter="500"
        class="mb-2"
      />
      <v-checkbox
        id="confirm-live-core"
        v-model="confirmed"
        label="This servable list was made from the live public core: I ran the servable list script on the ETL server."
      />
      <v-btn
        id="start-refresh-button"
        type="submit"
        color="primary"
        :disabled="!ready"
        :loading="busy"
      >
        Start the refresh
      </v-btn>
    </v-form>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {museumName} from '@/session'
import {ApiError, api} from '@/api'
import {pacificDate} from '@/words'

const route = useRoute()
const router = useRouter()
const file = ref<File | File[] | null>(null)
const today = pacificDate()
const refreshDate = ref(today) // the list is made from the live public core, so it's today's (D75)
const confirmed = ref(false)
const reason = ref('')
const busy = ref(false)
const error = ref('')

const chosen = computed(() => (Array.isArray(file.value) ? file.value[0] : file.value) || null)
const ready = computed(() => !!chosen.value && confirmed.value && /^\d{4}-\d{2}-\d{2}$/.test(refreshDate.value) &&
  refreshDate.value <= today && reason.value.trim().length > 0 && reason.value.length <= 500) // D62

async function start() {
  if (!chosen.value) {
    return
  }
  busy.value = true
  error.value = ''
  try {
    const refresh = await api.startRefresh(String(route.params.museum), chosen.value, refreshDate.value, reason.value.trim())
    await router.push({name: 'refresh', params: {museum: String(route.params.museum), refreshId: refresh.refresh_id}})
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The refresh didn\'t start.'
  } finally {
    busy.value = false
  }
}
</script>
