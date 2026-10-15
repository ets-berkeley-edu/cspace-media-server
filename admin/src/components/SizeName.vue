<template>
  <span v-if="!size" />
  <span v-else-if="sizes.includes(size)">{{ size }}</span>
  <span v-else class="text-no-wrap">{{ size }} <span class="text-medium-emphasis">(invalid)</span></span>
</template>

<script setup lang="ts">
// A request's size as it asked for it (Richard, October 14, 2026): a name that isn't one of the museum's sizes is
// followed by a muted "(invalid)", since the name shows the mistake.
defineProps<{size: string, sizes: string[]}>()
</script>
