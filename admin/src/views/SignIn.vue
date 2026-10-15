<template>
  <v-container class="sign-in">
    <v-card max-width="480" class="mx-auto mt-8">
      <v-card-title>Sign in</v-card-title>
      <v-card-text>
        <v-alert
          v-if="timedOut"
          id="sign-in-timed-out"
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          Your {{ timedOutName }} session ended. Serena signs an admin out after 30 minutes without activity, after 8
          hours, or when an admin signs everyone out. Sign in again{{ next ? ', and you\'ll return to the page you were on' : '' }}.
        </v-alert>
        <p class="mb-4">
          Use your own CollectionSpace account for the museum. It needs the museum's Serena admin role.
          Serena checks it with the museum's CollectionSpace and doesn't keep your password.
        </p>
        <v-form id="sign-in-form" @submit.prevent="submit">
          <v-select
            id="museum"
            v-model="museum"
            :items="museums"
            item-title="name"
            item-value="key"
            label="Museum"
          />
          <v-text-field
            id="username"
            v-model="username"
            label="CollectionSpace username"
            autocomplete="username"
          />
          <v-text-field
            id="password"
            v-model="password"
            label="Password"
            type="password"
            autocomplete="current-password"
          />
          <v-alert
            v-if="error"
            id="sign-in-error"
            type="error"
            class="mb-4"
            density="compact"
          >
            {{ error }}
          </v-alert>
          <v-btn
            id="sign-in-button"
            type="submit"
            color="primary"
            variant="flat"
            :disabled="!museum || !username || !password"
            :loading="busy"
          >
            Sign in
          </v-btn>
        </v-form>
      </v-card-text>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onMounted, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import type {Museum} from '@/api'
import {ApiError, api} from '@/api'
import {safeNext} from '@/router'
import {refresh} from '@/session'

const route = useRoute()
const router = useRouter()
const museums = ref<Museum[]>([])
const museum = ref<string | null>(typeof route.query.museum === 'string' ? route.query.museum : null)
const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
// Sent here because the session ended under the admin (D161): say so, and go back to that page afterwards.
const timedOut = computed(() => route.query.timedOut === '1')
const timedOutName = computed(() => museums.value.find(m => m.key === route.query.museum)?.name || '')
const next = computed(() => typeof route.query.museum === 'string' ? safeNext(route.query.next, route.query.museum) : null)

onMounted(async () => {
  museums.value = await api.museums()
})

async function submit() {
  if (!museum.value) {
    return
  }
  error.value = ''
  busy.value = true
  try {
    await api.signIn(museum.value, username.value, password.value)
    password.value = ''
    await refresh()
    const back = museum.value === route.query.museum ? next.value : null
    await router.push(back || {name: 'overview', params: {museum: museum.value}})
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Signing in failed.'
    password.value = ''
  } finally {
    busy.value = false
  }
}
</script>
