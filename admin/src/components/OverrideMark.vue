<template>
  <v-tooltip v-if="override" :text="text" location="top">
    <template #activator="{props: activator}">
      <span v-bind="activator" class="override-mark" tabindex="0">
        <v-icon
          :icon="mdiShieldAlert"
          color="warning"
          size="small"
          aria-hidden="true"
        /><span class="d-sr-only">{{ text }}</span>
      </span>
    </template>
  </v-tooltip>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {mdiShieldAlert} from '@mdi/js'
import type {Override} from '@/api'
import {overrideBy, when} from '@/words'

// An overridden refresh's marker on Past refreshes and Overview (issue #108): a shield, its words in a tooltip and for
// screen readers, so it doesn't rely on the icon alone.
const props = defineProps<{override: Override | null | undefined}>()
const text = computed(() => props.override ? `Delta threshold overridden by ${overrideBy(props.override)} at ${when(props.override.at)}` : '')
</script>

<style scoped>
.override-mark {
  margin-left: 4px;
  vertical-align: text-bottom;
}
</style>
