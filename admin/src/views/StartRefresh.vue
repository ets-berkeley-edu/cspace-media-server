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
        ref="fileField"
        v-model="file"
        label="The servable list (.tsv or .tsv.gz)"
        accept=".tsv,.gz,.txt"
        :error-messages="problems.file ? [problems.file] : []"
      />
      <v-text-field
        id="refresh-date"
        ref="dateField"
        v-model="refreshDate"
        type="date"
        :max="today"
        label="The refresh date the servable list is for"
        :error-messages="problems.date ? [problems.date] : []"
      />
      <ReasonField
        ref="reasonField"
        v-model="reason"
        class="mb-2"
        recorded="the refresh and the audit log"
      />
      <v-checkbox
        id="confirm-live-core"
        ref="confirmField"
        v-model="confirmed"
        label="This servable list was made from the live public core: I ran the servable list script on the ETL server."
        :error-messages="problems.confirmed ? [problems.confirmed] : []"
      />
      <!-- Never disabled (Richard, October 14, 2026): pressing it says what's missing, under its field. -->
      <v-btn
        id="start-refresh-button"
        type="submit"
        color="primary"
        variant="flat"
        :loading="busy"
      >
        Start the refresh
      </v-btn>
    </v-form>
  </v-container>
</template>

<script setup lang="ts">
import {computed, reactive, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {museumName} from '@/session'
import {ApiError, api} from '@/api'
import ReasonField from '@/components/ReasonField.vue'
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
// What's missing, under each field, once "Start the refresh" is pressed; a field's message goes when it's filled in.
const problems = reactive({file: '', date: '', confirmed: ''})
type Focusable = {focus: () => void} | null
const fileField = ref<Focusable>(null)
const dateField = ref<Focusable>(null)
const confirmField = ref<Focusable>(null)
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
watch(chosen, () => { problems.file = '' })
watch(refreshDate, () => { problems.date = '' })
watch(confirmed, () => { problems.confirmed = '' })

/** Every field that's missing says so; focus goes to the first. The reason is required (D62). */
function complete(): boolean {
  problems.file = chosen.value ? '' : 'Choose the servable list first.'
  problems.date = /^\d{4}-\d{2}-\d{2}$/.test(refreshDate.value) && refreshDate.value <= today
    ? '' : `Give a refresh date of today (${today}) or earlier.`
  const reasonGiven = reasonField.value?.check() ?? false
  problems.confirmed = confirmed.value ? '' : 'Confirm the list was made from the live public core.'
  // check() moved focus to the reason if it's missing; an earlier missing field takes it, a later one only without that.
  const first = problems.file ? fileField.value : problems.date ? dateField.value
    : reasonGiven && problems.confirmed ? confirmField.value : null
  first?.focus()
  return !problems.file && !problems.date && reasonGiven && !problems.confirmed
}

async function start() {
  if (!complete() || !chosen.value) {
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
