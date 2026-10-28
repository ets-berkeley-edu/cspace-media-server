<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-1">{{ museumName(museum) }} refresh {{ refresh?.refresh_id }}</h1>
    <p v-if="refresh" class="mb-4">
      <RefreshState id="refresh-state" :state="refresh.state" :override="refresh.override" />
      · refresh date {{ refresh.refresh_date }}<span v-if="refresh.manual" id="refresh-manual"> · a manual refresh, with
        <template v-if="refresh.admin_refresh_from">the ETL's list for {{ refresh.admin_refresh_date }} (from
          <RefreshLink :id="refresh.admin_refresh_from" />)</template><template v-else>an uploaded list for
          {{ refresh.admin_refresh_date || refresh.refresh_date }}</template></span> · last change {{ when(refresh.updated_at) }}
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
      <!-- How far past, in red, with how many times the threshold it is (issue #120). -->
      <div v-if="refresh.check && timesOver(refresh.check)" id="override-overshoot">
        The servable list changes <DeltaPast :check="refresh.check" />.
      </div>
      <div v-else-if="overshoot" id="override-overshoot">{{ overshoot }}</div>
      <div><strong>Delta threshold overridden</strong> by {{ overrideBy(refresh.override) }} at {{ when(refresh.override.at) }}.</div>
      <div v-if="refresh.override.reason" id="override-reason">Reason: {{ overrideWords(refresh.override) }}</div>
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

    <!-- A manual refresh whose check passed waits for an admin (issue #118, MR9). -->
    <p v-if="refresh?.state === 'waiting'" id="refresh-waiting" class="mb-2">
      <strong>The check passed{{ refresh.override ? ' without the delta threshold' : '' }}.</strong> Nothing has changed
      yet: the refresh waits for an admin to run the servability update. Running it is in the audit log. If tonight's ETL
      refresh or another manual refresh starts first, Serena closes this one as abandoned.
    </p>
    <div v-if="refresh?.actions.length" class="mb-6">
      <v-btn
        v-if="refresh.actions.includes('run_update')"
        id="run-update"
        color="primary"
        variant="flat"
        :loading="busy"
        @click="runUpdate"
      >
        Run the servability update
      </v-btn>
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
        <p id="check-counts" class="mb-2"><CheckCounts :check="refresh.check" /></p>
        <!-- From 10 times the threshold (issue #120); the banner says it once the threshold is overridden. -->
        <FarPastNote
          v-if="!refresh.override"
          id="check-far-past"
          :check="refresh.check"
          :before-override="refresh.actions.includes('override_threshold')"
        />
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
          <p v-if="action === 'override_threshold' && refresh?.check && timesOver(refresh.check)" id="override-explanation" class="mb-4">
            The servable list check failed only because more rows change than the delta threshold allows: this list
            changes <DeltaPast :check="refresh.check" />. {{ explanations[action] }}
          </p>
          <p v-else class="mb-4">{{ explanations[action] }}</p>
          <FarPastNote
            v-if="action === 'override_threshold' && refresh?.check"
            id="override-far-past"
            :check="refresh.check"
            before-override
          />
          <!-- An override says why the change is expected, then the reason (issue #120); a retry, only a reason. -->
          <OverrideReason
            v-if="action === 'override_threshold'"
            ref="overrideField"
            :kind="kind"
            :reason="reason"
            @update:kind="(v: string) => kind = v"
            @update:reason="(v: string) => reason = v"
          />
          <ReasonField
            v-else
            ref="reasonField"
            v-model="reason"
            recorded="the refresh and the audit log"
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
import {useCheckAgain, working} from '@/checkAgain'
import CheckCounts from '@/components/CheckCounts.vue'
import DeltaPast from '@/components/DeltaPast.vue'
import FarPastNote from '@/components/FarPastNote.vue'
import OverrideReason from '@/components/OverrideReason.vue'
import ReasonField from '@/components/ReasonField.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import RefreshState from '@/components/RefreshState.vue'
import {alertsChanged, museumName} from '@/session'
import {overrideBy, overrideReason, overrideWords, timesOver, when} from '@/words'

// The actions with a dialog and a reason; "Run the servability update" has neither (the reason was given at the start).
type Dialogued = Exclude<RefreshAction, 'run_update'>
const titles: Record<Dialogued, string> = {
  retry_update: 'Retry the servability update',
  override_threshold: 'Override the delta threshold'
}
const explanations = computed<Record<Dialogued, string>>(() => ({
  retry_update: 'The worker runs the servability update again. Do this once whatever stopped it is fixed.',
  override_threshold: (refresh.value?.check && timesOver(refresh.value.check) ? ''
    : 'The servable list check failed only because more rows change than the delta threshold allows. ') +
    'Do this once you know the change is expected. Serena checks the same servable list again without the delta ' +
    'threshold (every other check still applies) and, if it passes, ' +
    `${refresh.value?.manual ? 'waits for an admin to run the servability update' : 'updates Serena from it'}. The team is emailed.`
}))

const route = useRoute()
const refresh = ref<Refresh | null>(null)
const error = ref('')
const dialog = ref(false)
const action = ref<Dialogued>('retry_update')
const reason = ref('')
const busy = ref(false)

const museum = computed(() => String(route.params.museum))
// Every action needs a reason (D62): its button stays enabled, and ReasonField says what's missing.
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
const overrideField = ref<InstanceType<typeof OverrideReason> | null>(null)
const kind = ref('') // why the change is expected, for an override (issue #120)

// While the worker checks or updates, the page checks again by itself (issue #108), so an override's re-check and
// update show without a reload. These checks don't count as activity: an open tab still signs out when idle.
const after = useCheckAgain(() => load(true))

// The override's reason is in the banner, so Reasons leaves out the line Serena adds for it.
const reasons = computed(() => {
  const given = refresh.value?.override?.reason
  return (refresh.value?.reasons || []).filter(line => !given || line !== overrideReason(refresh.value?.override || {}))
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
  const manual = !!refresh.value?.manual // a manual refresh waits for an admin after its check (issue #118)
  if (state === 'checking' || (state === 'updating' && !manual)) {
    return 'Serena is checking the same servable list again without the delta threshold (every other check still ' +
      `applies) and, if it passes, ${manual ? 'waits for an admin to run the servability update' : 'updates'}. ` +
      'This page checks again every few seconds until it\'s done.'
  }
  const then = state === 'updated' ? ' and updated from it' : state === 'waiting'
    ? ': it passed, and waits for an admin to run the servability update'
    : state === 'updating' ? ': it passed, and Serena is running the servability update' : ''
  return `Serena checked the same servable list again without the delta threshold (every other check still applied)${then}. ` +
    'The team was emailed.'
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

async function runUpdate() {
  if (!refresh.value) {
    return
  }
  busy.value = true
  error.value = ''
  try {
    refresh.value = await api.runUpdate(museum.value, refresh.value.refresh_id)
    checkAgain()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
  } finally {
    busy.value = false
  }
}

function open(which: Dialogued) {
  action.value = which
  reason.value = ''
  kind.value = ''
  reasonField.value?.reset()
  overrideField.value?.reset()
  error.value = ''
  dialog.value = true
}

async function act() {
  const field = action.value === 'override_threshold' ? overrideField.value : reasonField.value
  if (!refresh.value || !field?.check()) {
    return
  }
  busy.value = true
  try {
    const id = refresh.value.refresh_id
    if (action.value === 'retry_update') {
      refresh.value = await api.retryUpdate(museum.value, id, reason.value.trim())
    } else {
      refresh.value = await api.overrideThreshold(museum.value, id, kind.value, reason.value.trim())
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
