<template>
  <v-container fluid>
    <h1 id="overview-title" class="text-h5 mb-4">{{ signed?.name }}</h1>
    <p class="mb-4">Signed in as {{ signed?.user }}.</p>
    <p class="mb-6">
      Runs and alerts, settings, takedowns and the unserved-requests pages arrive in the next pull requests.
      For now: the audit log and the ETL API's documentation.
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
import {computed, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {api} from '@/api'
import {refresh, signedInTo} from '@/session'

const route = useRoute()
const router = useRouter()
const confirming = ref(false)
const signed = computed(() => signedInTo(String(route.params.museum)))

async function signOutAll() {
  confirming.value = false
  await api.signOutAll(String(route.params.museum))
  await refresh()
  await router.push({name: 'sign-in'})
}
</script>
