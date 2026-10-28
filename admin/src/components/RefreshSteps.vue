<template>
  <ol
    v-if="at >= 0"
    id="refresh-steps"
    class="refresh-steps"
    :aria-label="`Progress: step ${at + 1} of 4, ${label}`"
  >
    <li v-for="(step, k) in STEPS" :key="k" :class="k < at ? 'done' : k > at ? '' : failed ? 'bad' : 'now'">
      <v-icon
        v-if="k < at"
        :icon="mdiCheck"
        size="small"
        aria-hidden="true"
      />
      <v-icon
        v-else-if="k === at && failed"
        :icon="mdiAlertCircle"
        size="small"
        aria-hidden="true"
      />
      <v-icon
        v-else-if="k === at && waiting"
        :icon="mdiClockOutline"
        size="small"
        aria-hidden="true"
      />
      <v-progress-circular
        v-else-if="k === at"
        class="refresh-steps-spin"
        indeterminate
        size="12"
        width="2"
        aria-hidden="true"
      />
      <span>{{ k < at ? step.done : k > at ? step.next : failed ? label : step.now }}</span>
    </li>
  </ol>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiAlertCircle, mdiCheck, mdiClockOutline} from '@mdi/js'
import {FAILED_STATES, STATES} from '@/words'

// A pending refresh's four steps, under its state line (mockup version 55, decided October 28, 2026): done ones
// ticked in green, the current one in blue with its clock or spinner (or, failed, in red), the rest to come.
const STEPS = [
  {done: 'Started', now: 'Waiting for the ETL list', next: 'Started'},
  {done: 'ETL list received', now: 'ETL list received', next: 'ETL list received'},
  {done: 'ETL list checked', now: 'Checking the ETL list', next: 'Check the ETL list'},
  {done: 'ETL list applied', now: 'Applying the ETL list', next: 'Apply the ETL list'}
]
const STEP_OF: Record<string, number> = {
  started: 0, received: 1, checking: 2, check_failed: 2, waiting: 3, updating: 3, update_failed: 3
}
const props = defineProps<{state: string}>()
const at = computed(() => STEP_OF[props.state] ?? -1)
const failed = computed(() => FAILED_STATES.has(props.state))
// A manual refresh waiting for an admin to apply its ETL list waits, as the first two steps do.
const waiting = computed(() => ['started', 'received', 'waiting'].includes(props.state))
const label = computed(() => STATES[props.state] || props.state)
</script>

<style scoped>
.refresh-steps {
  list-style: none;
  padding: 0;
  margin: 0 0 16px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  max-width: 760px;
}
.refresh-steps li {
  border-top: 4px solid rgba(var(--v-border-color), var(--v-border-opacity));
  padding-top: 6px;
  font-size: 0.8125rem;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  display: flex;
  gap: 5px;
  align-items: flex-start;
}
.refresh-steps li.done {
  border-color: rgb(var(--v-theme-success));
  color: rgb(var(--v-theme-success));
}
.refresh-steps li.now {
  border-color: rgb(var(--v-theme-info));
  color: rgb(var(--v-theme-info));
  font-weight: 600;
}
.refresh-steps li.bad {
  border-color: rgb(var(--v-theme-error));
  color: rgb(var(--v-theme-error));
  font-weight: 600;
}
.refresh-steps-spin {
  margin-top: 3px;
  flex: none;
}
@media (prefers-reduced-motion: reduce) {
  .refresh-steps-spin :deep(svg),
  .refresh-steps-spin :deep(circle) {
    animation: none;
  }
}
</style>
