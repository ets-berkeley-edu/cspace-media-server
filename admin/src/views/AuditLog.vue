<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <h1 id="page-title" class="text-h5">{{ museumName(museum) }} Audit log</h1>
      <v-spacer />
      <v-btn
        id="export-audit"
        variant="outlined"
        :href="api.auditExportUrl(museum)"
        download
      >
        Export CSV
      </v-btn>
    </div>
    <p class="mb-4">
      Every admin action of the last 30 days, newest first. Click a column's name to sort by it. "Export CSV" saves every
      entry this museum keeps, for as long as its audit retention (on the Settings page). The file holds admins'
      usernames and reasons: keep it as carefully as the log.
    </p>
    <LoadError :message="error" />
    <v-data-table
      id="audit-table"
      :headers="headers"
      :items="entries"
      :sort-by="[{key: 'at', order: 'desc'}]"
      :items-per-page="25"
      :items-per-page-options="PAGE_SIZES"
      :loading="!loaded && !error"
      density="compact"
      no-data-text="Nothing recorded in the last 30 days."
    >
      <template #[`item.at`]="{item}"><span class="text-no-wrap">{{ item.at.replace('T', ' ').slice(0, 19) }}</span></template>
      <template #[`item.action`]="{item}">{{ item.action.replace(/_/g, ' ') }}</template>
      <template #[`item.target`]="{item}"><span class="audit-target">{{ targetOf(item.action, item.target) }}</span></template>
      <template #[`item.details`]="{item}">
        <div class="audit-details">
          <div v-for="line in detailLines(item.details)" :key="line.label">
            {{ line.label }}: <span :title="line.full">{{ line.value }}</span>
          </div>
        </div>
      </template>
    </v-data-table>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {AuditEntry} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {PAGE_SIZES, detailLines, targetOf} from '@/words'

// Sortable: time, admin, action and target; the details aren't (D94).
const headers = [
  {title: 'When (UTC)', key: 'at'},
  {title: 'Admin', key: 'admin'},
  {title: 'Action', key: 'action'},
  {title: 'Target', key: 'target'},
  {title: 'Details', key: 'details', sortable: false}
]

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const entries = ref<AuditEntry[]>([])
const loaded = ref(false)
const error = ref('')

watch(museum, async m => {
  loaded.value = false
  error.value = ''
  try {
    entries.value = (await api.audit(m)).entries
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}, {immediate: true})
</script>

<style scoped>
.audit-target,
.audit-details {
  overflow-wrap: anywhere;
}
</style>
