<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Upload a night's file</h1>
    <p class="mb-4">
      For a partial night where the ETL loaded the public core but its Blob-to-Media file never reached Serena. Take
      that night's file from the ETL server. Serena checks it as it checks every night's file and, if it passes,
      applies it. If it fails, nothing changes and the run shows why.
    </p>
    <v-alert
      v-if="error"
      id="upload-error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ error }}
    </v-alert>
    <v-form id="upload-form" style="max-width: 640px" @submit.prevent="upload">
      <v-file-input
        id="file"
        v-model="file"
        label="The Blob-to-Media file (.tsv or .tsv.gz)"
        accept=".tsv,.gz,.txt"
      />
      <v-text-field
        id="night"
        v-model="night"
        type="date"
        :max="today"
        label="Which night's file it is"
      />
      <v-textarea
        id="reason"
        v-model="reason"
        label="Reason"
        hint="Recorded in the run and the audit log. No personal data, please."
        persistent-hint
        rows="2"
        counter="500"
        class="mb-2"
      />
      <v-checkbox
        id="confirm-loaded"
        v-model="confirmed"
        label="The public core loaded that night with this file: I checked the ETL's report."
      />
      <v-btn
        id="upload-button"
        type="submit"
        color="primary"
        :disabled="!ready"
        :loading="busy"
      >
        Upload and apply
      </v-btn>
    </v-form>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {ApiError, api} from '@/api'
import {pacificDate} from '@/words'

const route = useRoute()
const router = useRouter()
const file = ref<File | File[] | null>(null)
const today = pacificDate()
const night = ref(pacificDate(1)) // a partial night is usually last night
const confirmed = ref(false)
const reason = ref('')
const busy = ref(false)
const error = ref('')

const chosen = computed(() => (Array.isArray(file.value) ? file.value[0] : file.value) || null)
const ready = computed(() => !!chosen.value && confirmed.value && /^\d{4}-\d{2}-\d{2}$/.test(night.value) &&
  night.value <= today && reason.value.trim().length > 0 && reason.value.length <= 500) // D62

async function upload() {
  if (!chosen.value) {
    return
  }
  busy.value = true
  error.value = ''
  try {
    const run = await api.upload(String(route.params.museum), chosen.value, night.value, reason.value.trim())
    await router.push({name: 'run', params: {museum: String(route.params.museum), runId: run.run_id}})
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The upload didn\'t work.'
  } finally {
    busy.value = false
  }
}
</script>
