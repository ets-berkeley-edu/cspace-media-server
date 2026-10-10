<template>
  <v-container fluid>
    <h1 class="text-h5 mb-2">ETL API documentation</h1>
    <p class="mb-4">
      Generated from Serena's code, so it always matches what this Serena accepts. Read-only: requests can't be sent
      from here.
    </p>
    <div id="swagger-ui" ref="target" />
  </v-container>
</template>

<script setup lang="ts">
import 'swagger-ui-dist/swagger-ui.css'
import SwaggerUIBundle from 'swagger-ui-dist/swagger-ui-bundle.js'
import {onMounted, ref} from 'vue'
import {useRoute} from 'vue-router'
import {api} from '@/api'

const route = useRoute()
const target = ref<HTMLElement | null>(null)

onMounted(() => {
  // Bundled with the app (no script from a CDN), and read-only (decided October 10, 2026).
  SwaggerUIBundle({
    url: api.etlApiUrl(String(route.params.museum)),
    domNode: target.value,
    supportedSubmitMethods: [],
    deepLinking: false
  })
})
</script>
