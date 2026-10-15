<template>
  <v-table id="lookup-sizes" density="compact" class="mb-1">
    <thead>
      <tr class="text-no-wrap">
        <th>Size</th><th>Served</th><th>Why not</th><th>Cached copy</th><th>Last served</th><th>First cached</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="size in sizes" :key="size.size">
        <td>
          <!-- Each size opens its file (Richard, October 14, 2026). -->
          <button
            type="button"
            class="size-link"
            :title="`View the ${size.size} file`"
            @click="emit('open', size.size)"
          >
            {{ size.size }}
          </button>
        </td>
        <td>{{ size.served ? 'Yes' : 'No' }}</td>
        <td>{{ size.reason ? reasonOf(size.reason) : '' }}</td>
        <td>{{ size.stored ? `${size.stored.content_type}, ${bytes(size.stored.size)}` : '—' }}</td>
        <td>{{ size.stored?.last_served ? when(size.stored.last_served) : '—' }}</td>
        <td>{{ size.stored ? when(size.stored.fetched_at) : '—' }}</td>
      </tr>
    </tbody>
  </v-table>
</template>

<script setup lang="ts">
import type {LookupSize} from '@/api'
import {reasonOf, when} from '@/words'

// Media look up's sizes: each size's verdict and cached copy; a size's name opens its file.
defineProps<{sizes: LookupSize[]}>()
const emit = defineEmits<{open: [size: string]}>()

function bytes(n: number): string {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} bytes`
}
</script>

<style scoped>
.size-link {
  background: none;
  border: 0;
  color: rgb(var(--v-theme-primary));
  cursor: pointer;
  font: inherit;
  padding: 0;
  text-decoration: underline;
}
</style>
