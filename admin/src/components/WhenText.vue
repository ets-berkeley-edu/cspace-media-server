<template>
  <span class="when" :title="at || ''"><span>{{ parts[0] }}</span> <span>{{ parts[1] }}</span></span>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {whenParts} from '@/words'

// A time that breaks only between its date and its clock time, so a narrow column doesn't wrap it over three or four
// lines (D160).
const props = defineProps<{at: string | null | undefined}>()
const parts = computed(() => whenParts(props.at))
</script>

<style scoped>
.when > span {
  white-space: nowrap;
}
</style>
