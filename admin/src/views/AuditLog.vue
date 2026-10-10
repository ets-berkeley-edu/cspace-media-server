<template>
  <v-container>
    <h1 class="text-h5 mb-4">Audit log</h1>
    <v-table id="audit-table" density="compact">
      <thead>
        <tr>
          <th>When (UTC)</th>
          <th>Admin</th>
          <th>Action</th>
          <th>Target</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="entry in entries" :key="entry.at + entry.admin + entry.action">
          <td>{{ entry.at.replace('T', ' ').slice(0, 19) }}</td>
          <td>{{ entry.admin }}</td>
          <td>{{ entry.action.replace(/_/g, ' ') }}</td>
          <td>{{ entry.target }}</td>
          <td>{{ Object.keys(entry.details).length ? JSON.stringify(entry.details) : '' }}</td>
        </tr>
      </tbody>
    </v-table>
    <p v-if="loaded && !entries.length" class="mt-4">Nothing recorded yet.</p>
  </v-container>
</template>

<script setup lang="ts">
import {ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {AuditEntry} from '@/api'
import {api} from '@/api'

const route = useRoute()
const entries = ref<AuditEntry[]>([])
const loaded = ref(false)

watch(() => route.params.museum, async museum => {
  loaded.value = false
  entries.value = (await api.audit(String(museum))).entries
  loaded.value = true
}, {immediate: true})
</script>
