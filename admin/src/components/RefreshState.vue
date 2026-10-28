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
    /><v-icon
      v-if="waiting"
      class="refresh-state-icon refresh-state-waiting mr-1"
      :icon="mdiClockOutline"
      size="small"
      aria-hidden="true"
    /><v-progress-circular
      v-if="working"
      class="refresh-state-spin mr-1"
      indeterminate
      size="12"
      width="2"
      aria-hidden="true"
    />{{ refreshStateOf({state, override}) }}
  </v-chip>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiAlertCircle, mdiClockOutline, mdiShieldAlert} from '@mdi/js'
import type {Override} from '@/api'
import {FAILED_STATES, WAITING_STATES, WORKING_STATES, byOverride, refreshStateOf, toneOf} from '@/words'

// A refresh's state as a pill, the same on Past refreshes, the refresh's page and Overview (issue #107). The label is
// what's read out; the icon only repeats that it failed.
// Given the refresh's override, one that updated only after an admin overrode the delta threshold reads "Updated by
// override", in the warning colour with the shield, so it doesn't look like a healthy one (issue #110).
// A refresh under way says whether Serena is waiting for the ETL job's next call, with a clock, or working, with a
// small spinner, still for those who ask for reduced motion (mockup version 55).
const props = defineProps<{state: string, override?: Override | null}>()
const failed = computed(() => FAILED_STATES.has(props.state))
const overridden = computed(() => byOverride(props))
const waiting = computed(() => WAITING_STATES.has(props.state))
const working = computed(() => WORKING_STATES.has(props.state))
</script>

<style scoped>
.refresh-state {
  font-weight: 600;
  white-space: nowrap;
}
@media (prefers-reduced-motion: reduce) {
  .refresh-state-spin :deep(svg),
  .refresh-state-spin :deep(circle) {
    animation: none;
  }
}
</style>
