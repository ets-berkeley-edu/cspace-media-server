<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-1">{{ museumName(museum) }} refresh {{ refresh?.refresh_id }}</h1>
    <p v-if="refresh" class="mb-4">
      <RefreshState id="refresh-state" :state="refresh.state" :override="refresh.override" />
      · refresh date {{ refresh.refresh_date }}<span v-if="refresh.admin_refresh_date"> · an admin refresh, with the servable list
        for {{ refresh.admin_refresh_date }}</span> · last change {{ when(refresh.updated_at) }}
      <span v-if="!refresh.newest"> · a later refresh has started</span>
    </p>
    <!-- Who overrode the delta threshold, when and why, for as long as the refresh is shown (issue #108). -->
    <v-alert
      v-if="refresh?.override"
      id="override-banner"
      color="warning"
      variant="tonal"
      :icon="mdiShieldAlert"
      density="compact"
      class="mb-4"
    >
      <!-- It leads with the check that failed and by how much, then who, when and why (issue #110). -->
      <strong id="override-lead" class="text-subtitle-1 font-weight-bold">A safety check failed, and an admin overrode it</strong>
      <div v-if="overshoot" id="override-overshoot">{{ overshoot }}</div>
      <div><strong>Delta threshold overridden</strong> by {{ overrideBy(refresh.override) }} at {{ when(refresh.override.at) }}.</div>
      <div v-if="refresh.override.reason" id="override-reason">Reason: {{ refresh.override.reason }}</div>
      <div>{{ afterOverride }}</div>
    </v-alert>
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
        variant="flat"
        @click="open('retry_update')"
      >
        Retry the servability update
      </v-btn>
      <v-btn
        v-if="refresh.actions.includes('override_threshold')"
        id="override-threshold"
        color="error"
        variant="flat"
        @click="open('override_threshold')"
      >
        Override the delta threshold
      </v-btn>
    </div>

    <template v-if="refresh">
      <h2 class="text-h6 mb-2">Reasons</h2>
      <ul v-if="reasons.length" id="refresh-reasons" class="mb-4 ml-6">
        <li v-for="(line, i) in reasons" :key="i">{{ line }}</li>
      </ul>
      <p v-else class="mb-4">None recorded.</p>

      <h2 class="text-h6 mb-2">The servable list</h2>
      <p v-if="refresh.upload" class="mb-4">
        {{ refresh.file_name }}: {{ refresh.upload.rows }} rows, {{ refresh.upload.bytes }} bytes, received {{ when(refresh.upload.uploaded_at) }}.
      </p>
      <p v-else class="mb-4">Not received.</p>

      <template v-if="refresh.check">
        <h2 id="check-heading" class="text-h6 mb-2">
          <!-- After an override it never reads "passed" alone: the check failed, and an admin overrode it (issue #110). -->
          Servable list check: <template v-if="overriddenCheck"><span class="text-error">failed</span>, overridden by admin</template><template v-else>{{ refresh.check.result }}</template>
          <!-- Only where the heading doesn't already say it: a re-check that failed on something else (issue #110). -->
          <v-chip
            v-if="refresh.override && !overriddenCheck"
            id="check-overridden"
            color="warning"
            size="small"
            variant="tonal"
            class="ml-2"
          >
            <v-icon
              :icon="mdiShieldAlert"
              size="small"
              class="mr-1"
              aria-hidden="true"
            />Delta threshold overridden
          </v-chip>
        </h2>
        <p class="mb-2">
          {{ refresh.check.rows }} rows; {{ refresh.check.added }} added, {{ refresh.check.removed }} removed,
          {{ refresh.check.changed }} changed<span v-if="refresh.check.previous_rows !== null">
            ({{ refresh.check.delta_percent }}% of the {{ refresh.check.previous_rows }} rows of the last servability update; the
            threshold is {{ refresh.check.threshold_percent }}%)</span>.
        </p>
        <p v-if="passedByOverride" id="check-passed-without-threshold" class="mb-2 text-medium-emphasis">
          It passed when Serena checked it again without the delta threshold; every other check still applied.
        </p>
        <p v-if="overriddenFailure" class="mb-2 text-medium-emphasis">
          The check below is the one the override answered: its delta threshold problem no longer stops the refresh. The new
          check's result replaces it when Serena is done.
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
            <tr
              v-for="(problem, i) in refresh.check.errors"
              :key="i"
              :class="{'overridden-problem': overriddenFailure && isThreshold(problem.problem)}"
            >
              <td>{{ problem.line || '' }}</td><td>{{ problem.field }}</td>
              <td v-if="overriddenFailure && isThreshold(problem.problem)"><s>{{ problem.problem }}</s> (overridden)</td>
              <td v-else>{{ problem.problem }}</td>
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
        <p v-if="refresh.update.recalls_ended || refresh.update.recalls_kept" id="update-recalls" class="mb-4">
          Recalls: {{ refresh.update.recalls_ended || 0 }} ended (no longer public in CollectionSpace),
          {{ refresh.update.recalls_kept || 0 }} kept (still public in CollectionSpace).
        </p>
      </template>
    </template>

    <v-dialog v-model="dialog" max-width="560">
      <v-card>
        <v-card-title>{{ titles[action] }}</v-card-title>
        <v-card-text>
          <p class="mb-4">{{ explanations[action] }}</p>
          <ReasonField
            ref="reasonField"
            v-model="reason"
            :recorded="action === 'override_threshold' ? 'the refresh, the audit log and the alert emailed to the team' : 'the refresh and the audit log'"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="dialog = false">Cancel</v-btn>
          <v-btn
            id="confirm-action"
            :color="action === 'override_threshold' ? 'error' : 'primary'"
            variant="flat"
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
import {mdiShieldAlert} from '@mdi/js'
import type {Refresh, RefreshAction} from '@/api'
import {ApiError, api, problem as failure} from '@/api'
import {WORKING, useCheckAgain, working} from '@/checkAgain'
import ReasonField from '@/components/ReasonField.vue'
import RefreshState from '@/components/RefreshState.vue'
import {alertsChanged, museumName} from '@/session'
import {overrideBy, overrideReason, when} from '@/words'

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
// Every action needs a reason (D62): its button stays enabled, and ReasonField says what's missing.
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)

// While the worker checks or updates, the page checks again by itself (issue #108), so an override's re-check and
// update show without a reload. These checks don't count as activity: an open tab still signs out when idle.
const after = useCheckAgain(() => load(true))

// The override's reason is in the banner, so Reasons leaves out the line Serena adds for it.
const reasons = computed(() => {
  const given = refresh.value?.override?.reason
  return (refresh.value?.reasons || []).filter(line => !given || line !== overrideReason(given))
})
// The failed check an override answered, still shown while Serena checks the servable list again. A re-check that
// fails on something else replaces it, and isn't marked.
const overriddenFailure = computed(() => !!refresh.value?.override && refresh.value.state === 'checking' &&
  refresh.value.check?.result === 'failed')
// The re-check without the delta threshold passed (issue #110).
const passedByOverride = computed(() => !!refresh.value?.override && refresh.value.check?.result === 'passed')
// The check an admin overrode: "failed, overridden by admin" while Serena re-checks it and once the re-check passes.
const overriddenCheck = computed(() => overriddenFailure.value || passedByOverride.value)
// How far the servable list went past the delta threshold, for the banner (issue #110).
const overshoot = computed(() => {
  const check = refresh.value?.check
  return check && check.previous_rows !== null
    ? `The servable list changes ${check.delta_percent}% of the rows; the threshold is ${check.threshold_percent}%.`
    : ''
})
const afterOverride = computed(() => {
  const state = refresh.value?.state || ''
  if (WORKING.includes(state)) {
    return 'Serena is checking the same servable list again without the delta threshold (every other check still ' +
      'applies) and, if it passes, updates. This page checks again every few seconds until it\'s done.'
  }
  return 'Serena checked the same servable list again without the delta threshold (every other check still applied)' +
    `${state === 'updated' ? ' and updated from it' : ''}. The team was emailed.`
})

function isThreshold(problem: string): boolean {
  return problem.includes('threshold is')
}

function checkAgain() {
  after(working([refresh.value]))
}

async function load(background = false) {
  try {
    refresh.value = await api.refresh(museum.value, String(route.params.refreshId), background)
  } catch (e) {
    error.value = failure(e)
  }
  checkAgain()
}

function open(which: RefreshAction) {
  action.value = which
  reason.value = ''
  reasonField.value?.reset()
  error.value = ''
  dialog.value = true
}

async function act() {
  if (!refresh.value || !reasonField.value?.check()) {
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
    checkAgain()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
    dialog.value = false
  } finally {
    busy.value = false
  }
}

watch(() => [route.params.museum, route.params.refreshId], () => load(), {immediate: true})
</script>

<style scoped>
.overridden-problem td {
  color: rgb(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
}
</style>
