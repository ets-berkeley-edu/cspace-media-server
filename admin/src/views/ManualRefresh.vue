<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Manual refresh</h1>
    <p class="mb-4">
      Bring an ETL list into Serena now, when a refresh failed or its ETL list didn't reach Serena. Pick one of
      the ETL's recent lists or upload one: Serena checks it without changing anything. If the check passes, you run the
      ETL list update; if it fails only on the delta threshold, you can override it first.
    </p>
    <v-alert
      v-if="error"
      id="manual-error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ error }}
    </v-alert>

    <!-- The check's progress and result, here (layout A, decided October 27, 2026). -->
    <section
      v-if="run"
      id="manual-result"
      class="manual-result mb-6"
      aria-labelledby="manual-result-heading"
    >
      <h2 id="manual-result-heading" class="text-h6 mb-1">
        Your check: <RefreshLink :id="run.refresh_id" /> <RefreshState id="manual-result-state" :state="run.state" :override="run.override" /><OverrideMark
          v-if="!byOverride(run)"
          :override="run.override"
        />
      </h2>
      <p class="mb-2 text-medium-emphasis">
        With <template v-if="run.admin_refresh_from">
          the ETL's list for {{ run.admin_refresh_date }} (from
          <RefreshLink :id="run.admin_refresh_from" />)
        </template><template v-else>an uploaded list for {{ run.admin_refresh_date || run.refresh_date }}</template>.
      </p>
      <p v-if="run.override" id="manual-override-note" class="mb-2">
        Delta threshold overridden by {{ overrideBy(run.override) }} at {{ when(run.override.at) }}.
        <template v-if="run.override.reason">Reason: {{ overrideWords(run.override) }}</template>
      </p>
      <p v-if="run.check && !working([run])" id="manual-counts" class="mb-2"><CheckCounts :check="run.check" /></p>

      <template v-if="run.actions.includes('override_threshold')">
        <FarPastNote
          v-if="run.check"
          id="manual-far-past"
          :check="run.check"
          before-override
        />
        <p class="mb-2">
          The check failed only on the delta threshold. Override it only if you know the change is expected: Serena then
          checks the same list again without it, and you run the ETL list update as for a passed check. The team is
          emailed.
        </p>
        <v-btn
          id="manual-override"
          color="error"
          variant="flat"
          class="mb-2"
          @click="openOverride"
        >
          Override the delta threshold
        </v-btn>
      </template>
      <template v-else-if="run.state === 'check_failed' && run.check">
        <p class="mb-2"><strong>The ETL list has {{ run.check.error_count }} problem{{ run.check.error_count === 1 ? '' : 's' }}</strong>, so nothing changed.</p>
        <v-table id="manual-problems" density="compact" class="mb-2">
          <thead>
            <tr><th>Line</th><th>Field</th><th>Problem</th></tr>
          </thead>
          <tbody>
            <tr v-for="(found, i) in run.check.errors" :key="i">
              <td>{{ found.line || '' }}</td><td>{{ found.field }}</td><td>{{ found.problem }}</td>
            </tr>
          </tbody>
        </v-table>
        <p class="mb-2 text-medium-emphasis">The first {{ run.check.errors.length }} of {{ run.check.error_count }}, by line.</p>
        <p class="mb-2">
          These problems can't be overridden. Fix the list, or make a new one with the servable list script on the ETL
          server, and check it again.
        </p>
      </template>

      <p
        v-if="working([run])"
        id="manual-working"
        role="status"
        class="mb-2"
      >
        <v-progress-circular
          indeterminate
          size="16"
          width="2"
          class="mr-2"
          aria-hidden="true"
        />{{ workingText }}
      </p>
      <template v-if="run.state === 'waiting'">
        <p class="mb-2">
          <strong>The check passed{{ run.override ? ' without the delta threshold' : '' }}.</strong> Nothing has changed
          yet: the refresh waits for you.
        </p>
        <v-btn
          id="run-update"
          color="primary"
          variant="flat"
          class="mb-2"
          :loading="running"
          @click="runUpdate"
        >
          Run the ETL list update
        </v-btn>
        <p class="mb-2 text-medium-emphasis">
          Running it is in the audit log. If tonight's ETL refresh or another manual refresh starts first, Serena closes
          this one as abandoned; it doesn't time out.
        </p>
      </template>
      <p v-if="run.update" id="manual-updated" class="mb-2">
        Updated: {{ run.update.deleted }} deleted, {{ run.update.written }} written, {{ run.update.unchanged }} unchanged.
      </p>
      <p v-if="run.state === 'abandoned'" class="mb-2">
        Closed as abandoned: another refresh started before the ETL list update ran. Nothing changed.
      </p>
    </section>

    <v-form id="manual-form" @submit.prevent="submit">
      <v-radio-group
        id="manual-source"
        v-model="source"
        inline
        label="Where the ETL list comes from"
        hide-details
        class="mb-2"
      >
        <v-radio id="source-etl" label="A recent list from the ETL" value="etl" />
        <v-radio id="source-upload" label="Upload a file" value="upload" />
      </v-radio-group>

      <template v-if="source === 'etl'">
        <p class="mb-2 text-medium-emphasis">
          The last 10 ETL lists for {{ museumName(museum) }}, one per refresh, newest first, whatever the
          refresh's outcome. Lists an admin uploaded aren't here.
        </p>
        <v-table id="manual-lists" density="compact" class="mb-1">
          <thead>
            <tr>
              <th><span class="d-sr-only">Use</span></th><th>Refresh date</th><th>Uploaded</th><th>Rows</th>
              <th>The refresh's outcome</th><th>SHA-256</th><th>Refresh</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(list, i) in lists"
              :key="list.refresh_id"
              :class="{picked: picked === list.refresh_id}"
            >
              <td>
                <input
                  :id="`pick-${list.refresh_id}`"
                  v-model="picked"
                  type="radio"
                  name="manual-pick"
                  :value="list.refresh_id"
                  :aria-label="`Use the list for ${list.refresh_date}${i === 0 ? ', the newest' : ''}`"
                >
              </td>
              <td class="text-no-wrap">
                {{ list.refresh_date }}<v-chip
                  v-if="i === 0"
                  size="x-small"
                  class="ml-2"
                >
                  newest
                </v-chip>
              </td>
              <td><WhenText :at="list.uploaded_at" /></td>
              <td>{{ list.rows }}</td>
              <td><RefreshState :state="list.state" :override="list.override" /></td>
              <td class="text-no-wrap"><span class="sha" :title="list.sha256">{{ list.sha256.slice(0, 12) }}…</span><CopyButton :value="list.sha256" label="the SHA-256" /></td>
              <td><RefreshLink :id="list.refresh_id" /></td>
            </tr>
            <tr v-if="loadedLists && !lists.length">
              <td colspan="7">No ETL lists yet.</td>
            </tr>
          </tbody>
        </v-table>
        <div id="pick-error" class="text-error text-caption mb-2" role="alert">{{ problems.pick }}</div>
        <!-- An older list (MR6): what it does, and what's better. -->
        <v-alert
          v-if="older && pickedList && lists[0]"
          id="manual-older"
          type="warning"
          variant="tonal"
          density="compact"
          class="mb-4"
          style="max-width: 90ch"
        >
          <strong>This isn't the newest list.</strong> It's the ETL's list for {{ pickedList.refresh_date }},
          {{ olderDays }} day{{ olderDays === 1 ? '' : 's' }} older than the newest ({{ lists[0].refresh_date }}).
          <p class="mt-1">
            Using it sets what Serena serves back to that day's public core while Solr keeps today's: the portals may link to
            images Serena then refuses, and Serena may serve images that have since stopped being public.
          </p>
          <p class="mt-1">
            <strong>Better:</strong> run the servable list script on the ETL server (or ask whoever runs it) to make a
            list from today's public core, then pick it here or upload it. Serena can't start the ETL itself.
          </p>
        </v-alert>
      </template>
      <div v-else style="max-width: 640px">
        <v-file-input
          id="file"
          ref="fileField"
          v-model="file"
          label="The ETL list (.tsv or .tsv.gz)"
          accept=".tsv,.gz,.txt"
          :error-messages="problems.file ? [problems.file] : []"
        />
        <v-text-field
          id="refresh-date"
          ref="dateField"
          v-model="refreshDate"
          type="date"
          :max="today"
          label="The refresh date the ETL list is for"
          :error-messages="problems.date ? [problems.date] : []"
        />
        <v-checkbox
          id="confirm-live-core"
          ref="confirmField"
          v-model="confirmed"
          label="This ETL list was made from the live public core: I ran the servable list script on the ETL server."
          :error-messages="problems.confirmed ? [problems.confirmed] : []"
        />
      </div>

      <div style="max-width: 640px">
        <ReasonField
          ref="reasonField"
          v-model="reason"
          class="mb-2"
          recorded="the refresh and the audit log"
        />
      </div>
      <!-- The open refresh a check closes (MR13), or one Serena won't close while it's busy. -->
      <v-alert
        v-if="open"
        id="manual-open"
        type="warning"
        variant="tonal"
        density="compact"
        class="mb-4"
        style="max-width: 90ch"
      >
        <template v-if="openBusy">
          <strong>{{ open.refresh_id }} is being {{ open.state === 'checking' ? 'checked' : 'updated' }}.</strong> Serena
          doesn't close a refresh while it's checking or updating: wait for it to finish, then check a list.
        </template>
        <template v-else>
          <strong>{{ open.refresh_id }} is still open</strong> ({{ STATES[open.state] || open.state }}). Checking a list
          closes it as abandoned: it stops where it is and won't update. You'll be asked to confirm.
        </template>
      </v-alert>
      <!-- Never disabled (Richard, October 14, 2026): pressing it says what's missing, under its field. -->
      <v-btn
        id="manual-check"
        type="submit"
        color="primary"
        variant="flat"
        :loading="busy"
      >
        Check the ETL list
      </v-btn>
    </v-form>

    <v-dialog v-model="confirming" max-width="600">
      <v-card id="manual-confirm-dialog">
        <v-card-title>{{ open ? `Close ${open.refresh_id} and check this list?` : 'Check an older list?' }}</v-card-title>
        <v-card-text>
          <p v-if="older && pickedList && lists[0]" class="mb-3">
            <strong>The list for {{ pickedList.refresh_date }} isn't the newest</strong> ({{ lists[0].refresh_date }}). If
            its check passes and you run the ETL list update, what Serena serves goes back to that day's public core while
            Solr keeps today's: the portals may link to images Serena refuses, and Serena may serve images that are no
            longer public. A list made today with the servable list script on the ETL server is better.
          </p>
          <p v-if="open">
            <strong>{{ open.refresh_id }} is still open</strong> ({{ STATES[open.state] || open.state }}). Serena closes it
            as abandoned: it stops where it is and won't update. Its page will say which refresh closed it.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="confirming = false">Cancel</v-btn>
          <v-btn
            id="manual-confirm"
            :color="open ? 'error' : 'primary'"
            variant="flat"
            :loading="busy"
            @click="start"
          >
            {{ open ? 'Close it and check the list' : 'Check the older list' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="overriding" max-width="560">
      <v-card>
        <v-card-title>Override the delta threshold</v-card-title>
        <v-card-text>
          <p class="mb-4">
            The ETL list check failed only because more rows change than the delta threshold allows<span v-if="run?.check && timesOver(run.check)">: this list changes <DeltaPast :check="run.check" /></span>.
            Do this once
            you know the change is expected. Serena checks the same ETL list again without the delta threshold (every
            other check still applies) and, if it passes, waits for you to run the ETL list update. The team is emailed.
          </p>
          <FarPastNote
            v-if="run?.check"
            id="override-far-past"
            :check="run.check"
            before-override
          />
          <OverrideReason
            id="override-reason"
            ref="overrideField"
            :kind="overrideKind"
            :reason="overrideReason"
            @update:kind="(v: string) => overrideKind = v"
            @update:reason="(v: string) => overrideReason = v"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="overriding = false">Cancel</v-btn>
          <v-btn
            id="confirm-override"
            color="error"
            variant="flat"
            :loading="busy"
            @click="override"
          >
            Override the delta threshold
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onActivated, reactive, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {Refresh, ServableList} from '@/api'
import {ApiError, api, problem} from '@/api'
import {useCheckAgain, working} from '@/checkAgain'
import CheckCounts from '@/components/CheckCounts.vue'
import CopyButton from '@/components/CopyButton.vue'
import DeltaPast from '@/components/DeltaPast.vue'
import FarPastNote from '@/components/FarPastNote.vue'
import OverrideReason from '@/components/OverrideReason.vue'
import OverrideMark from '@/components/OverrideMark.vue'
import ReasonField from '@/components/ReasonField.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import RefreshState from '@/components/RefreshState.vue'
import WhenText from '@/components/WhenText.vue'
import {alertsChanged, museumName} from '@/session'
import {STATES, byOverride, lowerFirst, overrideBy, overrideWords, pacificDate, timesOver, when} from '@/words'

// Manual refresh (issue #118, decisions MR1 to MR15, reviewed October 27, 2026): one of the ETL's recent ETL lists
// or an uploaded one, checked without updating; a passed check waits for "Run the ETL list update", and a failure
// on the delta threshold alone can be overridden here. Kept alive (App.vue), one per museum, so coming back from a
// refresh's page finds it as it was left.
const route = useRoute()
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const source = ref<'etl' | 'upload'>('etl')
const lists = ref<ServableList[]>([])
const loadedLists = ref(false)
const picked = ref('')
const open = ref<Refresh | null>(null) // the museum's open refresh, which a check closes
const run = ref<Refresh | null>(null) // the refresh this page started
const file = ref<File | File[] | null>(null)
const today = pacificDate()
const refreshDate = ref(today) // an uploaded list is made from the live public core, so it's today's (D75)
const confirmed = ref(false)
const reason = ref('')
const busy = ref(false)
const running = ref(false)
const error = ref('')
const confirming = ref(false)
const overriding = ref(false)
const overrideReason = ref('')
const overrideKind = ref('') // why the change is expected (issue #120)

const chosen = computed(() => (Array.isArray(file.value) ? file.value[0] : file.value) || null)
const pickedList = computed(() => lists.value.find(list => list.refresh_id === picked.value) || null)
const older = computed(() => !!pickedList.value && pickedList.value !== lists.value[0])
const olderDays = computed(() => pickedList.value && lists.value[0]
  ? Math.round((Date.parse(lists.value[0].refresh_date) - Date.parse(pickedList.value.refresh_date)) / 864e5) : 0)
const openBusy = computed(() => working([open.value]))
const workingText = computed(() => {
  const state = run.value?.state
  if (state === 'updating') {
    return 'Serena is running the ETL list update.'
  }
  return run.value?.override
    ? 'Serena is checking the same ETL list again without the delta threshold (every other check still applies).'
    : 'Serena is checking the ETL list. Nothing changes until it passes and you run the ETL list update.'
})

// What's missing, under each field, once "Check the ETL list" is pressed; a field's message goes when it's filled.
const problems = reactive({pick: '', file: '', date: '', confirmed: ''})
type Focusable = {focus: () => void} | null
const fileField = ref<Focusable>(null)
const dateField = ref<Focusable>(null)
const confirmField = ref<Focusable>(null)
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
const overrideField = ref<InstanceType<typeof OverrideReason> | null>(null)
watch(picked, () => { problems.pick = '' })
watch(chosen, () => { problems.file = '' })
watch(refreshDate, () => { problems.date = '' })
watch(confirmed, () => { problems.confirmed = '' })

/** The ETL's lists and the museum's open refresh, read again whenever the page is shown or a check ends. */
async function loadChoices() {
  try {
    const [found, status] = await Promise.all([api.servableLists(ownMuseum), api.status(ownMuseum)])
    lists.value = found.lists
    loadedLists.value = true
    const newest = status.newest
    open.value = newest && !['updated', 'abandoned'].includes(newest.state) ? newest : null
    if (picked.value && !lists.value.some(list => list.refresh_id === picked.value)) {
      picked.value = ''
    }
  } catch (e) {
    error.value = problem(e)
  }
}

// While the check or the update runs, the page loads the refresh again by itself (checkAgain.ts).
const after = useCheckAgain(() => loadRun(true))

async function loadRun(background = false) {
  if (!run.value) {
    return
  }
  const before = working([run.value])
  try {
    run.value = await api.refresh(ownMuseum, run.value.refresh_id, background)
  } catch (e) {
    if (!background) {
      error.value = problem(e)
    }
  }
  after(working([run.value]))
  if (before && !working([run.value])) {
    void loadChoices() // it's done: the open refresh has changed
  }
}

void loadChoices()
let shown = false
onActivated(() => {
  if (shown) {
    void loadChoices()
    void loadRun()
  }
  shown = true
})

/** Every field that's missing says so; focus goes to the first. The reason is required (D62). */
function complete(): boolean {
  if (source.value === 'etl') {
    problems.pick = picked.value ? '' : 'Choose a list first.'
  } else {
    problems.file = chosen.value ? '' : 'Choose the ETL list first.'
    problems.date = /^\d{4}-\d{2}-\d{2}$/.test(refreshDate.value) && refreshDate.value <= today
      ? '' : `Give a refresh date of today (${today}) or earlier.`
    problems.confirmed = confirmed.value ? '' : 'Confirm the list was made from the live public core.'
  }
  const reasonGiven = reasonField.value?.check() ?? false
  // check() moved focus to the reason if it's missing; an earlier missing field takes it, a later one only without that.
  if (problems.pick) {
    document.querySelector<HTMLInputElement>('input[name="manual-pick"]')?.focus()
  } else if (source.value === 'upload') {
    const first = problems.file ? fileField.value : problems.date ? dateField.value
      : reasonGiven && problems.confirmed ? confirmField.value : null
    first?.focus()
  }
  return reasonGiven && (source.value === 'etl' ? !problems.pick : !problems.file && !problems.date && !problems.confirmed)
}

async function submit() {
  error.value = ''
  if (!complete()) {
    return
  }
  if (open.value && openBusy.value) {
    error.value = `Refresh ${open.value.refresh_id} is ${lowerFirst(STATES[open.value.state] || open.value.state)}: wait for it to finish.`
    return
  }
  if (older.value || open.value) {
    confirming.value = true // MR6, MR13
    return
  }
  await start()
}

async function start() {
  busy.value = true
  error.value = ''
  try {
    const openId = open.value?.refresh_id || ''
    run.value = source.value === 'etl'
      ? await api.startFromList(ownMuseum, picked.value, reason.value.trim(), openId)
      : await api.startRefresh(ownMuseum, chosen.value as File, refreshDate.value, reason.value.trim(), openId)
    picked.value = ''
    file.value = null
    confirmed.value = false
    reason.value = ''
    reasonField.value?.reset()
    after(working([run.value]))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The check didn\'t start.'
  } finally {
    busy.value = false
    confirming.value = false
    void loadChoices()
  }
}

async function runUpdate() {
  if (!run.value) {
    return
  }
  running.value = true
  error.value = ''
  try {
    run.value = await api.runUpdate(ownMuseum, run.value.refresh_id)
    after(working([run.value]))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The ETL list update didn\'t start.'
  } finally {
    running.value = false
  }
}

function openOverride() {
  overrideReason.value = ''
  overrideKind.value = ''
  overrideField.value?.reset()
  overriding.value = true
}

async function override() {
  if (!run.value || !overrideField.value?.check()) {
    return
  }
  busy.value = true
  try {
    run.value = await api.overrideThreshold(ownMuseum, run.value.refresh_id, overrideKind.value, overrideReason.value.trim())
    alertsChanged.value++ // the override's alert
    after(working([run.value]))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
  } finally {
    busy.value = false
    overriding.value = false
  }
}
</script>

<style scoped>
.manual-result {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 12px 16px;
  max-width: 90ch;
}

tr.picked td {
  background: rgba(var(--v-theme-primary), 0.08);
}

.sha {
  font-family: monospace;
}
</style>
