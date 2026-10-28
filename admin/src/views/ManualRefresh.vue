<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Manual refresh</h1>
    <p class="mb-4" style="max-width: 100ch">
      Replace the current ETL list with one from a previous refresh or one you upload, when a refresh failed or its ETL
      list didn't reach Serena. Check it first: a dry run shows what would change, and changes nothing. Then apply it:
      Serena starts a manual refresh, checks the ETL list again and updates what it serves by itself. Follow it on Past
      refreshes or Overview.
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

    <v-form id="manual-form" @submit.prevent="checkList">
      <!-- The top card holds the action: the current and pending refreshes, the choice, the dry run and Apply. -->
      <section id="manual-card" class="manual-card mb-4" aria-labelledby="manual-card-head">
        <div id="manual-current" class="mb-3">
          <p class="mb-1">
            <strong>Current refresh:</strong>
            <template v-if="current">
              <RefreshLink :id="current.refresh_id" /> <RefreshState :state="current.state" :override="current.override" /><v-chip
                v-if="partly"
                id="manual-partly"
                class="ml-1 font-weight-bold"
                color="warning"
                size="small"
                variant="tonal"
              >
                partly replaced
              </v-chip>
              <span class="text-medium-emphasis"> · {{ current.rows?.toLocaleString('en-US') ?? '—' }} rows ·
                {{ partly ? 'Serena serves some of it and some of the pending refresh\'s ETL list' : 'Serena serves from it' }}</span>
            </template>
            <template v-else>none yet</template>
          </p>
          <p id="manual-pending" class="mb-0">
            <template v-if="!pending"><strong>Pending refresh:</strong> <span class="text-medium-emphasis">none.</span></template>
            <template v-else-if="FAILED_STATES.has(pending.state)">
              <strong class="text-error">Pending refresh, needs an admin:</strong> <RefreshLink :id="pending.refresh_id" />
              <RefreshState :state="pending.state" /> <span class="text-medium-emphasis">· its page has the details and other
                ways to fix it</span>
            </template>
            <template v-else>
              <strong>Pending refresh:</strong> <RefreshLink :id="pending.refresh_id" /> <RefreshState :state="pending.state" />
              <StateSince :refresh="pending" />
            </template>
          </p>
        </div>

        <!-- After Apply: what started, and where to follow it. The page doesn't follow the refresh. -->
        <section
          v-if="applied"
          id="manual-applied"
          class="manual-result"
          aria-labelledby="manual-applied-head"
        >
          <h2 id="manual-applied-head" class="text-h6 mb-1" tabindex="-1">
            Applied: <RefreshLink :id="applied.refresh.refresh_id" /> started
          </h2>
          <p class="mb-2">
            At {{ when(applied.refresh.created_at) }}, with {{ applied.with }}. Reason:
            <template v-if="applied.kind"><strong>{{ OVERRIDE_KINDS[applied.kind] }}</strong>: </template>{{ applied.reason }}<template v-if="applied.kind">
              (the delta threshold is overridden for it, and the team was emailed)
            </template>.
          </p>
          <p v-if="applied.replaced" id="manual-replaced" class="mb-2">
            It replaced the pending refresh <RefreshLink :id="applied.replaced" />, which is now Abandoned.
          </p>
          <p class="mb-2">
            Serena now checks the ETL list again and, if it passes, updates what it serves, by itself. Follow it on
            <router-link :to="{name: 'refreshes', params: {museum}}">Past refreshes</router-link> or
            <router-link :to="{name: 'overview', params: {museum}}">Overview</router-link>; if it fails, the team is
            emailed and its page says what to do.
          </p>
          <v-btn id="manual-again" variant="outlined" @click="startOver">Replace with another ETL list</v-btn>
        </section>

        <template v-else>
          <h2 id="manual-card-head" class="text-subtitle-1 font-weight-bold mb-1">Replace with:</h2>
          <v-radio-group
            id="manual-source"
            v-model="source"
            inline
            hide-details
            class="mb-2"
            aria-labelledby="manual-card-head"
          >
            <v-radio id="source-etl" label="Choose from previous" value="etl" />
            <v-radio id="source-upload" label="Upload one" value="upload" />
          </v-radio-group>
          <p v-if="source" id="manual-chosen" class="mb-2">
            <strong>The ETL list:</strong>
            <template v-if="source === 'etl'">
              <template v-if="pickedList">
                the one for {{ pickedList.refresh_date }}{{ older ? '' : ' (the newest)' }},
                {{ pickedList.rows.toLocaleString('en-US') }} rows, from <RefreshLink :id="pickedList.refresh_id" />.
              </template>
              <span v-else class="text-medium-emphasis">none yet. Choose one of the previous ETL lists below.</span>
            </template>
            <template v-else>
              <template v-if="chosen">an uploaded file, <span class="sha">{{ chosen.name }}</span>.</template>
              <span v-else class="text-medium-emphasis">none yet. Choose the ETL list file below.</span>
            </template>
          </p>
          <div id="pick-error" class="text-error text-caption mb-2" role="alert">{{ problems.pick }}</div>

          <!-- Shown once an ETL list is chosen, until its dry run: hidden, never disabled. -->
          <div v-if="listChosen && !dry" id="manual-check-step">
            <p class="mb-2 text-medium-emphasis">
              The check is a dry run: it shows what applying this ETL list would change, and changes nothing.
            </p>
            <v-btn
              id="manual-check"
              type="submit"
              color="primary"
              variant="flat"
              :loading="checking"
            >
              Check the ETL list
            </v-btn>
          </div>

          <section
            v-if="dry"
            id="manual-dry"
            class="manual-result mt-2"
            aria-labelledby="manual-dry-head"
          >
            <h2 id="manual-dry-head" class="text-h6 mb-1" tabindex="-1">{{ dryHead }}</h2>
            <p id="manual-checked" class="mb-2 text-medium-emphasis">
              {{ `Checked ${when(dry.checked_at)}${dry.against ? ', against the last ETL list update (' : '. '}` }}<RefreshLink
                v-if="dry.against"
                :id="dry.against.refresh_id"
              />{{ dry.against ? '). ' : '' }}Nothing has changed.
            </p>
            <p id="manual-counts" class="mb-2"><CheckCounts :check="dry.check" /></p>
            <FarPastNote
              v-if="deltaOnly"
              id="manual-far-past"
              :check="dry.check"
              before-override
            />
            <template v-if="failed && !deltaOnly">
              <v-table id="manual-problems" density="compact" class="mb-2">
                <thead>
                  <tr><th>Line</th><th>Field</th><th>Problem</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(found, i) in dry.check.errors" :key="i">
                    <td>{{ found.line || '' }}</td><td>{{ found.field }}</td><td>{{ found.problem }}</td>
                  </tr>
                </tbody>
              </v-table>
              <p class="mb-2 text-medium-emphasis">The first {{ dry.check.errors.length }} of {{ dry.check.error_count }}, by line.</p>
              <p class="mb-2">
                These problems can't be overridden. Fix the ETL list, or make a new one with the ETL list script on
                the ETL server, and check it again.
              </p>
              <v-btn id="manual-cancel" variant="outlined" @click="startOver">Cancel</v-btn>
            </template>

            <template v-else>
              <h3 class="text-subtitle-1 font-weight-bold mb-1">Apply it</h3>
              <p class="mb-2 text-medium-emphasis">
                Applying starts a manual refresh with this ETL list: Serena checks it again{{ deltaOnly ? ' without the delta threshold' : '' }}
                and, if it passes, updates what it serves.<template v-if="deltaOnly">
                  It overrides the delta threshold for
                  this refresh, and the team is emailed.
                </template>
              </p>
              <!-- An older list (MR6): what it does, and what's better. -->
              <v-alert
                v-if="older && pickedList && lists[0]"
                id="manual-older"
                type="warning"
                variant="tonal"
                density="compact"
                class="mb-3"
              >
                <strong>This isn't the newest ETL list.</strong> It's the ETL list for {{ pickedList.refresh_date }},
                {{ olderDays }} day{{ olderDays === 1 ? '' : 's' }} older than the newest ({{ lists[0].refresh_date }}).
                <p class="mt-1">
                  Applying it sets what Serena serves back to that day's public core while Solr keeps today's: the portals
                  may link to images Serena then refuses, and Serena may serve images that have since stopped being public.
                </p>
                <p class="mt-1">
                  <strong>Better:</strong> run the ETL list script on the ETL server (or ask whoever runs it) to make an
                  ETL list from today's public core, then pick it here or upload it. Serena can't start the ETL itself.
                  You'll be asked to confirm.
                </p>
              </v-alert>
              <!-- A pending refresh in the way (rule D): a busy one means waiting; one waiting is stopped, once confirmed. -->
              <v-alert
                v-if="pending && !FAILED_STATES.has(pending.state)"
                id="manual-open"
                type="warning"
                variant="tonal"
                density="compact"
                class="mb-3"
              >
                <template v-if="pendingBusy">
                  <strong>{{ pending.refresh_id }} is {{ pending.state === 'checking' ? 'checking' : 'applying' }} its ETL
                    list.</strong> Serena runs one refresh at a time and doesn't stop one while it's checking or applying:
                  wait for it to finish (a few minutes), then apply.
                </template>
                <template v-else>
                  <strong>{{ pending.manual ? 'A manual refresh' : 'Tonight\'s refresh' }}, {{ pending.refresh_id }}, is still
                    under way</strong> ({{ STATES[pending.state] || pending.state }}). Applying your ETL list stops it:
                  {{ pending.manual ? 'its ETL list won\'t be applied' : 'the ETL job\'s list won\'t be applied, and its run ends with an error' }}.
                  You'll be asked to confirm.
                </template>
              </v-alert>
              <v-checkbox
                v-if="source === 'upload'"
                id="confirm-live-core"
                v-model="confirmed"
                label="This ETL list was made from the live public core: I ran the ETL list script on the ETL server."
                :error-messages="problems.confirmed ? [problems.confirmed] : []"
              />
              <div style="max-width: 640px">
                <OverrideReason
                  v-if="deltaOnly"
                  id="manual-override-reason"
                  ref="overrideField"
                  :kind="overrideKind"
                  :reason="reason"
                  @update:kind="(v: string) => overrideKind = v"
                  @update:reason="(v: string) => reason = v"
                />
                <ReasonField
                  v-else
                  ref="reasonField"
                  v-model="reason"
                  class="mb-2"
                  recorded="the refresh and the audit log"
                />
              </div>
              <div class="d-flex flex-wrap ga-2">
                <v-btn
                  id="manual-apply"
                  :color="deltaOnly ? 'error' : 'primary'"
                  variant="flat"
                  :loading="applying"
                  @click="apply"
                >
                  {{ deltaOnly ? 'Apply with override' : 'Apply refresh' }}
                </v-btn>
                <v-btn id="manual-cancel" variant="outlined" @click="startOver">Cancel</v-btn>
              </div>
            </template>
          </section>
          <p
            v-if="checking"
            id="manual-checking"
            role="status"
            class="mt-2"
          >
            <v-progress-circular
              indeterminate
              size="16"
              width="2"
              class="mr-2"
              aria-hidden="true"
            />Checking the ETL list: a dry run, which changes nothing…
          </p>
        </template>
      </section>

      <!-- The bottom card: the previous ETL lists or the upload's fields, once one is chosen above. -->
      <v-expansion-panels
        v-if="source && !applied"
        id="manual-picker"
        v-model="pickerOpen"
        variant="accordion"
        style="max-width: 1000px"
      >
        <v-expansion-panel value="picker">
          <v-expansion-panel-title>{{ source === 'etl' ? 'Previous ETL lists' : 'Upload an ETL list file' }}</v-expansion-panel-title>
          <v-expansion-panel-text>
            <template v-if="source === 'etl'">
              <p class="mb-2 text-medium-emphasis">
                The last 10 ETL lists for {{ museumName(museum) }}, one per refresh, newest first, whatever the
                refresh's outcome. ETL lists an admin uploaded aren't here.
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
                        :aria-label="`Use the ETL list for ${list.refresh_date}${i === 0 ? ', the newest' : ''}`"
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
                    <td>{{ list.rows.toLocaleString('en-US') }}</td>
                    <td><RefreshState :state="list.state" :override="list.override" /></td>
                    <td class="text-no-wrap"><span class="sha" :title="list.sha256">{{ list.sha256.slice(0, 12) }}…</span><CopyButton :value="list.sha256" label="the SHA-256" /></td>
                    <td><RefreshLink :id="list.refresh_id" /></td>
                  </tr>
                  <tr v-if="loadedLists && !lists.length">
                    <td colspan="7">No ETL lists yet.</td>
                  </tr>
                </tbody>
              </v-table>
            </template>
            <div v-else style="max-width: 640px">
              <v-file-input
                id="file"
                v-model="file"
                label="The ETL list file (.tsv or .tsv.gz)"
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
            </div>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-form>

    <v-dialog v-model="confirming" max-width="600">
      <v-card id="manual-confirm-dialog">
        <v-card-title>{{ stopping ? `Stop ${pending?.refresh_id} and apply this ETL list?` : 'Apply an older ETL list?' }}</v-card-title>
        <v-card-text>
          <p v-if="older && pickedList && lists[0]" class="mb-3">
            <strong>The ETL list for {{ pickedList.refresh_date }} isn't the newest</strong> ({{ lists[0].refresh_date }}).
            If its check passes, what Serena serves goes back to that day's public core while Solr keeps today's: the
            portals may link to images Serena refuses, and Serena may serve images that are no longer public. An ETL list
            made today with the ETL list script on the ETL server is better.
          </p>
          <p v-if="stopping && pending">
            <strong>{{ pending.refresh_id }} is still under way</strong> ({{ STATES[pending.state] || pending.state }}).
            Applying your ETL list stops it: {{ pending.manual ? 'its ETL list won\'t be applied' : 'the ETL job\'s list won\'t be applied, and its run ends with an error' }}.
            Its page will say which refresh replaced it.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="confirming = false">Cancel</v-btn>
          <v-btn
            id="manual-confirm"
            :color="stopping ? 'error' : 'primary'"
            variant="flat"
            :loading="applying"
            @click="start"
          >
            {{ stopping ? 'Stop it and apply' : 'Apply the older ETL list' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, nextTick, onActivated, reactive, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {DryRun, Refresh, ServableList} from '@/api'
import {ApiError, api, problem} from '@/api'
import CheckCounts from '@/components/CheckCounts.vue'
import CopyButton from '@/components/CopyButton.vue'
import FarPastNote from '@/components/FarPastNote.vue'
import OverrideReason from '@/components/OverrideReason.vue'
import ReasonField from '@/components/ReasonField.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import RefreshState from '@/components/RefreshState.vue'
import StateSince from '@/components/StateSince.vue'
import WhenText from '@/components/WhenText.vue'
import {alertsChanged, museumName} from '@/session'
import {FAILED_STATES, OVERRIDE_KINDS, STATES, pacificDate, when} from '@/words'

// Manual refresh (issue #118; reworked October 28, 2026, mockup version 55): "Replace with:" a previous ETL list or an
// upload, a dry run that changes nothing and makes no refresh, then Apply refresh (or Apply with override), which starts
// an ordinary manual refresh that checks again and updates by itself; then a summary that points to Past refreshes and
// Overview. Kept alive (App.vue), one per museum, so coming back from a refresh's page finds it as it was left.
const route = useRoute()
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const source = ref<'' | 'etl' | 'upload'>('')
const lists = ref<ServableList[]>([])
const loadedLists = ref(false)
const picked = ref('')
const current = ref<Refresh | null>(null) // the newest updated refresh: Serena serves from it
const pending = ref<Refresh | null>(null) // the museum's open refresh, if any
const file = ref<File | File[] | null>(null)
const today = pacificDate()
const refreshDate = ref(today) // an uploaded list is made from the live public core, so it's today's (D75)
const dry = ref<DryRun | null>(null) // the dry run of the ETL list chosen now
const checking = ref(false)
const confirmed = ref(false)
const reason = ref('')
const overrideKind = ref('') // Apply with override: why the change is expected (issue #120)
const applying = ref(false)
const applied = ref<{refresh: Refresh, with: string, reason: string, kind: string, replaced: string} | null>(null)
const error = ref('')
const confirming = ref(false)
const pickerOpen = ref<string | undefined>('picker')

const chosen = computed(() => (Array.isArray(file.value) ? file.value[0] : file.value) || null)
const pickedList = computed(() => lists.value.find(list => list.refresh_id === picked.value) || null)
const older = computed(() => source.value === 'etl' && !!pickedList.value && pickedList.value !== lists.value[0])
const olderDays = computed(() => pickedList.value && lists.value[0]
  ? Math.round((Date.parse(lists.value[0].refresh_date) - Date.parse(pickedList.value.refresh_date)) / 864e5) : 0)
const listChosen = computed(() => source.value === 'etl' ? !!pickedList.value : source.value === 'upload' && !!chosen.value)
const partly = computed(() => pending.value?.state === 'update_failed')
const pendingBusy = computed(() => !!pending.value && ['checking', 'updating'].includes(pending.value.state))
// A pending refresh waiting for the ETL job (or a manual one left waiting) is stopped by Apply, once confirmed.
const stopping = computed(() => !!pending.value && !FAILED_STATES.has(pending.value.state) && !pendingBusy.value)
const failed = computed(() => dry.value?.check.result === 'failed')
// Failed on the delta threshold and nothing else, as Serena decides an override is possible.
const deltaOnly = computed(() => {
  const check = dry.value?.check
  return !!check && check.result === 'failed' && check.error_count === 1 && check.errors.length === 1 &&
    check.errors[0].field === 'file' && check.errors[0].problem.includes('threshold')
})
const dryHead = computed(() => !failed.value ? 'The dry run passed'
  : deltaOnly.value ? 'The dry run failed only on the delta threshold'
    : `The dry run found ${dry.value?.check.error_count} problem${dry.value?.check.error_count === 1 ? '' : 's'}`)

// What's missing, under each field, once a button is pressed; a field's message goes when it's filled.
const problems = reactive({pick: '', file: '', date: '', confirmed: ''})
type Focusable = {focus: () => void} | null
const dateField = ref<Focusable>(null)
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
const overrideField = ref<InstanceType<typeof OverrideReason> | null>(null)
watch(picked, () => { problems.pick = '' })
watch(chosen, () => { problems.file = '' })
watch(refreshDate, () => { problems.date = '' })
watch(confirmed, () => { problems.confirmed = '' })
// Choosing another ETL list drops the dry run's result.
watch([source, picked, chosen], () => { dry.value = null })

/** The ETL's lists and the current and pending refreshes, read again whenever the page is shown or after Apply. */
async function loadChoices() {
  try {
    const [found, status] = await Promise.all([api.servableLists(ownMuseum), api.status(ownMuseum)])
    lists.value = found.lists
    loadedLists.value = true
    current.value = status.current
    pending.value = status.pending
    if (picked.value && !lists.value.some(list => list.refresh_id === picked.value)) {
      picked.value = ''
    }
  } catch (e) {
    error.value = problem(e)
  }
}

void loadChoices()
let shown = false
onActivated(() => {
  if (shown) {
    void loadChoices()
  }
  shown = true
})

/** Back to "Replace with:" with nothing chosen: Cancel, and "Replace with another ETL list" after Apply. */
function startOver() {
  source.value = ''
  picked.value = ''
  file.value = null
  refreshDate.value = today
  dry.value = null
  confirmed.value = false
  reason.value = ''
  overrideKind.value = ''
  applied.value = null
  error.value = ''
  pickerOpen.value = 'picker'
  Object.assign(problems, {pick: '', file: '', date: '', confirmed: ''})
}

/** The dry run: Serena answers within the request, with nothing stored and nothing changed. */
async function checkList() {
  error.value = ''
  if (!listChosen.value) {
    problems.pick = source.value === 'etl' ? 'Choose one of the previous ETL lists first.' : ''
    problems.file = source.value === 'upload' ? 'Choose the ETL list file first.' : ''
    return
  }
  checking.value = true
  try {
    dry.value = source.value === 'etl'
      ? await api.dryRunList(ownMuseum, picked.value)
      : await api.dryRunUpload(ownMuseum, chosen.value as File)
    pickerOpen.value = undefined // it folds away once checked
    await nextTick()
    document.getElementById('manual-dry-head')?.focus()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The check didn\'t run.'
  } finally {
    checking.value = false
  }
}

/** Every field that's missing says so; focus goes to the first. */
function complete(): boolean {
  if (source.value === 'upload') {
    problems.date = /^\d{4}-\d{2}-\d{2}$/.test(refreshDate.value) && refreshDate.value <= today
      ? '' : `Give a refresh date of today (${today}) or earlier.`
    problems.confirmed = confirmed.value ? '' : 'Confirm the ETL list was made from the live public core.'
  }
  if (problems.date) {
    pickerOpen.value = 'picker'
  }
  const reasonGiven = deltaOnly.value ? overrideField.value?.check() ?? false : reasonField.value?.check() ?? false
  if (reasonGiven && problems.confirmed) {
    document.querySelector<HTMLInputElement>('#confirm-live-core')?.focus()
  } else if (reasonGiven && problems.date) {
    dateField.value?.focus()
  }
  return reasonGiven && !problems.date && !problems.confirmed
}

async function apply() {
  error.value = ''
  if (!complete()) {
    return
  }
  if (pendingBusy.value && pending.value) {
    error.value = `${pending.value.refresh_id} is ${pending.value.state === 'checking' ? 'checking' : 'applying'} its ` +
      'ETL list: wait for it to finish (a few minutes), then apply.'
    return
  }
  if (older.value || stopping.value) {
    confirming.value = true // MR6, rule D
    return
  }
  await start()
}

async function start() {
  applying.value = true
  error.value = ''
  const kind = deltaOnly.value ? overrideKind.value : ''
  const why = reason.value.trim()
  const replaced = pending.value?.refresh_id || ''
  try {
    const refresh = source.value === 'etl'
      ? await api.startFromList(ownMuseum, picked.value, why, replaced, kind)
      : await api.startRefresh(ownMuseum, chosen.value as File, refreshDate.value, why, replaced, kind)
    const listed = pickedList.value
    const what = source.value === 'etl' && listed
      ? `the ETL list for ${listed.refresh_date}, from ${listed.refresh_id}`
      : `the uploaded file ${chosen.value?.name || ''}`
    startOver()
    applied.value = {refresh, with: what, reason: why, kind, replaced}
    if (kind) {
      alertsChanged.value++ // the override's alert
    }
    await nextTick()
    document.getElementById('manual-applied-head')?.focus()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'The refresh didn\'t start.'
  } finally {
    applying.value = false
    confirming.value = false
    void loadChoices()
  }
}
</script>

<style scoped>
.manual-card {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 10px;
  padding: 12px 16px;
  max-width: 100ch;
}

.manual-result {
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  padding-top: 12px;
}

tr.picked td {
  background: rgba(var(--v-theme-primary), 0.08);
}

.sha {
  font-family: monospace;
}
</style>
