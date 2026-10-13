<template>
  <v-app>
    <v-app-bar color="topbar" density="comfortable">
      <v-app-bar-title>
        Serena admin
        <v-chip
          v-if="session.environment"
          id="environment"
          class="ml-2"
          size="small"
          variant="outlined"
        >
          {{ session.environment }}<template v-if="session.build"> · {{ session.build }}</template>
        </v-chip>
      </v-app-bar-title>
      <template v-if="current">
        <v-btn
          id="alerts-bell"
          icon
          :to="{name: 'alerts', params: {museum: current.museum}}"
          :aria-label="waitingCount ? `Alerts: ${waitingCount} unacknowledged` : 'Alerts'"
          :title="waitingCount ? `${waitingCount} unacknowledged alert${waitingCount === 1 ? '' : 's'}` : 'Alerts'"
        >
          <v-badge
            v-if="waitingCount"
            id="alerts-badge"
            color="error"
            :content="waitingCount > 99 ? '99+' : waitingCount"
          >
            <v-icon :icon="mdiBell" />
          </v-badge>
          <v-icon v-else :icon="mdiBell" />
        </v-btn>
        <v-btn
          id="settings-gear"
          icon
          :to="{name: 'settings', params: {museum: current.museum}}"
          :aria-label="`${current.name} settings`"
          :title="`${current.name} settings`"
        >
          <v-icon :icon="mdiCog" />
        </v-btn>
        <v-menu>
          <template #activator="{props: activator}">
            <v-btn v-bind="activator" id="museum-menu" variant="text">{{ current.name }} · {{ current.user }}</v-btn>
          </template>
          <v-list>
            <v-list-item
              v-for="signed in session.signedIn"
              :key="signed.museum"
              :to="{name: 'overview', params: {museum: signed.museum}}"
              :title="`${signed.name} (${signed.user})`"
            />
            <v-list-item id="sign-in-another" :to="{name: 'sign-in'}" title="Sign in to another museum" />
          </v-list>
        </v-menu>
        <v-btn id="sign-out" variant="text" @click="signOut">Sign out of {{ current.name }}</v-btn>
      </template>
    </v-app-bar>
    <v-navigation-drawer v-if="current" permanent>
      <v-list nav>
        <div v-for="group in NAV" :key="group.title">
          <v-list-subheader class="nav-group">{{ group.title }}</v-list-subheader>
          <v-list-item
            v-for="item in group.items"
            :id="`nav-${item.name}`"
            :key="item.name"
            :to="{name: item.name, params: {museum: current.museum}}"
            :title="item.title"
            :exact="item.name === 'overview'"
          />
        </div>
      </v-list>
    </v-navigation-drawer>
    <v-main>
      <AlertBanner v-if="current" />
      <router-view />
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
import {mdiBell, mdiCog} from '@mdi/js'
import {computed} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {api} from '@/api'
import AlertBanner from '@/components/AlertBanner.vue'
import {refresh, session, signedInTo, waiting} from '@/session'

// The left-hand menu's groups (the UI review, October 13, 2026). Alerts and Settings are in the app bar: the bell and
// the gear (D137, D138).
const NAV = [
  {title: 'Daily refresh', items: [
    {name: 'overview', title: 'Overview'}, {name: 'start-refresh', title: 'Start a refresh'},
    {name: 'refreshes', title: 'Past refreshes'}]},
  {title: 'Media records', items: [
    {name: 'requests', title: 'Past requests'}, {name: 'lookup', title: 'Media look up'}, {name: 'recalls', title: 'Recalls'}]},
  {title: 'Admin', items: [{name: 'audit', title: 'Audit log'}, {name: 'api', title: 'API documentation'}]}
]

const route = useRoute()
const router = useRouter()

const current = computed(() => route.params.museum ? signedInTo(String(route.params.museum)) : undefined)
const waitingCount = computed(() => current.value && waiting.museum === current.value.museum ? waiting.alerts.length : 0)

async function signOut() {
  if (!current.value) {
    return
  }
  await api.signOut(current.value.museum)
  await refresh()
  const next = session.signedIn[0]
  await router.push(next ? {name: 'overview', params: {museum: next.museum}} : {name: 'sign-in'})
}
</script>

<style scoped>
.nav-group {
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgb(var(--v-theme-on-surface));
  opacity: 0.85;
}
</style>
