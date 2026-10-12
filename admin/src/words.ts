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

/** How the audit retention's choices read (D97). */
export const RETENTION_LABELS: Record<number, string> = {
  90: '90 days', 183: '6 months', 365: '12 months', 548: '18 months', 730: '24 months', 1095: '36 months'
}

/** The page sizes the Refreshes, Alerts and Audit log tables offer; 25 to start (D92). */
export const PAGE_SIZES = [10, 25, 50, 100].map(n => ({value: n, title: String(n)}))

/** The Requests page's ranges (D106). */
export const REQUEST_RANGES = [
  {value: '1h', title: 'Last hour'},
  {value: '24h', title: 'Last 24 hours'},
  {value: '7d', title: 'Last 7 days'}
]

/** An unserved request's reason, readable: not_listed → "not listed". */
export function reasonOf(reason: string): string {
  return reason.replace(/_/g, ' ')
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
