import {createRouter, createWebHistory} from 'vue-router'
import type {RouteLocationNormalized} from 'vue-router'
import {onSessionEnded} from '@/api'
import {refresh, session, signedInTo} from '@/session'
import Alerts from '@/views/Alerts.vue'
import AuditLog from '@/views/AuditLog.vue'
import Overview from '@/views/Overview.vue'
import RefreshDetail from '@/views/RefreshDetail.vue'
import Refreshes from '@/views/Refreshes.vue'
import LookUp from '@/views/LookUp.vue'
import Requests from '@/views/Requests.vue'
import Settings from '@/views/Settings.vue'
import SignIn from '@/views/SignIn.vue'
import StartRefresh from '@/views/StartRefresh.vue'
import Recalls from '@/views/Recalls.vue'

export const routes = [
  {path: '/', name: 'home', component: SignIn, meta: {public: true}},
  {path: '/sign-in', name: 'sign-in', component: SignIn, meta: {public: true}},
  {path: '/:museum', name: 'overview', component: Overview},
  {path: '/:museum/refreshes', name: 'refreshes', component: Refreshes},
  {path: '/:museum/refreshes/:refreshId', name: 'refresh', component: RefreshDetail},
  {path: '/:museum/start-refresh', name: 'start-refresh', component: StartRefresh},
  {path: '/:museum/alerts', name: 'alerts', component: Alerts},
  {path: '/:museum/requests', name: 'requests', component: Requests},
  {path: '/:museum/recalls', name: 'recalls', component: Recalls},
  {path: '/:museum/lookup', name: 'lookup', component: LookUp},
  {path: '/:museum/settings', name: 'settings', component: Settings},
  {path: '/:museum/audit', name: 'audit', component: AuditLog},
  // Swagger UI is large: loaded only when the page is opened.
  {path: '/:museum/api', name: 'api', component: () => import('@/views/ApiDocs.vue')}
]

export async function guard(to: RouteLocationNormalized) {
  if (!session.loaded) {
    await refresh()
  }
  if (to.meta.public) {
    // Signed in somewhere already: go to that museum, unless the admin came here to sign in to another one.
    if (to.name === 'home' && session.signedIn.length) {
      return {name: 'overview', params: {museum: session.signedIn[0].museum}}
    }
    return true
  }
  if (!signedInTo(String(to.params.museum))) {
    return {name: 'sign-in', query: {museum: String(to.params.museum), next: to.fullPath}}
  }
  return true
}

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes
})
router.beforeEach(guard)

/**
 * A page of this museum is where the admin goes back to after signing in (D161): only a path of the app, in the museum
 * they sign in to, so a link can't send them anywhere else.
 */
export function safeNext(next: unknown, museum: string): string | null {
  if (typeof next !== 'string' || !new RegExp(`^/${museum}(?:[/?#]|$)`).test(next)) {
    return null
  }
  const resolved = router.resolve(next)
  return resolved.matched.length && !resolved.meta.public && resolved.params.museum === museum ? resolved.fullPath : null
}

/** Serena said the museum's session ended (it timed out, or everyone was signed out): sign in again, saying why. */
export function sessionEnded(museum: string): void {
  session.signedIn = session.signedIn.filter(s => s.museum !== museum)
  const here = router.currentRoute.value
  if (here.meta.public || String(here.params.museum) !== museum) {
    return
  }
  void router.push({name: 'sign-in', query: {museum, timedOut: '1', next: here.fullPath}})
}

onSessionEnded(sessionEnded)

export default router
