<template>
  <span
    v-if="line.text"
    id="state-detail"
    class="state-detail"
    :class="{'text-warning': line.late}"
  >
    {{ line.late ? `${line.text} ${line.late}` : line.text }}
  </span>
</template>

<script setup lang="ts">
import {computed, onBeforeUnmount, ref} from 'vue'
import {stateSince} from '@/words'

// Beside a refresh's state where there's room (mockup version 55): since when it has waited or worked, and what's
// normal; past the watchdog's deadline, in the warning colour. The minutes move on by themselves.
const props = defineProps<{refresh: {state: string, updated_at: string, deadline_at?: string | null}}>()
const now = ref(new Date())
const timer = setInterval(() => { now.value = new Date() }, 30000)
onBeforeUnmount(() => clearInterval(timer))
const line = computed(() => stateSince(props.refresh, now.value))
</script>
