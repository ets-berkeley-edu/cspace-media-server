<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Media look up</h1>
    <p class="mb-4">
      Why Serena serves a file or not. Give a file's URL or path, a Blob CSID or a Media CSID. This asks only Serena, never
      CollectionSpace, and shows the decision a request would get without a signed link.
    </p>
    <v-form class="d-flex align-start flex-wrap ga-4 mb-4" @submit.prevent="look">
      <v-text-field
        id="lookup-input"
        v-model="q"
        label="URL, path, Blob CSID or Media CSID"
        style="min-width: 320px"
        class="flex-grow-1"
      />
      <v-btn
        id="lookup-go"
        type="submit"
        color="primary"
        :loading="loading"
        :disabled="!q.trim()"
      >
        Look up
      </v-btn>
    </v-form>
    <LoadError :message="error" />
    <template v-if="result">
      <p id="lookup-refresh" class="mb-4">
        <template v-if="result.refresh">
          The last servability update was refresh {{ result.refresh.refresh_id }} (refresh date
          {{ result.refresh.refresh_date }}).
        </template>
        <template v-else>No servability update yet.</template>
      </p>
      <v-alert
        v-if="result.refused"
        id="lookup-refused"
        type="warning"
        variant="tonal"
        class="mb-4"
      >
        {{ result.input }} isn't served: {{ reasonOf(result.refused) }}.
      </v-alert>
      <v-card
        v-for="item in result.items"
        :key="item.blob_csid"
        variant="outlined"
        class="lookup-item mb-4"
      >
        <v-card-title class="text-subtitle-1">
          Blob {{ item.blob_csid }}<span v-if="item.media_csid">, Media record {{ item.media_csid }}</span>
        </v-card-title>
        <v-card-text>
          <v-table density="compact" class="mb-4 lookup-steps">
            <tbody>
              <tr v-for="step in item.steps" :key="step.check">
                <td class="text-no-wrap">{{ step.ok === true ? 'Yes' : step.ok === false ? 'No' : 'Depends' }}</td>
                <td class="text-no-wrap">{{ step.check }}</td>
                <td>{{ step.outcome }}</td>
              </tr>
            </tbody>
          </v-table>
          <v-table density="compact" class="lookup-sizes">
            <thead><tr><th>Size</th><th>Verdict</th><th>Reason</th><th>Stored copy</th></tr></thead>
            <tbody>
              <tr v-for="size in item.sizes" :key="size.size">
                <td>{{ size.size }}</td>
                <td>{{ size.verdict }}</td>
                <td>{{ size.reason ? reasonOf(size.reason) : '' }}</td>
                <td>
                  <span v-if="size.stored">{{ size.stored.content_type }}, {{ size.stored.size.toLocaleString('en-US') }}
                    bytes, fetched {{ size.stored.fetched_at }}</span>
                  <span v-else>none</span>
                </td>
              </tr>
            </tbody>
          </v-table>
        </v-card-text>
      </v-card>
    </template>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {Lookup} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {reasonOf} from '@/words'

const route = useRoute()
const museum = computed(() => String(route.params.museum))
const q = ref('')
const result = ref<Lookup | null>(null)
const loading = ref(false)
const error = ref('')

watch(museum, () => {
  result.value = null
  error.value = ''
})

async function look() {
  loading.value = true
  error.value = ''
  try {
    result.value = await api.lookup(museum.value, q.value.trim())
  } catch (e) {
    result.value = null
    error.value = problem(e)
  } finally {
    loading.value = false
  }
}
</script>
