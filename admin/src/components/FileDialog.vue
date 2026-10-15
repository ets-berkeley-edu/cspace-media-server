<template>
  <v-dialog
    :model-value="!!file"
    max-width="760"
    @update:model-value="open => {
      if (!open) emit('close')
    }"
  >
    <v-card v-if="file" id="file-dialog">
      <v-card-title class="text-subtitle-1">
        {{ file.title }}
        <div class="text-caption text-medium-emphasis file-dialog-name">{{ file.name }}<CopyButton :value="file.name" /></div>
      </v-card-title>
      <v-card-text>
        <div class="file-dialog-picture">
          <img
            v-if="!failed"
            :src="file.url"
            :alt="file.title"
            @error="explain"
          >
          <p v-else-if="!why" class="pa-4 text-medium-emphasis">Finding out why it can't be shown…</p>
          <p v-else id="file-dialog-none" class="pa-4">
            {{ why.text }}<template v-if="why.open"> <a :href="file.url" target="_blank" rel="noopener">Open it in a new tab</a>.</template>
          </p>
        </div>
        <p v-if="file.note" class="mt-3 mb-0">{{ file.note }}</p>
        <p class="mt-2 mb-0 text-medium-emphasis">
          Shown to you through the admin app, from Serena's cached copy or, without one, from CollectionSpace (Serena
          doesn't keep that), whether or not Serena serves it to the public. Your browser doesn't keep it either.
        </p>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn
          v-if="file.lookup"
          id="file-dialog-lookup"
          variant="outlined"
          @click="lookUp"
        >
          Media look up
        </v-btn>
        <v-btn
          id="file-dialog-dismiss"
          color="primary"
          variant="flat"
          @click="emit('close')"
        >
          Dismiss
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import {ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {museumOfPath, sessionEndedFor, unexplained} from '@/api'
import CopyButton from '@/components/CopyButton.vue'

/**
 * A file to show: its picture's URL (through the admin API), what to look up, and how to name it (D145). Without
 * `lookup` there's no "Media look up" button: Media look up's own size links (Richard, October 14, 2026).
 */
export interface ShownFile {
  title: string
  name: string
  url: string
  lookup?: string
  note?: string
}

const props = defineProps<{file: ShownFile | null}>()
const emit = defineEmits<{close: []}>()
const route = useRoute()
const router = useRouter()
const failed = ref(false)
// Why there's no picture: the one real reason, not a list of every possible one (the UI review, October 13, 2026).
const why = ref<{text: string, open: boolean} | null>(null)

watch(() => props.file, () => {
  failed.value = false
  why.value = null
})

/** The picture didn't load: ask the admin API why, once (its 404 says which reason; a PDF loads but isn't a picture). */
async function explain() {
  failed.value = true
  const url = props.file?.url
  if (!url) {
    return
  }
  try {
    const response = await fetch(url, {credentials: 'same-origin', headers: {Accept: 'application/json'}})
    const type = response.headers.get('content-type') || ''
    if (response.ok) {
      response.body?.cancel().catch(() => undefined) // only its type was wanted
      why.value = type.startsWith('application/pdf')
        ? {text: 'A PDF: this page doesn\'t show it.', open: true}
        : {text: 'This page can\'t show this file.', open: true}
    } else if (response.status === 401) {
      why.value = {text: 'Your session ended: sign in again to see it.', open: false}
      const museum = museumOfPath(new URL(url, window.location.href).pathname.replace(/^\/admin\/v1/, ''))
      if (museum) {
        sessionEndedFor(museum)
      }
    } else {
      const body = await response.json().catch(() => null) // the admin API's problem: {detail}
      why.value = {text: body && typeof body.detail === 'string' ? body.detail : `Nothing to show: ${unexplained(response.status)}`, open: false}
    }
  } catch {
    why.value = {text: 'Nothing to show: Serena couldn\'t be reached.', open: false}
  }
}

async function lookUp() {
  const q = props.file?.lookup || ''
  emit('close')
  await router.push({name: 'lookup', params: {museum: String(route.params.museum)}, query: {q}})
}
</script>

<style scoped>
.file-dialog-name {
  font-family: monospace;
  overflow-wrap: anywhere;
  white-space: normal;
}
.file-dialog-picture {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  overflow: hidden;
  text-align: center;
}
.file-dialog-picture img {
  display: block;
  max-width: 100%;
  max-height: 60vh;
  margin: 0 auto;
}
</style>
