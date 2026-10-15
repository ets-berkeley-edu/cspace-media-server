<template>
  <span class="request-path">
    <template v-if="media">
      <FileLink
        v-if="isCsid(media.media)"
        class="mono"
        :title="`View this file: ${path}`"
        :aria-label="`View this file: ${path}`"
        @open="emit('open')"
      >Media {{ short(media.media) }}</FileLink>
      <span v-else class="mono" :title="path">Media {{ short(media.media) }}</span>
    </template>
    <template v-else-if="parts">
      <FileLink
        v-if="openable"
        class="mono"
        :title="`View this file: ${path}`"
        :aria-label="`View this file: ${path}`"
        @open="emit('open')"
      >{{ short(parts.blob) }}</FileLink>
      <span v-else class="mono" :title="path">{{ short(parts.blob) }}</span>
    </template>
    <template v-else>
      <span class="mono" :class="{'sel-all': shortPath(path) === path}" :title="path">{{ shortPath(path) }}</span>
    </template>
    <!-- ⧉ only for a shortened value (Richard, October 14, 2026); a path shown whole is selected with one click. -->
    <CopyButton v-if="parts || media ? true : shortPath(path) !== path" :value="path" label="path" />
    <span v-if="!parts && !media" class="text-medium-emphasis"> (not a Blob path)</span>
  </span>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import FileLink from '@/components/FileLink.vue'
import {blobOfPath, blobPathOf, isCsid, mediaPathOf, short, shortPath} from '@/words'

// A request's path on Past requests (Richard, October 14, 2026): a Blob path Serena serves shows its Blob CSID,
// shortened (its size has its own column), and opens the file when the CSID is one CollectionSpace makes (D145). Any
// Media URL (pull request 15, D179) shows "Media <CSID…>" and opens the file the same way. Any other path shows itself,
// shortened (shortPath), with "(not a Blob path)". The path on hover; ⧉ copies it.
const props = defineProps<{path: string}>()
const emit = defineEmits<{open: []}>()
const parts = computed(() => blobPathOf(props.path))
// A Media URL (pull request 15, D179): "Media <CSID…>", its size in the Size column.
const media = computed(() => mediaPathOf(props.path))
const openable = computed(() => blobOfPath(props.path) !== null)
</script>

<style scoped>
.request-path {
  white-space: nowrap;
}
.mono {
  font-family: monospace;
}
</style>
