<template>
  <router-link class="refresh-link" :to="{name: 'refresh', params: {museum: museum || String(route.params.museum), refreshId: id}}">{{ id }}</router-link>
</template>

<script setup lang="ts">
import {useRoute} from 'vue-router'

// A refresh ID opens that refresh's own page (D157): from Alerts, the Audit log and "kept by" on Recalls.
defineProps<{id: string, museum?: string}>()
const route = useRoute()
</script>

<style scoped>
.refresh-link {
  font-family: monospace;
  white-space: nowrap;
}
</style>
