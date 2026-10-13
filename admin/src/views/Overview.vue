<template>
  <v-container fluid>
    <h1 id="overview-title" class="text-h5 mb-4">{{ signed?.name }}</h1>
    <p class="mb-4">Signed in as {{ signed?.user }}.</p>
    <LoadError :message="error" />
    <p v-if="status?.newest" id="newest-refresh" class="mb-2">
      Newest refresh:
      <router-link :to="{name: 'refresh', params: {museum: String(route.params.museum), refreshId: status.newest.refresh_id}}">
        {{ status.newest.refresh_id }}
      </router-link>, {{ stateOf(status.newest.state) }}.
    </p>
    <p v-else-if="status" class="mb-2">No refreshes yet.</p>
    <p class="mb-6">
      What Serena served and couldn't serve is on the Requests page; "Look up a file" says why for any one file.
    </p>
    <v-btn
      id="sign-out-all"
      variant="outlined"
      color="error"
      @click="confirming = true"
    >
      Sign everyone out of {{ signed?.name }}
    </v-btn>
    <v-dialog v-model="confirming" max-width="480">
      <v-card>
        <v-card-title>Sign everyone out?</v-card-title>
        <v-card-text>
          Every admin signed in to {{ signed?.name }}, you included, is signed out at once. Use it after a
          Serena admin role has been removed in CollectionSpace.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="confirming = false">Cancel</v-btn>
          <v-btn id="confirm-sign-out-all" color="error" @click="signOutAll">Sign everyone out</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import type {Status} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {refresh, signedInTo} from '@/session'
import {stateOf} from '@/words'

const route = useRoute()
const router = useRouter()
const confirming = ref(false)
const signed = computed(() => signedInTo(String(route.params.museum)))
const status = ref<Status | null>(null)
const error = ref('')

async function load() {
  error.value = ''
  try {
    status.value = await api.status(String(route.params.museum))
  } catch (e) {
    error.value = problem(e)
  }
}

watch(() => route.params.museum, load, {immediate: true})

async function signOutAll() {
  confirming.value = false
  await api.signOutAll(String(route.params.museum))
  await refresh()
  await router.push({name: 'sign-in'})
}
</script>
