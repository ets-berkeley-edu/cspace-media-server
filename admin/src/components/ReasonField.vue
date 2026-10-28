<template>
  <v-textarea
    :id="id"
    ref="box"
    :model-value="modelValue"
    label="Reason (required)"
    :hint="`Required${min ? `, at least ${min} characters` : ''}${asks ? `: ${asks}` : ''}. Recorded in ${recorded}. No personal data, please.`"
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
// Given min, it needs at least that many characters, spaces run together counting once, as Serena counts them (an
// override's reason, issue #120); asks says what to put in it.
const props = withDefaults(defineProps<{modelValue: string, id?: string, recorded?: string, min?: number, asks?: string}>(), {
  id: 'reason',
  recorded: 'the audit log',
  min: 0,
  asks: ''
})
const emit = defineEmits<{'update:modelValue': [value: string]}>()
const box = ref<{focus: () => void} | null>(null)
const problem = ref('')

function whatsWrong(value: string): string {
  const length = value.trim().split(/\s+/).join(' ').length
  return !value.trim() ? 'Give a reason first.' : value.length > 500 ? 'At most 500 characters.'
    : length < props.min ? `Say a little more: at least ${props.min} characters (${length} so far).` : ''
}

watch(() => props.modelValue, value => {
  if (problem.value && !whatsWrong(value)) {
    problem.value = ''
  }
})

/** Whether the reason will do; if not, says why under the field and moves focus there. */
function check(): boolean {
  problem.value = whatsWrong(props.modelValue)
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
