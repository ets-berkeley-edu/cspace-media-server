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
        <div class="text-caption text-medium-emphasis file-dialog-name">{{ file.name }}</div>
      </v-card-title>
      <v-card-text>
        <div class="file-dialog-picture">
          <img
            v-if="!failed"
            :src="file.url"
            :alt="file.title"
            @error="failed = true"
          >
          <p v-else id="file-dialog-none" class="pa-4">
            This page can't show it: a PDF, a TIFF original or a 3D file, or nothing cached and CollectionSpace
            unreachable. <a :href="file.url" target="_blank" rel="noopener">Open it in a new tab</a>.
          </p>
        </div>
        <p v-if="file.note" class="mt-3 mb-0">{{ file.note }}</p>
        <p class="mt-2 mb-0 text-medium-emphasis">
          Shown to you through the admin app, from Serena's cached copy or, without one, from CollectionSpace (Serena
          doesn't keep that), whether or not the public is served it. Your browser doesn't keep it either.
        </p>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn id="file-dialog-lookup" @click="lookUp">Media look up</v-btn>
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

/** A file to show: its picture's URL (through the admin API), what to look up, and how to name it (D145). */
export interface ShownFile {
  title: string
  name: string
  url: string
  lookup: string
  note?: string
}

const props = defineProps<{file: ShownFile | null}>()
const emit = defineEmits<{close: []}>()
const route = useRoute()
const router = useRouter()
const failed = ref(false)

watch(() => props.file, () => { failed.value = false })

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
