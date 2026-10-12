<template>
  <v-container fluid>
    <h1 class="text-h5 mb-1">{{ refresh?.refresh_id }}</h1>
    <p v-if="refresh" class="mb-4">
      <span id="refresh-state" class="font-weight-bold">{{ stateOf(refresh.state) }}</span>
      · refresh date {{ refresh.refresh_date }}<span v-if="refresh.admin_refresh_date"> · an admin refresh, with the servable list
        for {{ refresh.admin_refresh_date }}</span> · last change {{ when(refresh.updated_at) }}
      <span v-if="!refresh.newest"> · a later refresh has started</span>
    </p>
    <v-alert
      v-if="error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ error }}
    </v-alert>

    <div v-if="refresh?.actions.length" class="mb-6">
      <v-btn
        v-if="refresh.actions.includes('retry_update')"
        id="retry-update"
        color="primary"
        @click="open('retry_update')"
      >
        Retry the servability update
      </v-btn>
      <v-btn
        v-if="refresh.actions.includes('override_threshold')"
        id="override-threshold"
        color="warning"
        @click="open('override_threshold')"
      >
        Override the delta threshold
      </v-btn>
    </div>

    <template v-if="refresh">
      <h2 class="text-h6 mb-2">Reasons</h2>
      <ul v-if="refresh.reasons.length" id="refresh-reasons" class="mb-4 ml-6">
        <li v-for="(line, i) in refresh.reasons" :key="i">{{ line }}</li>
      </ul>
      <p v-else class="mb-4">None recorded.</p>

      <h2 class="text-h6 mb-2">The servable list</h2>
      <p v-if="refresh.upload" class="mb-4">
        {{ refresh.file_name }}: {{ refresh.upload.rows }} rows, {{ refresh.upload.bytes }} bytes, received {{ when(refresh.upload.uploaded_at) }}.
      </p>
      <p v-else class="mb-4">Not received.</p>

      <template v-if="refresh.check">
        <h2 class="text-h6 mb-2">Servable list check: {{ refresh.check.result }}</h2>
        <p class="mb-2">
          {{ refresh.check.rows }} rows; {{ refresh.check.added }} added, {{ refresh.check.removed }} removed,
          {{ refresh.check.changed }} changed<span v-if="refresh.check.previous_rows !== null">
            ({{ refresh.check.delta_percent }}% of the {{ refresh.check.previous_rows }} rows of the last servability update; the
            threshold is {{ refresh.check.threshold_percent }}%)</span>.
        </p>
        <ul v-if="refresh.check.warnings.length" class="mb-2 ml-6">
          <li v-for="(warning, i) in refresh.check.warnings" :key="i">Warning: {{ warning }}</li>
        </ul>
        <v-table
          v-if="refresh.check.errors.length"
          id="check-problems"
          density="compact"
          class="mb-4"
        >
          <thead>
            <tr><th>Line</th><th>Field</th><th>Problem</th></tr>
          </thead>
          <tbody>
            <tr v-for="(problem, i) in refresh.check.errors" :key="i">
              <td>{{ problem.line || '' }}</td><td>{{ problem.field }}</td><td>{{ problem.problem }}</td>
            </tr>
          </tbody>
        </v-table>
        <p v-if="refresh.check.error_count > refresh.check.errors.length" class="mb-4">
          {{ refresh.check.error_count }} problems in all; the first {{ refresh.check.errors.length }} are shown.
        </p>
      </template>

      <template v-if="refresh.update">
        <h2 class="text-h6 mb-2">The servability update</h2>
        <p class="mb-4">{{ refresh.update.deleted }} deleted, {{ refresh.update.written }} written, {{ refresh.update.unchanged }} unchanged.</p>
      </template>
    </template>

    <v-dialog v-model="dialog" max-width="560">
      <v-card>
        <v-card-title>{{ titles[action] }}</v-card-title>
        <v-card-text>
          <p class="mb-4">{{ explanations[action] }}</p>
          <v-textarea
            id="reason"
            v-model="reason"
            label="Reason"
            hint="Recorded in the refresh and the audit log. No personal data, please."
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
import type {Refresh, RefreshAction} from '@/api'
import {ApiError, api, problem as failure} from '@/api'
import {alertsChanged} from '@/session'
import {stateOf, when} from '@/words'

const titles: Record<RefreshAction, string> = {
  retry_update: 'Retry the servability update',
  override_threshold: 'Override the delta threshold'
}
const explanations: Record<RefreshAction, string> = {
  retry_update: 'The worker runs the servability update again. Do this once whatever stopped it is fixed.',
  override_threshold: 'The servable list check failed only because more rows change than the delta threshold allows. ' +
    'Do this once you know the change is expected. Serena checks the same servable list again without the delta ' +
    'threshold (every other check still applies) and, if it passes, updates Serena from it. The team is emailed.'
}

const route = useRoute()
const refresh = ref<Refresh | null>(null)
const error = ref('')
const dialog = ref(false)
const action = ref<RefreshAction>('retry_update')
const reason = ref('')
const busy = ref(false)

const museum = computed(() => String(route.params.museum))
// Every action needs a reason (D62).
const ready = computed(() => reason.value.length <= 500 && reason.value.trim().length > 0)

async function load() {
  try {
    refresh.value = await api.refresh(museum.value, String(route.params.refreshId))
  } catch (e) {
    error.value = failure(e)
  }
}

function open(which: RefreshAction) {
  action.value = which
  reason.value = ''
  error.value = ''
  dialog.value = true
}

async function act() {
  if (!refresh.value) {
    return
  }
  busy.value = true
  try {
    const id = refresh.value.refresh_id
    if (action.value === 'retry_update') {
      refresh.value = await api.retryUpdate(museum.value, id, reason.value.trim())
    } else {
      refresh.value = await api.overrideThreshold(museum.value, id, reason.value.trim())
      alertsChanged.value++ // the override's alert
    }
    dialog.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
    dialog.value = false
  } finally {
    busy.value = false
  }
}

watch(() => [route.params.museum, route.params.refreshId], load, {immediate: true})
</script>
