<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Settings</h1>
    <p class="mb-4">
      This museum's settings. Each starts at the value in Serena's configuration; an admin's value replaces it until
      someone chooses "Use the starting value". Every change needs a reason and goes in the audit log, and changing the
      delta threshold or the audit retention also emails the team. Serena uses a change within about a minute.
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
        <v-table density="compact">
          <tbody>
            <tr v-for="setting in group.settings" :id="`setting-${setting.name.replace('.', '-')}`" :key="setting.name">
              <td>{{ setting.label }}</td>
              <td class="font-weight-bold setting-value">{{ shown(setting, setting.value) }}</td>
              <td class="text-body-2">
                <span v-if="setting.changed">changed; starting value {{ shown(setting, setting.starting) }}</span>
                <span v-else>the starting value</span>
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
                  variant="text"
                  class="reset"
                  @click="open(setting, true)"
                >
                  Use the starting value
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card-text>
    </v-card>

    <v-dialog v-model="dialog" max-width="560">
      <v-card v-if="editing">
        <v-card-title>{{ toStarting ? 'Use the starting value' : 'Change' }}: {{ editing.label }}</v-card-title>
        <v-card-text>
          <p v-if="toStarting" class="mb-4">
            Back to {{ shown(editing, editing.starting) }} (now {{ shown(editing, editing.value) }}).
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
            v-model="value"
            :label="editing.label"
            :hint="hints[editing.name] || hints[editing.group]"
            persistent-hint
          />
          <p v-if="removing" id="retention-warning" class="text-warning mt-2">
            {{ removing }} audit {{ removing === 1 ? 'entry is' : 'entries are' }} older than that: the next daily
            removal deletes {{ removing === 1 ? 'it' : 'them' }}. Export the audit log first if you need {{ removing === 1 ? 'it' : 'them' }}.
          </p>
          <v-textarea
            id="reason"
            v-model="reason"
            class="mt-4"
            label="Reason"
            hint="Recorded in the audit log. No personal data, please."
            persistent-hint
            rows="2"
            counter="500"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="dialog = false">Cancel</v-btn>
          <v-btn
            id="save-setting"
            color="primary"
            :disabled="!ready"
            :loading="busy"
            @click="save"
          >
            {{ toStarting ? 'Use the starting value' : 'Save' }}
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
import {alertsChanged} from '@/session'
import {RETENTION_LABELS} from '@/words'

const GROUPS: Record<string, string> = {
  watchdog: 'Watchdog',
  etl: 'The ETL job',
  check: 'Servable list check',
  size_limits: 'Size limits',
  audit: 'Audit log'
}
// The allowed values (D88); Serena checks them too.
const hints: Record<string, string> = {
  watchdog_deadline: '00:00 to 23:59, Pacific',
  etl_poll_interval_seconds: '5 to 300',
  etl_step_timeout_seconds: '60 to 7,200 (2 hours)',
  delta_threshold_percent: '0.1 to 100',
  size_limits: '1 to 2,048'
}

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const data = ref<SettingsResponse | null>(null)
const error = ref('')
const saveError = ref('')
const dialog = ref(false)
const editing = ref<SettingItem | null>(null)
const toStarting = ref(false)
const value = ref<string | number>('')
const reason = ref('')
const busy = ref(false)

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
  const days = toStarting.value ? Number(editing.value.starting) : Number(value.value)
  return data.value?.audit_retention_choices.find(c => c.days === days)?.entries_removed || 0
})
const ready = computed(() => reason.value.trim().length > 0 && reason.value.length <= 500 &&
  (toStarting.value || String(value.value).trim() !== ''))

function shown(setting: SettingItem, v: string | number): string {
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

function open(setting: SettingItem, starting: boolean) {
  editing.value = setting
  toStarting.value = starting
  value.value = setting.value
  reason.value = ''
  saveError.value = ''
  dialog.value = true
}

async function save() {
  if (!editing.value) {
    return
  }
  busy.value = true
  try {
    const name = editing.value.name
    data.value = toStarting.value
      ? await api.resetSetting(museum.value, name, reason.value.trim())
      : await api.changeSetting(museum.value, name, typeof value.value === 'string' ? value.value.trim() : value.value,
                                reason.value.trim())
    alertsChanged.value++ // a change to the delta threshold or the audit retention raises an alert
    dialog.value = false
  } catch (e) {
    saveError.value = e instanceof ApiError ? e.message : 'That didn\'t work.'
    dialog.value = false
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
</style>
