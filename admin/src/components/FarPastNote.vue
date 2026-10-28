<template>
  <v-alert
    v-if="times >= FAR_PAST_TIMES"
    class="far-past mb-4"
    color="error"
    variant="tonal"
    :icon="mdiAlertCircle"
    density="compact"
    role="note"
  >
    <strong>Far past the delta threshold.</strong> {{ check.delta_percent }}% is {{ timesText(times) }} times the
    threshold: the last ETL list update had {{ check.previous_rows }} rows, this list has {{ check.rows }}. A change
    this large is usually a first load or the wrong file.
    <span v-if="beforeOverride">Check that the file is the right one before you override.</span>
  </v-alert>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiAlertCircle} from '@mdi/js'
import type {Check} from '@/api'
import {FAR_PAST_TIMES, timesOver, timesText} from '@/words'

// From 10 times the delta threshold, a red note under the check and in the override dialog (issue #120): it says
// nothing about what Serena serves or whether an override is allowed. Given beforeOverride, it says to check the file
// first.
const props = defineProps<{check: Check, beforeOverride?: boolean}>()
const times = computed(() => timesOver(props.check))
</script>
