<template>
  <button
    type="button"
    class="copy-button"
    :class="{copied}"
    :title="copied ? 'Copied' : `Copy ${label || value}`"
    :aria-label="copied ? 'Copied' : `Copy ${label || value}`"
    @click.stop="copy"
  >
    <svg
      v-if="!copied"
      viewBox="0 0 24 24"
      aria-hidden="true"
    ><path fill="currentColor" :d="mdiContentCopy" /></svg>
    <span v-else>Copied</span>
  </button>
</template>

<script setup lang="ts">
import {mdiContentCopy} from '@mdi/js'
import {onBeforeUnmount, ref} from 'vue'

// ⧉ beside a value the page shortens with an ellipsis (a CSID, a path, a SHA-256): it copies the whole value, and says
// "Copied" for a moment (D154). A value shown whole has none: one click selects it (the sel-all class), ready to copy
// (Richard, October 14, 2026, which replaces D165). Always shown, so it's found without hovering and works with a
// keyboard or a touch screen.
const props = defineProps<{value: string, label?: string}>()
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

async function copy() {
  try {
    await navigator.clipboard.writeText(props.value)
  } catch {
    return // no clipboard (an insecure page, or the browser refused): nothing to say "Copied" about
  }
  copied.value = true
  clearTimeout(timer)
  timer = setTimeout(() => { copied.value = false }, 1500)
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.copy-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  min-width: 22px;
  height: 22px;
  margin-left: 4px;
  padding: 0 4px;
  border: 1px solid rgba(var(--v-border-color), 0.35);
  border-radius: 4px;
  background: rgb(var(--v-theme-surface));
  color: rgba(var(--v-theme-on-surface), 0.7);
  cursor: pointer;
  font-size: 0.7rem;
  line-height: 1;
}
.copy-button:hover,
.copy-button:focus-visible {
  border-color: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-primary));
}
.copy-button.copied {
  color: rgb(var(--v-theme-success));
}
.copy-button svg {
  width: 13px;
  height: 13px;
}
</style>
