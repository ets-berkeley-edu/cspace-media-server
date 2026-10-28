<template>
  <v-container fluid>
    <h1 id="overview-title" class="text-h5 mb-4">{{ signed?.name }}</h1>
    <p class="mb-4">Signed in as {{ signed?.user }}.</p>
    <LoadError :message="error" />
    <!-- The current refresh, which Serena serves from, and the pending one, side by side (mockup version 55). -->
    <div v-if="status" class="refresh-cards mb-6">
      <v-card id="current-card" variant="outlined" class="refresh-card">
        <v-card-text>
          <div class="refresh-card-label">Current refresh (Serena serves from it)</div>
          <template v-if="status.current">
            <div class="my-1">
              <RefreshState id="current-refresh-state" :state="status.current.state" :override="status.current.override" /><OverrideMark
                v-if="!byOverride(status.current)"
                id="current-override"
                :override="status.current.override"
              />
            </div>
            <div>
              <RefreshLink :id="status.current.refresh_id" /> · {{ status.current.rows?.toLocaleString('en-US') ?? '—' }} rows ·
              {{ when(status.current.updated_at) }}
            </div>
          </template>
          <div v-else id="current-none" class="my-1">None yet: Serena hasn't had an ETL list update.</div>
        </v-card-text>
      </v-card>
      <v-card
        id="pending-card"
        variant="outlined"
        class="refresh-card"
        :class="{'needs-admin': pending && FAILED_STATES.has(pending.state)}"
      >
        <v-card-text>
          <div class="refresh-card-label">Pending refresh<template v-if="pending && FAILED_STATES.has(pending.state)">: needs an admin</template></div>
          <template v-if="pending">
            <div class="my-1">
              <RefreshState id="pending-refresh-state" :state="pending.state" :override="pending.override" /><OverrideMark
                id="pending-override"
                :override="pending.override"
              />
            </div>
            <div><RefreshLink :id="pending.refresh_id" /> · refresh date {{ pending.refresh_date }}</div>
            <div v-if="fixText(pending)" id="pending-fix" class="mt-1">{{ fixText(pending) }}</div>
            <div v-else class="mt-1"><StateSince :refresh="pending" /></div>
          </template>
          <template v-else>
            <div id="pending-none" class="my-1 text-h6">None</div>
            <div>Nothing under way.</div>
          </template>
        </v-card-text>
      </v-card>
    </div>
    <p id="overview-pages" class="mb-6">
      What Serena served and couldn't serve is on the
      <router-link :to="{name: 'requests', params: {museum: String(route.params.museum)}}">Past requests</router-link>
      page; "<router-link :to="{name: 'lookup', params: {museum: String(route.params.museum)}}">Media look up</router-link>"
      says why for any one file.
    </p>
    <p id="overview-manual" class="mb-6">
      When a refresh failed, or its ETL list didn't reach Serena:
      <router-link :to="{name: 'manual-refresh', params: {museum: String(route.params.museum)}}">Manual refresh</router-link>.
    </p>
    <v-btn
      id="sign-out-all"
      variant="outlined"
      color="error"
      @click="confirming = true; signOutError = ''"
    >
      Sign everyone out of {{ signed?.name }}
    </v-btn>
    <v-dialog v-model="confirming" max-width="480">
      <v-card>
        <v-card-title>Sign everyone out?</v-card-title>
        <v-card-text>
          Every admin signed in to {{ signed?.name }}, you included, is signed out at once. Use it after a
          Serena admin role has been removed in CollectionSpace.
          <v-alert
            v-if="signOutError"
            id="sign-out-all-error"
            type="error"
            density="compact"
            class="mt-3"
          >
            {{ signOutError }}
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="confirming = false">Cancel</v-btn>
          <v-btn
            id="confirm-sign-out-all"
            color="error"
            variant="flat"
            :loading="signingOut"
            @click="signOutAll"
          >
            Sign everyone out
          </v-btn>
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
import {useCheckAgain, working} from '@/checkAgain'
import LoadError from '@/components/LoadError.vue'
import OverrideMark from '@/components/OverrideMark.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import RefreshState from '@/components/RefreshState.vue'
import StateSince from '@/components/StateSince.vue'
import {refresh, signedInTo} from '@/session'
import {FAILED_STATES, byOverride, fixText, when} from '@/words'

const route = useRoute()
const router = useRouter()
const confirming = ref(false)
const signed = computed(() => signedInTo(String(route.params.museum)))
const status = ref<Status | null>(null)
const error = ref('')
const signOutError = ref('')
const pending = computed(() => status.value?.pending ?? null)
const signingOut = ref(false)

// While the newest refresh is checking or updating, the page loads again by itself (checkAgain.ts); one that fails
// leaves what it shows and tries again.
const after = useCheckAgain(() => load(true))

async function load(background = false) {
  if (!background) {
    error.value = ''
  }
  try {
    status.value = await api.status(String(route.params.museum), background)
    error.value = ''
  } catch (e) {
    if (!background) {
      error.value = problem(e)
      after(false)
      return
    }
  }
  after(working([status.value?.newest]))
}

watch(() => route.params.museum, () => load(), {immediate: true})

// It says why when it fails, instead of doing nothing; the dialog stays open to try again.
async function signOutAll() {
  signOutError.value = ''
  signingOut.value = true
  try {
    await api.signOutAll(String(route.params.museum))
  } catch (e) {
    signOutError.value = problem(e)
    return
  } finally {
    signingOut.value = false
  }
  confirming.value = false
  await refresh()
  await router.push({name: 'sign-in', query: {museum: String(route.params.museum)}})
}
</script>

<style scoped>
.refresh-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 360px));
  gap: 12px;
}
.refresh-card-label {
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.refresh-card.needs-admin {
  border-color: rgb(var(--v-theme-error));
}
.refresh-card.needs-admin .refresh-card-label {
  color: rgb(var(--v-theme-error));
}
</style>
