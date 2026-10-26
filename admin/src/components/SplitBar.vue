<template>
  <!-- Served requests as one bar: from Serena's cache, then from CollectionSpace (issue #96). -->
  <div
    class="split"
    role="img"
    :aria-label="`${share(hits)} from the cache, ${share(misses)} from CollectionSpace`"
    :title="`${hits.toLocaleString('en-US')} from the cache, ${misses.toLocaleString('en-US')} from CollectionSpace`"
  >
    <template v-if="hits + misses">
      <span class="hit" :style="{width: `${100 * hits / (hits + misses)}%`}" />
      <span class="miss" :style="{width: `${100 * misses / (hits + misses)}%`}" />
    </template>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{hits: number, misses: number}>()
const share = (part: number) => props.hits + props.misses ? `${Math.round(100 * part / (props.hits + props.misses))}%` : '0%'
</script>

<style scoped>
.split {
  background: rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 5px;
  display: flex;
  height: 10px;
  min-width: 120px;
  overflow: hidden;
}
.hit {
  background: rgb(var(--v-theme-primary));
}
.miss {
  background: rgb(var(--v-theme-warning));
}
</style>
