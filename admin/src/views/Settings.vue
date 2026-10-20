<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Settings</h1>
    <p class="mb-4">
      This museum's settings. Each has a default value in Serena's configuration; an admin's value replaces it until
      someone chooses "Use default". Every change needs a reason and goes in the audit log, and changing the delta
      threshold or the audit retention also emails the team. Serena uses a change within about a minute.
    </p>
    <LoadError :message="error" />
    <v-alert
      v-if="saveError"
      id="settings-error"
      type="error"
      density="compact"
      class="mb-4"
    >
      {{ saveError }}
    </v-alert>
    <v-alert
      v-if="warning"
      id="settings-warning"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-4"
      closable
      @click:close="warning = ''"
    >
      {{ warning }}
    </v-alert>
    <v-card
      v-for="group in groups"
      :id="`settings-${group.key}`"
      :key="group.key"
      class="mb-4"
      variant="outlined"
      max-width="760"
    >
      <v-card-title class="text-subtitle-1">{{ group.title }}</v-card-title>
      <v-card-text>
        <p v-if="group.key === 'placeholder'" id="placeholder-help" class="text-body-2 mb-2">
          The Media record whose picture the public sees in place of an image the museum restricts. Serena checks it
          with CollectionSpace and fetches every size when it's saved; save it again after staff change its picture.
          Without one, Serena's generic "Image restricted" picture.
          <template v-if="data && !data.placeholder.blob_csid">
            This museum's ETL doesn't list a placeholder image yet, so a record named here is used once it does.
          </template>
        </p>
        <v-table density="compact">
          <tbody>
            <tr v-for="setting in group.settings" :id="`setting-${setting.name.replace('.', '-')}`" :key="setting.name">
              <td>{{ setting.label }}</td>
              <td class="font-weight-bold setting-value">
                <template v-if="setting.name === PLACEHOLDER && setting.value">
                  <!-- The named Media record (D169): its CSID, number and thumbnail. -->
                  <div class="d-flex align-center ga-3">
                    <img
                      v-if="!brokenThumbnail"
                      id="placeholder-thumbnail"
                      class="placeholder-thumbnail"
                      :src="api.previewUrl(museum, String(setting.value))"
                      alt="The placeholder image"
                      @error="brokenThumbnail = true"
                    >
                    <div>
                      <div class="mono sel-all font-weight-regular">{{ setting.value }}</div>
                      <div v-if="data?.placeholder.identification_number" class="font-weight-regular text-body-2">
                        Media <span class="sel-all">{{ data.placeholder.identification_number }}</span>
                      </div>
                    </div>
                  </div>
                </template>
                <template v-else>{{ shown(setting, setting.value) }}</template>
              </td>
              <td class="text-body-2">
                <span v-if="setting.changed">changed; default value {{ shown(setting, setting.default) }}</span>
                <span v-else>default value</span>
              </td>
              <td class="text-right text-no-wrap">
                <v-btn
                  size="small"
                  variant="outlined"
                  class="mr-2 change"
                  @click="open(setting, false)"
                >
                  Change
                </v-btn>
                <v-btn
                  v-if="setting.changed"
                  size="small"
                  variant="outlined"
                  class="reset"
                  @click="open(setting, true)"
                >
                  Use default
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card-text>
    </v-card>

    <v-dialog v-model="dialog" max-width="560">
      <v-card v-if="editing">
        <v-card-title>{{ toDefault ? 'Use default' : 'Change' }}: {{ editing.label }}</v-card-title>
        <v-card-text>
          <p v-if="toDefault" class="mb-4">
            Back to the default value, {{ shown(editing, editing.default) }} (now {{ shown(editing, editing.value) }}).
          </p>
          <v-select
            v-else-if="editing.name === 'audit_retention_days'"
            id="setting-value"
            v-model="value"
            :items="retentionChoices"
            label="Keep the audit log for"
          />
          <v-text-field
            v-else
            id="setting-value"
            ref="valueField"
            v-model="value"
            :label="editing.label"
            :error-messages="valueProblem ? [valueProblem] : []"
            :hint="hintFor(editing)"
            persistent-hint
          />
          <p v-if="editing.name === PLACEHOLDER && !toDefault" class="text-body-2 mt-2 mb-0">
            Saving checks the record with CollectionSpace and fetches each of its sizes, which can take a minute.
          </p>
          <p v-if="removing" id="retention-warning" class="text-warning mt-2">
            {{ removing }} audit {{ removing === 1 ? 'entry is' : 'entries are' }} older than that: the next daily
            removal deletes {{ removing === 1 ? 'it' : 'them' }}. Export the audit log first if you need {{ removing === 1 ? 'it' : 'them' }}.
          </p>
          <ReasonField
            ref="reasonField"
            v-model="reason"
            class="mt-4"
            :recorded="alerting ? 'the audit log and the alert emailed to the team' : 'the audit log'"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="dialog = false">Cancel</v-btn>
          <v-btn
            id="save-setting"
            color="primary"
            variant="flat"
            :loading="busy"
            @click="save"
          >
            {{ toDefault ? 'Use default' : 'Save' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {SettingItem, SettingsResponse} from '@/api'
import {ApiError, api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import ReasonField from '@/components/ReasonField.vue'
import {alertsChanged, museumName} from '@/session'
import {RETENTION_LABELS} from '@/words'

const GROUPS: Record<string, string> = {
  watchdog: 'Watchdog',
  etl: 'The ETL job',
  check: 'Servable list check',
  size_limits: 'Size limits',
  audit: 'Audit log',
  placeholder: 'Placeholder image'
}
// The placeholder image's Media record (decided October 14, 2026, D166 to D172).
const PLACEHOLDER = 'placeholder_media_csid'
// The allowed values (D88), from Serena's answer (D219), so the hint and the check on Save never drift from what
// Serena checks; a few words added where they help.
const HINT_EXTRA: Record<string, string> = {etl_step_timeout_seconds: ' (2 hours)'}
const number = (n: number | null | undefined) => (n ?? 0).toLocaleString('en-US')
function hintFor(setting: SettingItem): string {
  switch (setting.kind) {
  case 'whole':
  case 'number':
    return `${number(setting.min)} to ${number(setting.max)}${HINT_EXTRA[setting.name] || ''}`
  case 'time':
    return '00:00 to 23:59, Pacific'
  case 'csid':
    return 'The Media CSID of a record in this museum\'s CollectionSpace'
  default:
    return ''
  }
}
/** What's wrong with a value, in words, or '' (D219, D221): checked on Save, before anything is sent. */
function problemWith(setting: SettingItem, text: string): string {
  const inRange = (n: number) => n >= (setting.min ?? -Infinity) && n <= (setting.max ?? Infinity)
  switch (setting.kind) {
  case 'whole':
    return /^\d+$/.test(text) && inRange(Number(text)) ? ''
      : `Give a whole number from ${number(setting.min)} to ${number(setting.max)}.`
  case 'number':
    return /^(\d+(\.\d*)?|\.\d+)$/.test(text) && inRange(Number(text)) ? ''
      : `Give a number from ${number(setting.min)} to ${number(setting.max)}.`
  case 'time':
    return /^([01]\d|2[0-3]):[0-5]\d$/.test(text) ? '' : 'Give a time as HH:MM, from 00:00 to 23:59.'
  default:
    return '' // a Media CSID: Serena checks it with CollectionSpace (D170)
  }
}

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const data = ref<SettingsResponse | null>(null)
const error = ref('')
const saveError = ref('')
const dialog = ref(false)
const editing = ref<SettingItem | null>(null)
const toDefault = ref(false)
const value = ref<string | number>('')
const reason = ref('')
const busy = ref(false)
const warning = ref('')
const brokenThumbnail = ref(false)

const groups = computed(() => Object.entries(GROUPS).map(([key, title]) => ({
  key, title, settings: (data.value?.settings || []).filter(s => s.group === key)
})).filter(g => g.settings.length))
const retentionChoices = computed(() => (data.value?.audit_retention_choices || []).map(c => ({
  value: c.days, title: RETENTION_LABELS[c.days] || `${c.days} days`
})))
// How many entries a shorter retention would remove at the next daily removal (D98).
const removing = computed(() => {
  if (editing.value?.name !== 'audit_retention_days') {
    return 0
  }
  const days = toDefault.value ? Number(editing.value.default) : Number(value.value)
  return data.value?.audit_retention_choices.find(c => c.days === days)?.entries_removed || 0
})
// The button stays enabled (Richard, October 14, 2026): save() says what's missing, under its field.
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
const valueField = ref<{focus: () => void} | null>(null)
const valueProblem = ref('')
// A change to the delta threshold or the audit retention raises an alert (D89, D97).
const alerting = computed(() => ['delta_threshold_percent', 'audit_retention_days'].includes(editing.value?.name || ''))
watch(value, () => { valueProblem.value = '' })

function shown(setting: SettingItem, v: string | number | null): string {
  if (v === null) {
    return setting.name === PLACEHOLDER ? 'none: the generic picture' : 'none'
  }
  return setting.name === 'audit_retention_days' ? (RETENTION_LABELS[Number(v)] || `${v} days`) : String(v)
}

async function load() {
  error.value = ''
  try {
    data.value = await api.settings(museum.value)
  } catch (e) {
    error.value = problem(e)
  }
}

function open(setting: SettingItem, toTheDefault: boolean) {
  editing.value = setting
  toDefault.value = toTheDefault
  value.value = setting.value ?? ''
  reason.value = ''
  reasonField.value?.reset()
  saveError.value = ''
  dialog.value = true
  valueProblem.value = ''
}

async function save() {
  if (!editing.value) {
    return
  }
  if (!toDefault.value && String(value.value).trim() === '') {
    valueProblem.value = 'Give a value first.'
    valueField.value?.focus()
    return
  }
  if (!toDefault.value) {
    valueProblem.value = problemWith(editing.value, String(value.value).trim())
    if (valueProblem.value) {
      valueField.value?.focus()
      return
    }
  }
  if (!reasonField.value?.check()) {
    return
  }
  busy.value = true
  try {
    const name = editing.value.name
    data.value = toDefault.value
      ? await api.resetSetting(museum.value, name, reason.value.trim())
      : await api.changeSetting(museum.value, name, typeof value.value === 'string' ? value.value.trim() : value.value,
                                reason.value.trim())
    alertsChanged.value++ // a change to the delta threshold or the audit retention raises an alert
    warning.value = data.value?.warning || ''
    brokenThumbnail.value = false
    dialog.value = false
  } catch (e) {
    const message = e instanceof ApiError ? e.message : 'That didn\'t work.'
    if (!toDefault.value && e instanceof ApiError && e.status === 422 && editing.value) {
      // A value Serena refuses, any setting's (D220, as D170 for the placeholder's record): said under the field,
      // without the setting's name that the dialog already shows, and the dialog stays open.
      const prefix = `${editing.value.label}: `
      const said = message.startsWith(prefix) ? message.slice(prefix.length) : message
      valueProblem.value = said.charAt(0).toUpperCase() + said.slice(1)
      valueField.value?.focus()
    } else {
      saveError.value = message
      dialog.value = false
    }
  } finally {
    busy.value = false
  }
}

watch(museum, load, {immediate: true})
</script>

<style scoped>
.setting-value {
  white-space: nowrap;
}
.placeholder-thumbnail {
  width: 64px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
}
.mono {
  font-family: monospace;
}
</style>
