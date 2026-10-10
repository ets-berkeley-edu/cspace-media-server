/**
 * Which museums this browser is signed in to (one session per museum: design, decided October 10, 2026).
 */
import {reactive} from 'vue'
import type {SignedIn} from '@/api'
import {api} from '@/api'

export const session = reactive({
  environment: '',
  signedIn: [] as SignedIn[],
  loaded: false
})

export async function refresh(): Promise<void> {
  const me = await api.me()
  session.environment = me.environment
  session.signedIn = me.sessions
  session.loaded = true
}

export function signedInTo(museum: string): SignedIn | undefined {
  return session.signedIn.find(s => s.museum === museum)
}
