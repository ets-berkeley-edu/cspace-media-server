<template>
  <v-chip
    class="refresh-state"
    :class="{'refresh-state-failed': failed}"
    :color="toneOf(state) || undefined"
    size="small"
    variant="tonal"
  >
    <v-icon
      v-if="failed"
      class="refresh-state-icon mr-1"
      :icon="mdiAlertCircle"
      size="small"
      aria-hidden="true"
    />{{ stateOf(state) }}
  </v-chip>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiAlertCircle} from '@mdi/js'
import {FAILED_STATES, stateOf, toneOf} from '@/words'

// A refresh's state as a pill, the same on Past refreshes, the refresh's page and Overview (issue #107). The label is
// what's read out; the icon only repeats that it failed.
const props = defineProps<{state: string}>()
const failed = computed(() => FAILED_STATES.has(props.state))
</script>

<style scoped>
.refresh-state {
  font-weight: 600;
  white-space: nowrap;
}
</style>
