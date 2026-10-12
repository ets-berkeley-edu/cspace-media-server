/** How the app names refresh states and timestamps (one place, so every page says the same). */
export const STATES: Record<string, string> = {
  started: 'Started',
  received: 'File received',
  checking: 'Checking the servable list',
  check_failed: 'Servable list check failed',
  updating: 'Updating servability',
  updated: 'Updated',
  update_failed: 'Servability update failed',
  abandoned: 'Abandoned'
}

export function stateOf(state: string): string {
  return STATES[state] || state
}

export function when(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').replace(/(\.\d+)?(Z|\+00:00)$/, '').slice(0, 19) + ' UTC' : ''
}

/** A date in Pacific time, as YYYY-MM-DD: the museums' refresh dates are Pacific dates (design: The ETL API). */
export function pacificDate(daysAgo = 0, now: Date = new Date()): string {
  const day = new Date(now.getTime() - daysAgo * 24 * 60 * 60 * 1000)
  return new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(day)
}

/** An audit entry's details, one readable field per line (the stored entry is unchanged). */
export interface DetailLine {
  label: string
  value: string
  full?: string // the whole value, when the line shortens it (a SHA-256)
}

export function detailLines(details: Record<string, unknown>): DetailLine[] {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      const label = key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' ')
      if (key.endsWith('_at') && typeof value === 'number') {
        return {label, value: when(new Date(value * 1000).toISOString())}
      }
      if (key === 'sha256' && typeof value === 'string') {
        return {label: 'SHA-256', value: value.slice(0, 12) + '…', full: value}
      }
      return {label, value: typeof value === 'object' ? JSON.stringify(value) : String(value)}
    })
}

/** An audit entry's target, readable: an alert's key (`<refresh date>#<kind>#<subject>[#<n>]`) as kind, refresh date and subject. */
export function targetOf(action: string, target: string): string {
  if (action !== 'alert_acknowledge') {
    return target
  }
  const [refreshDate, kind, subject] = target.split('#')
  if (!kind) {
    return target
  }
  const what = kind.replace(/_/g, ' ')
  return [what.charAt(0).toUpperCase() + what.slice(1), refreshDate, subject !== refreshDate ? subject : '']
    .filter(Boolean).join(' · ')
}
