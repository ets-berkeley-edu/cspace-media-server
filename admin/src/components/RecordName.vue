<template>
  <span v-if="number" class="record-name sel-all">{{ number }}</span>
  <ShortCsid v-else :csid="csid" label="Media CSID" />
</template>

<script setup lang="ts">
import ShortCsid from '@/components/ShortCsid.vue'

// A Media record as staff know it: its identification number (D153), shown whole, so one click selects it and there's
// no ⧉ (Richard, October 14, 2026); or its shortened Media CSID, with ⧉, without one.
defineProps<{number: string | null | undefined, csid: string}>()
</script>

<style scoped>
.record-name {
  white-space: nowrap;
}
</style>
