<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Refreshes</h1>
    <p class="mb-4">This museum's daily refreshes, newest first. Open one to see its servable list, its checks and what an admin can do.</p>
    <LoadError :message="error" />
    <v-table id="refreshes-table" density="compact">
      <thead>
        <tr>
          <th>Refresh</th>
          <th>Refresh date</th>
          <th>State</th>
          <th>Rows</th>
          <th>Last change</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="refresh in refreshes" :key="refresh.refresh_id">
          <td><router-link :to="{name: 'refresh', params: {museum, refreshId: refresh.refresh_id}}">{{ refresh.refresh_id }}</router-link></td>
          <td>{{ refresh.refresh_date }}<span v-if="refresh.admin_refresh_date"> (admin refresh, list for {{ refresh.admin_refresh_date }})</span></td>
          <td>{{ stateOf(refresh.state) }}</td>
          <td>{{ refresh.rows ?? '' }}</td>
          <td>{{ when(refresh.updated_at) }}</td>
        </tr>
      </tbody>
    </v-table>
    <p v-if="loaded && !refreshes.length" class="mt-4">No refreshes yet.</p>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {RefreshSummary} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {stateOf, when} from '@/words'

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const refreshes = ref<RefreshSummary[]>([])
const loaded = ref(false)
const error = ref('')

watch(museum, async m => {
  loaded.value = false
  error.value = ''
  try {
    refreshes.value = (await api.refreshes(m)).refreshes
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}, {immediate: true})
</script>
