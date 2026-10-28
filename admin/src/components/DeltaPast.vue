<template>
  <span class="delta-past"><span class="delta-over">{{ check.delta_percent }}%</span> of the rows, {{ timesText(times) }}
    times the {{ check.threshold_percent }}% threshold<template v-if="times >= FAR_PAST_TIMES">: far past it</template></span>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import type {Check} from '@/api'
import {FAR_PAST_TIMES, timesOver, timesText} from '@/words'

// How far a check went past the delta threshold, in the banner and the override dialog (issue #120): the percent in
// red, and how many times the threshold it is. Shown only for a check past it.
const props = defineProps<{check: Check}>()
const times = computed(() => timesOver(props.check))
</script>

