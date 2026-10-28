<template>
  <span class="check-counts">{{ check.rows }} rows; {{ check.added }} added, {{ check.removed }} removed,
    {{ check.changed }} changed<template v-if="check.previous_rows !== null">
      (<span :class="{'delta-over': times}">{{ check.delta_percent }}%</span> of the {{ check.previous_rows }} rows of
      the last servability update; <template v-if="times">{{ timesText(times) }} times the {{ check.threshold_percent }}%
        threshold</template><template v-else>the threshold is {{ check.threshold_percent }}%</template>)</template>.</span>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import type {Check} from '@/api'
import {timesOver, timesText} from '@/words'

// A check's counts, on a refresh's page and Manual refresh. Past the delta threshold, the percent is in red and says
// how many times the threshold it is (issue #120).
const props = defineProps<{check: Check}>()
const times = computed(() => timesOver(props.check))
</script>
