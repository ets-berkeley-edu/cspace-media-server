import {createRouter, createWebHistory} from 'vue-router'
import type {RouteLocationNormalized} from 'vue-router'
import {refresh, session, signedInTo} from '@/session'
import AuditLog from '@/views/AuditLog.vue'
import Overview from '@/views/Overview.vue'
import SignIn from '@/views/SignIn.vue'

export const routes = [
  {path: '/', name: 'home', component: SignIn, meta: {public: true}},
  {path: '/sign-in', name: 'sign-in', component: SignIn, meta: {public: true}},
  {path: '/:museum', name: 'overview', component: Overview},
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
    return {name: 'sign-in', query: {museum: String(to.params.museum)}}
  }
  return true
}

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes
})
router.beforeEach(guard)

export default router
