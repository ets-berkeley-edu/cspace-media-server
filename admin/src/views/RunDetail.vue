<template>
  <v-container fluid>
    <h1 class="text-h5 mb-1">{{ run?.run_id }}</h1>
    <p v-if="run" class="mb-4">
      <span id="run-state" class="font-weight-bold">{{ stateOf(run.state) }}</span>
      · night of {{ run.night }}<span v-if="run.uploaded_night"> · an admin's upload of the night of
        {{ run.uploaded_night }}'s file</span> · last change {{ when(run.updated_at) }}
      <span v-if="!run.newest"> · a later run has started</span>
    </p>
    <v-alert
      v-if="error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ error }}
    </v-alert>

    <div v-if="run?.actions.length" class="mb-6">
      <v-btn
        v-if="run.actions.includes('retry_apply')"
        id="retry-apply"
        color="primary"
        @click="open('retry_apply')"
      >
        Retry the apply
      </v-btn>
      <v-btn
        v-if="run.actions.includes('record_load')"
        id="record-load"
        color="primary"
        @click="open('record_load')"
      >
        Record tonight's load and apply
      </v-btn>
      <v-btn
        v-if="run.actions.includes('override_threshold')"
        id="override-threshold"
        color="warning"
        @click="open('override_threshold')"
      >
        Override the change threshold for the next run
      </v-btn>
    </div>

    <template v-if="run">
      <h2 class="text-h6 mb-2">Reasons</h2>
      <ul v-if="run.reasons.length" id="run-reasons" class="mb-4 ml-6">
        <li v-for="(line, i) in run.reasons" :key="i">{{ line }}</li>
      </ul>
      <p v-else class="mb-4">None recorded.</p>

      <h2 class="text-h6 mb-2">The file</h2>
      <p v-if="run.upload" class="mb-4">
        {{ run.file_name }}: {{ run.upload.rows }} rows, {{ run.upload.bytes }} bytes, received {{ when(run.upload.uploaded_at) }}.
      </p>
      <p v-else class="mb-4">Not received.</p>

      <template v-if="run.preflight">
        <h2 class="text-h6 mb-2">Preflight: {{ run.preflight.result }}</h2>
        <p class="mb-2">
          {{ run.preflight.rows }} rows; {{ run.preflight.added }} added, {{ run.preflight.removed }} removed,
          {{ run.preflight.changed }} changed<span v-if="run.preflight.previous_rows !== null">
            ({{ run.preflight.change_percent }}% of the {{ run.preflight.previous_rows }} rows applied before; the
            threshold is {{ run.preflight.threshold_percent }}%)</span>.
        </p>
        <ul v-if="run.preflight.warnings.length" class="mb-2 ml-6">
          <li v-for="(warning, i) in run.preflight.warnings" :key="i">Warning: {{ warning }}</li>
        </ul>
        <v-table
          v-if="run.preflight.errors.length"
          id="preflight-problems"
          density="compact"
          class="mb-4"
        >
          <thead>
            <tr><th>Line</th><th>Field</th><th>Problem</th></tr>
          </thead>
          <tbody>
            <tr v-for="(problem, i) in run.preflight.errors" :key="i">
              <td>{{ problem.line || '' }}</td><td>{{ problem.field }}</td><td>{{ problem.problem }}</td>
            </tr>
          </tbody>
        </v-table>
        <p v-if="run.preflight.error_count > run.preflight.errors.length" class="mb-4">
          {{ run.preflight.error_count }} problems in all; the first {{ run.preflight.errors.length }} are shown.
        </p>
      </template>

      <template v-if="run.solr_load">
        <h2 class="text-h6 mb-2">The public core's load</h2>
        <p class="mb-4">
          {{ run.solr_load.outcome }}<span v-if="run.solr_load.rows !== null">, {{ run.solr_load.rows }} documents</span>
          <span v-if="run.solr_load.recorded_by_admin"> (recorded by an admin)</span>.
        </p>
      </template>

      <template v-if="run.apply">
        <h2 class="text-h6 mb-2">The apply</h2>
        <p class="mb-4">{{ run.apply.deleted }} deleted, {{ run.apply.written }} written, {{ run.apply.unchanged }} unchanged.</p>
      </template>
    </template>

    <v-dialog v-model="dialog" max-width="560">
      <v-card>
        <v-card-title>{{ titles[action] }}</v-card-title>
        <v-card-text>
          <p class="mb-4">{{ explanations[action] }}</p>
          <template v-if="action === 'record_load'">
            <v-checkbox id="confirm-loaded" v-model="confirmed" label="The public core loaded that night: I checked the ETL's report." />
            <v-text-field
              id="load-rows"
              v-model="rows"
              label="Documents loaded (optional, from the ETL's report)"
              type="number"
            />
          </template>
          <v-textarea
            id="reason"
            v-model="reason"
            label="Reason"
            hint="Recorded in the run and the audit log. No personal data, please."
            persistent-hint
            rows="2"
            counter="500"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="dialog = false">Cancel</v-btn>
          <v-btn
            id="confirm-action"
            color="primary"
            :disabled="!ready"
            :loading="busy"
            @click="act"
          >
            {{ titles[action] }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {Run, RunAction} from '@/api'
import {ApiError, api, problem as failure} from '@/api'
import {alertsChanged} from '@/session'
import {stateOf, when} from '@/words'

const titles: Record<RunAction, string> = {
  retry_apply: 'Retry the apply',
  record_load: 'Record tonight\'s load and apply',
  override_threshold: 'Override the change threshold'
}
const explanations: Record<RunAction, string> = {
  retry_apply: 'The worker applies the file again. Do this once whatever stopped the apply is fixed.',
  record_load: 'The ETL didn\'t report this night\'s load. If the public core did load it, Serena records the load ' +
    'and applies the file, so Serena and the public core match again.',
  override_threshold: 'The preflight failed only because too many rows change. This arms an override for the ' +
    'museum\'s next run: its preflight skips the threshold once (every other check still applies). It expires ' +
    'after 48 hours, and the team is emailed. Then ask the ETL team to rerun the night.'
}

const route = useRoute()
const run = ref<Run | null>(null)
const error = ref('')
const dialog = ref(false)
const action = ref<RunAction>('retry_apply')
const reason = ref('')
const confirmed = ref(false)
const rows = ref('')
const busy = ref(false)

const museum = computed(() => String(route.params.museum))
// Every action needs a reason (D62); recording a load also needs the confirmation (D65).
const ready = computed(() => reason.value.length <= 500 && reason.value.trim().length > 0 &&
  (action.value !== 'record_load' || confirmed.value))

async function load() {
  try {
    run.value = await api.run(museum.value, String(route.params.runId))
  } catch (e) {
    error.value = failure(e)
  }
}

function open(which: RunAction) {
  action.value = which
  reason.value = ''
  confirmed.value = false
  rows.value = ''
  error.value = ''
  dialog.value = true
}

async function act() {
  if (!run.value) {
    return
  }
  busy.value = true
  try {
    const id = run.value.run_id
    if (action.value === 'retry_apply') {
      run.value = await api.retryApply(museum.value, id, reason.value.trim())
    } else if (action.value === 'record_load') {
      run.value = await api.recordLoad(museum.value, id, rows.value === '' ? null : Number(rows.value), reason.value.trim())
    } else {
      await api.overrideThreshold(museum.value, id, reason.value.trim())
      alertsChanged.value++
      await load()
    }
    dialog.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
    dialog.value = false
  } finally {
    busy.value = false
  }
}

watch(() => [route.params.museum, route.params.runId], load, {immediate: true})
</script>
