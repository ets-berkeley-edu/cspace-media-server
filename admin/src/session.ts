/**
 * Which museums this browser is signed in to (one session per museum: design, decided October 10, 2026).
 */
import {reactive, ref} from 'vue'
import type {SignedIn} from '@/api'
import {api} from '@/api'

export const session = reactive({
  environment: '',
  build: '',
  signedIn: [] as SignedIn[],
  loaded: false
})

export async function refresh(): Promise<void> {
  const me = await api.me()
  session.environment = me.environment
  session.build = me.build || ''
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
