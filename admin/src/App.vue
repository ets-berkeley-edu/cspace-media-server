<template>
  <v-app>
    <v-app-bar color="topbar" density="comfortable">
      <v-app-bar-title>
        Serena admin
        <v-chip
          v-if="session.environment"
          class="ml-2"
          size="small"
          variant="outlined"
        >
          {{ session.environment }}
        </v-chip>
      </v-app-bar-title>
      <template v-if="current">
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
        <v-list-item :to="{name: 'overview', params: {museum: current.museum}}" title="Overview" exact />
        <v-list-item id="nav-audit" :to="{name: 'audit', params: {museum: current.museum}}" title="Audit log" />
        <v-list-item id="nav-api" :to="{name: 'api', params: {museum: current.museum}}" title="API documentation" />
      </v-list>
    </v-navigation-drawer>
    <v-main>
      <router-view />
    </v-main>
  </v-app>
</template>

<script setup lang="ts">
import {computed} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {api} from '@/api'
import {refresh, session, signedInTo} from '@/session'

const route = useRoute()
const router = useRouter()

const current = computed(() => route.params.museum ? signedInTo(String(route.params.museum)) : undefined)

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
