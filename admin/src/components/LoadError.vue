<template>
  <v-alert
    v-if="message"
    id="load-error"
    type="error"
    density="compact"
    class="mb-4"
  >
    {{ message }}
  </v-alert>
</template>

<script setup lang="ts">
/** What a page shows when it couldn't load its data (Serena unreachable, or the session ended). */
defineProps<{message: string}>()
</script>
