<template>
  <span class="short-csid">
    <FileLink
      v-if="openable"
      class="mono"
      :title="`View this file: ${csid}`"
      @open="emit('open')"
    >
      {{ short(csid) }}
    </FileLink>
    <span v-else class="mono" :title="csid">{{ short(csid) }}</span>
    <CopyButton v-if="short(csid) !== csid" :value="csid" :label="label || 'CSID'" />
  </span>
</template>

<script setup lang="ts">
import CopyButton from '@/components/CopyButton.vue'
import FileLink from '@/components/FileLink.vue'
import {short} from '@/words'

// A CSID on one line, shortened to both ends, with ⧉ to copy all of it (D154); the whole CSID on hover. With
// openable, it opens the file, as on Past requests (D145).
defineProps<{csid: string, label?: string, openable?: boolean}>()
const emit = defineEmits<{open: []}>()
</script>

<style scoped>
.short-csid {
  white-space: nowrap;
}
.mono {
  font-family: monospace;
}
</style>
