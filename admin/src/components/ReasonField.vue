<template>
  <v-textarea
    :id="id"
    ref="box"
    :model-value="modelValue"
    label="Reason (required)"
    :hint="`Required. Recorded in ${recorded}. No personal data, please.`"
    persistent-hint
    :error-messages="problem ? [problem] : []"
    rows="2"
    counter="500"
    @update:model-value="(v: string) => emit('update:modelValue', v)"
  />
</template>

<script setup lang="ts">
import {ref, watch} from 'vue'

// The reason every action that changes something needs (D62). Its button is never disabled, so it can be found and
// pressed with a keyboard or a screen reader (Richard, October 14, 2026): pressing it calls check(), which, without a
// reason, says so under the field and moves focus there; the hint says it's required and where it's recorded.
const props = withDefaults(defineProps<{modelValue: string, id?: string, recorded?: string}>(), {
  id: 'reason',
  recorded: 'the audit log'
})
const emit = defineEmits<{'update:modelValue': [value: string]}>()
const box = ref<{focus: () => void} | null>(null)
const problem = ref('')

watch(() => props.modelValue, value => {
  if (problem.value && value.trim() && value.length <= 500) {
    problem.value = ''
  }
})

/** Whether the reason will do; if not, says why under the field and moves focus there. */
function check(): boolean {
  const value = props.modelValue
  problem.value = !value.trim() ? 'Give a reason first.' : value.length > 500 ? 'At most 500 characters.' : ''
  if (problem.value) {
    box.value?.focus()
  }
  return !problem.value
}

/** A dialog opened again starts without the last message. */
function reset() {
  problem.value = ''
}

defineExpose({check, reset})
</script>
