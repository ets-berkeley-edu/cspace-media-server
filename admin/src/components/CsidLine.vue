<template>
  <span class="csid-line">
    <span class="mono sel-all">{{ csid }}</span> ·
    <button
      type="button"
      class="view-file"
      :aria-label="`View file: ${what} ${csid}`"
      @click="emit('open')"
    >
      View file
    </button>
  </span>
</template>

<script setup lang="ts">
// A CSID shown whole, as in an opened Recalls row (Richard, October 14, 2026): plain text, so one click selects all of
// it (no ⧉, since nothing is shortened), followed by "View file", which opens the file in a dialog.
defineProps<{csid: string, what: string}>()
const emit = defineEmits<{open: []}>()
</script>

<style scoped>
.csid-line {
  white-space: nowrap;
}
.mono {
  font-family: monospace;
}
.view-file {
  background: none;
  border: 0;
  color: rgb(var(--v-theme-primary));
  cursor: pointer;
  font: inherit;
  padding: 0;
  text-decoration: underline;
}
</style>
