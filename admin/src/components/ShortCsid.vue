<template>
  <span class="short-csid">
    <FileLink
      v-if="openable"
      class="mono"
      :title="`View this file: ${csid}`"
      :aria-label="`View this file: ${label || 'CSID'} ${csid}`"
      @open="emit('open')"
    >
      {{ short(csid) }}
    </FileLink>
    <template v-else>
      <span class="mono" :title="csid" aria-hidden="true">{{ short(csid) }}</span>
      <span class="visually-hidden">{{ csid }}</span>
    </template>
    <CopyButton v-if="short(csid) !== csid" :value="csid" :label="label || 'CSID'" />
  </span>
</template>

<script setup lang="ts">
import CopyButton from '@/components/CopyButton.vue'
import FileLink from '@/components/FileLink.vue'
import {short} from '@/words'

// A CSID on one line, shortened to both ends, with ⧉ to copy all of it (D154); the whole CSID on hover, and always
// to a screen reader, which reads the hidden whole CSID (or the link's label) instead of the shortened one. With
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
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
