<template>
  <div class="v-data-table-header__content">
    <v-tooltip
      v-if="help"
      :text="help"
      location="top"
      max-width="320"
      interactive
    >
      <template #activator="{props: activator}">
        <span v-bind="activator" class="column-help" tabindex="0">{{ column.title }}</span>
      </template>
    </v-tooltip>
    <span v-else>{{ column.title }}</span>
    <v-icon
      v-if="column.sortable !== false"
      class="v-data-table-header__sort-icon"
      :icon="getSortIcon(column as never) as string"
    />
  </div>
</template>

<script setup lang="ts">
// A column's name with its description on hover or keyboard focus (D164): a dotted underline says there's one.
// Used through a v-data-table's header.<key> slot, so it draws the sort icon as Vuetify's own header does.
interface Column {
  title?: string
  sortable?: boolean
}

defineProps<{column: Column, getSortIcon: (column: never) => unknown, help?: string}>()
</script>

<style scoped>
.column-help {
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}
</style>
