<template>
  <v-container fluid>
    <h1 class="text-h5 mb-4">Runs</h1>
    <p class="mb-4">Each night's run for this museum, newest first. Open one to see its file, its checks and what an admin can do.</p>
    <LoadError :message="error" />
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
          <td>{{ run.night }}<span v-if="run.uploaded_night"> (upload of {{ run.uploaded_night }})</span></td>
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
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {stateOf, when} from '@/words'

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const runs = ref<RunSummary[]>([])
const loaded = ref(false)
const error = ref('')

watch(museum, async m => {
  loaded.value = false
  error.value = ''
  try {
    runs.value = (await api.runs(m)).runs
    loaded.value = true
  } catch (e) {
    error.value = problem(e)
  }
}, {immediate: true})
</script>
