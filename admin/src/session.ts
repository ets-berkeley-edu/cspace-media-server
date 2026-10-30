/**
 * Which museums this browser is signed in to (one session per museum: design, decided October 10, 2026).
 */
import {reactive, ref} from 'vue'
import type {AlertItem, SignedIn} from '@/api'
import {api} from '@/api'

export const session = reactive({
  environment: '',
  build: '',
  simulated: false, // every museum's server is the CollectionSpace simulator
  signedIn: [] as SignedIn[],
  loaded: false
})

export async function refresh(): Promise<void> {
  const me = await api.me()
  session.environment = me.environment
  session.build = me.build || ''
  session.simulated = !!me.simulated_cspace
  session.signedIn = me.sessions
  session.loaded = true
}

/** The museum's name as the app shows it (for example PAHMA), for page titles. */
export function museumName(museum: string): string {
  return signedInTo(museum)?.name || museum.toUpperCase()
}

export function signedInTo(museum: string): SignedIn | undefined {
  return session.signedIn.find(s => s.museum === museum)
}

/** Bumped when an alert is acknowledged or raised by an admin's action, so the banner and pages reload. */
export const alertsChanged = ref(0)

/** The current museum's unacknowledged alerts, as the banner last loaded them; the app bar's bell counts them (D137). */
export const waiting = reactive({museum: '', alerts: [] as AlertItem[]})
