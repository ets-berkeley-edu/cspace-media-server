/** How the app names run states and timestamps (one place, so every page says the same). */
export const STATES: Record<string, string> = {
  started: 'Started',
  received: 'File received',
  preflighting: 'Preflighting',
  ready: 'Preflight passed; waiting for the load report',
  preflight_failed: 'Preflight failed',
  solr_loaded: 'Public core loaded; waiting for the apply',
  applying: 'Applying',
  applied: 'Applied',
  apply_failed: 'Apply failed',
  abandoned: 'Abandoned'
}

export function stateOf(state: string): string {
  return STATES[state] || state
}

export function when(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').replace(/(\.\d+)?(Z|\+00:00)$/, '').slice(0, 19) + ' UTC' : ''
}
