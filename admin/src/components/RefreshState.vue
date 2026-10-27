<template>
  <v-chip
    class="refresh-state"
    :class="{'refresh-state-failed': failed, 'refresh-state-overridden': overridden}"
    :color="overridden ? 'warning' : toneOf(state) || undefined"
    size="small"
    variant="tonal"
  >
    <v-icon
      v-if="failed"
      class="refresh-state-icon mr-1"
      :icon="mdiAlertCircle"
      size="small"
      aria-hidden="true"
    /><v-icon
      v-if="overridden"
      class="refresh-state-icon mr-1"
      :icon="mdiShieldAlert"
      size="small"
      aria-hidden="true"
    />{{ refreshStateOf({state, override}) }}
  </v-chip>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiAlertCircle, mdiShieldAlert} from '@mdi/js'
import type {Override} from '@/api'
import {FAILED_STATES, byOverride, refreshStateOf, toneOf} from '@/words'

// A refresh's state as a pill, the same on Past refreshes, the refresh's page and Overview (issue #107). The label is
// what's read out; the icon only repeats that it failed.
// Given the refresh's override, one that updated only after an admin overrode the delta threshold reads "Updated by
// override", in the warning colour with the shield, so it doesn't look like a healthy one (issue #110).
const props = defineProps<{state: string, override?: Override | null}>()
const failed = computed(() => FAILED_STATES.has(props.state))
const overridden = computed(() => byOverride(props))
</script>

<style scoped>
.refresh-state {
  font-weight: 600;
  white-space: nowrap;
}
</style>
