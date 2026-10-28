<template>
  <div class="override-reason">
    <v-radio-group
      id="override-kind"
      :model-value="kind"
      label="Why is the change expected? (required)"
      :error-messages="kindProblem ? [kindProblem] : []"
      class="mb-2"
      @update:model-value="(v: string | null) => emit('update:kind', v || '')"
    >
      <v-radio
        v-for="(words, value) in OVERRIDE_KINDS"
        :id="`override-kind-${value}`"
        :key="value"
        :label="words"
        :value="value"
      />
    </v-radio-group>
    <ReasonField
      :id="id"
      ref="reasonField"
      :model-value="reason"
      :min="OVERRIDE_REASON_MIN"
      asks="what changed, and how you know it's expected"
      recorded="the refresh, the audit log and the alert emailed to the team"
      @update:model-value="(v: string) => emit('update:reason', v)"
    />
  </div>
</template>

<script setup lang="ts">
import {ref, watch} from 'vue'
import ReasonField from '@/components/ReasonField.vue'
import {OVERRIDE_KINDS, OVERRIDE_REASON_MIN} from '@/words'

// An override's reason (issue #120, mockup version 47): why the change is expected, one of the kinds, then the reason
// in the admin's own words, at least 20 characters. As with every reason, the button stays enabled: check() says
// what's missing under each field and moves focus to the first. The other dialogs' reasons are plain ReasonFields.
const props = withDefaults(defineProps<{kind: string, reason: string, id?: string}>(), {id: 'reason'})
const emit = defineEmits<{'update:kind': [value: string], 'update:reason': [value: string]}>()
const reasonField = ref<InstanceType<typeof ReasonField> | null>(null)
const kindProblem = ref('')

watch(() => props.kind, value => {
  if (value) {
    kindProblem.value = ''
  }
})

/** Whether the kind and the reason will do; if not, says why under each and moves focus to the first missing. */
function check(): boolean {
  kindProblem.value = props.kind ? '' : 'Choose why the change is expected.'
  const reasonGiven = reasonField.value?.check() ?? false
  if (kindProblem.value) {
    document.getElementById(`override-kind-${Object.keys(OVERRIDE_KINDS)[0]}`)?.focus()
  }
  return !kindProblem.value && reasonGiven
}

/** A dialog opened again starts without the last messages. */
function reset() {
  kindProblem.value = ''
  reasonField.value?.reset()
}

defineExpose({check, reset})
</script>
