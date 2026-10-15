<template>
  <button
    type="button"
    class="file-link"
    :title="title || 'View this file'"
    @click="emit('open')"
  >
    <slot />
  </button>
</template>

<script setup lang="ts">
// A path or CSID that reads as plain text until hovered or focused, then as a link that opens the file (D145).
defineProps<{title?: string}>() // an aria-label given to it passes through to the button
const emit = defineEmits<{open: []}>()
</script>

<style scoped>
.file-link {
  background: none;
  border: 0;
  color: inherit;
  cursor: pointer;
  font: inherit;
  overflow-wrap: anywhere;
  padding: 0;
  text-align: left;
}
.file-link:hover,
.file-link:focus-visible {
  color: rgb(var(--v-theme-primary));
  text-decoration: underline;
}
</style>
