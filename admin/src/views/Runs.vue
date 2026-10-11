<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Runs</h1>
    <p class="mb-4">Each night's run for this museum, newest first. Open one to see its file, its checks and what an admin can do.</p>
    <v-table id="runs-table" density="compact">
      <thead>
        <tr>
          <th>Run</th>
          <th>Night</th>
          <th>State</th>
          <th>Rows</th>
          <th>Last change</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="run in runs" :key="run.run_id">
          <td><router-link :to="{name: 'run', params: {museum, runId: run.run_id}}">{{ run.run_id }}</router-link></td>
          <td>{{ run.night }}</td>
          <td>{{ stateOf(run.state) }}</td>
          <td>{{ run.rows ?? '' }}</td>
          <td>{{ when(run.updated_at) }}</td>
        </tr>
      </tbody>
    </v-table>
    <p v-if="loaded && !runs.length" class="mt-4">No runs yet.</p>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import type {RunSummary} from '@/api'
import {api} from '@/api'
import {stateOf, when} from '@/words'

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const runs = ref<RunSummary[]>([])
const loaded = ref(false)

watch(museum, async m => {
  loaded.value = false
  runs.value = (await api.runs(m)).runs
  loaded.value = true
}, {immediate: true})
</script>
