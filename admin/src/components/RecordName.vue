<template>
  <span v-if="number" class="record-name">{{ number }}<CopyButton :value="number" label="identification number" /></span>
  <ShortCsid v-else :csid="csid" label="Media CSID" />
</template>

<script setup lang="ts">
import CopyButton from '@/components/CopyButton.vue'
import ShortCsid from '@/components/ShortCsid.vue'

// A Media record as staff know it: its identification number (D153), or its shortened Media CSID without one.
defineProps<{number: string | null | undefined, csid: string}>()
</script>

<style scoped>
.record-name {
  white-space: nowrap;
}
</style>
