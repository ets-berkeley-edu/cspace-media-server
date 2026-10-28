/** How the app names refresh states and timestamps (one place, so every page says the same). */
// Mockup version 55 (decided October 28, 2026): a refresh under way says whether Serena is waiting for the ETL job's
// next call (started, received) or working (checking, updating), in the ETL list's words.
export const STATES: Record<string, string> = {
  started: 'Waiting for the ETL list',
  received: 'ETL list received',
  checking: 'Checking the ETL list',
  check_failed: 'ETL list check failed',
  updating: 'Applying the ETL list',
  updated: 'Updated',
  update_failed: 'ETL list update failed',
  waiting: 'Waiting for the ETL list update', // a manual refresh's passed check (issue #118)
  abandoned: 'Abandoned'
}

/** A state's words inside a sentence: "checking the ETL list", keeping "ETL" as it is. */
export function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1)
}

/** Serena waits for the ETL job's next call: a clock beside the state. */
export const WAITING_STATES = new Set(['started', 'received'])
/** Serena is working: a small spinner beside the state. */
export const WORKING_STATES = new Set(['checking', 'updating'])

/** A refresh is open until it is updated or abandoned; the museum's open refresh, if any, is its pending refresh. */
export function isOpen(state: string): boolean {
  return state !== 'updated' && state !== 'abandoned'
}

/**
 * What an admin can do about a pending refresh that needs one, in a line (mockup version 55): on the refresh's own
 * page the button is "below", elsewhere it's "on its page".
 */
export function fixText(refresh: {state: string, actions?: string[], retry_until?: string | null}, onPage = false,
                        now: Date = new Date()): string {
  const where = onPage ? 'below' : 'on its page'
  if (refresh.state === 'update_failed') {
    const retrying = retryText(refresh, now)
    return retrying
      ? `Serena serves some of each ETL list. ${retrying} Retry the ETL list update ${where} to try now, or apply another ETL list.`
      : `Serena serves some of each ETL list. Retry the ETL list update ${where} once the cause is fixed, or apply another ETL list.`
  }
  if (refresh.state !== 'check_failed') {
    return ''
  }
  return (refresh.actions || []).includes('override_threshold')
    ? `It failed only on the delta threshold: override it ${where} if the change is expected, or apply another ETL list.`
    : 'Nothing changed. Fix the ETL list and rerun the ETL job, or apply another ETL list.'
}

/**
 * A failed update that Serena retries by itself (decided October 28, 2026): every 10 minutes until its retry_until,
 * then it has stopped. Empty for a refresh from before, which Serena doesn't retry.
 */
export function retryText(refresh: {retry_until?: string | null}, now: Date = new Date()): string {
  if (!refresh.retry_until) {
    return ''
  }
  return now.getTime() < new Date(refresh.retry_until).getTime()
    ? `Serena tries the update again every 10 minutes, until ${when(refresh.retry_until).slice(11, 16)} UTC.`
    : 'Serena has stopped retrying it.'
}

/** How long since a time, as the "since" line says it: "just now", "3 min", "6 h 59 min". */
export function took(iso: string, now: Date = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000))
  return mins < 1 ? 'just now' : mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`
}

/**
 * Beside a refresh waiting or working, where there's room (mockup version 55): since when, and what's normal, so a
 * normal wait can be told from a stuck one ("Checking since 16:57 UTC (3 min): usually a few minutes."). `late` says
 * whether an ETL refresh is past the watchdog's deadline; empty for any other state.
 */
export function stateSince(refresh: {state: string, updated_at: string, deadline_at?: string | null},
                           now: Date = new Date()): {text: string, late: string} {
  const {state, updated_at: at} = refresh
  if (!WAITING_STATES.has(state) && !WORKING_STATES.has(state)) {
    return {text: '', late: ''}
  }
  const since = `since ${when(at).slice(11, 16)} UTC (${took(at, now)})`
  const text = state === 'started' ? `Waiting ${since}: the ETL job uploads it.`
    : state === 'received' ? `Received ${since}: the ETL job asks Serena to check it next.`
    : `${state === 'checking' ? 'Checking' : 'Applying'} ${since}: usually a few minutes.`
  const deadline = refresh.deadline_at ? new Date(refresh.deadline_at) : null
  const pacific = deadline && new Intl.DateTimeFormat('en-GB', {timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit'}).format(deadline)
  const late = deadline && now.getTime() > deadline.getTime()
    ? `Past the ${pacific} Pacific deadline: the watchdog has alerted${WAITING_STATES.has(state) ? ', and the ETL job may have failed' : ''}.`
    : ''
  return {text, late}
}

/** An audit action's words: the stored name, except "admin_refresh", which the app calls a manual refresh (issue #118). */
export function actionWords(action: string): string {
  return action === 'admin_refresh' ? 'manual refresh' : action.replace(/_/g, ' ')
}

/** Who overrode a refresh's delta threshold: an override made before issue #108 doesn't say. */
export function overrideBy(override: {by?: string}): string {
  return override.by || 'an admin'
}

/**
 * Why an admin expects the change an override lets through (issue #120): one of these, then the reason in their own
 * words, at least OVERRIDE_REASON_MIN characters. Serena has the same words (admin_refreshes.py) for the alert, the
 * refresh's reasons and the audit log.
 */
export const OVERRIDE_KINDS: Record<string, string> = {
  first_load: 'First load',
  bulk_change: 'Known bulk change in CollectionSpace',
  testing: 'Testing',
  other: 'Something else'
}
export const OVERRIDE_REASON_MIN = 20

/** An override's reason with its kind's words first ("Testing: …"); an override made before issue #120 has no kind. */
export function overrideWords(override: {kind?: string, reason?: string}): string {
  const kind = override.kind && OVERRIDE_KINDS[override.kind]
  return kind ? `${kind}: ${override.reason || ''}` : override.reason || ''
}

/** The line Serena adds to a refresh's reasons on an override: its page shows the reason in its banner instead (issue #108). */
export function overrideReason(override: {kind?: string, reason?: string}): string {
  return `delta threshold overridden by an admin: ${overrideWords(override)}`
}

/** The states that need an admin: shown in red, with a failure icon so the cue isn't colour alone (issue #107). */
export const FAILED_STATES = new Set(['check_failed', 'update_failed'])

/**
 * A state's colour, as the mockup's pills (version 43): Updated green, a failed state red, Abandoned grey, and a
 * refresh still running blue. An unknown state is grey.
 */
export function toneOf(state: string): string {
  if (FAILED_STATES.has(state)) {
    return 'error'
  }
  return {updated: 'success', started: 'info', received: 'info', checking: 'info', updating: 'info', waiting: 'info'}[state] || ''
}

/** How the audit retention's choices read (D97). */
export const RETENTION_LABELS: Record<number, string> = {
  90: '90 days', 183: '6 months', 365: '12 months', 548: '18 months', 730: '24 months', 1095: '36 months'
}

/** The page sizes the Refreshes, Alerts and Audit log tables offer; 25 to start (D92). */
export const PAGE_SIZES = [10, 25, 50, 100].map(n => ({value: n, title: String(n)}))

/** The Past requests page's ranges (D106). */
export const REQUEST_RANGES = [
  {value: '1h', title: 'Last hour'},
  {value: '24h', title: 'Last 24 hours'},
  {value: '7d', title: 'Last 7 days'}
]

/** How the app names each kind (D151): "file" only when the kind isn't known. */
export const KIND_WORDS: Record<string, string> = {
  image: 'image', card: 'catalog card', pdf: 'PDF', '3D': '3D model', audio: 'audio file', video: 'video'
}

export function kindWord(kind: string | null | undefined): string {
  return (kind && KIND_WORDS[kind]) || 'file'
}

/** A logged path on one line, shortened in the middle (D152): the museum, both ends of the CSID and the size stay. */
export function middlePath(path: string): string {
  const m = /^(\/[^/]+\/imageserver\/(?:blobs|media)\/)([^/]+)(\/.*)?$/.exec(path)
  if (m && m[2].length > 16) {
    return `${m[1]}${m[2].slice(0, 8)}…${m[2].slice(-6)}${m[3] || ''}`
  }
  return path.length > 72 ? `${path.slice(0, 40)}…${path.slice(-28)}` : path
}

/**
 * A path that isn't a Blob path, as Past requests and the recall form show it (Richard, October 14, 2026, mockup
 * version 34): its first 26 and last 14 characters, so it fits a table's column; the whole path on hover and in ⧉.
 */
export function shortPath(path: string): string {
  return path.length > 44 ? `${path.slice(0, 26)}…${path.slice(-14)}` : path
}

/** A CSID shortened to both ends, for a table or a line (D154: every shortened CSID gets a copy button). */
export function short(csid: string): string {
  return csid.length > 20 ? `${csid.slice(0, 8)}…${csid.slice(-6)}` : csid
}

/** A refresh ID, as the ETL API makes them: <museum>-<refresh date>-<n>. */
export const REFRESH_ID = /^[a-z]+-\d{4}-\d{2}-\d{2}-\d+$/

/** The refresh IDs in a line of text (an alert's message), for linking them (D157). */
export const REFRESH_IN_TEXT = /\b[a-z]+-\d{4}-\d{2}-\d{2}-\d+\b/g

/** Who did it, as the Audit log's "By" and Recalls show it: a refresh's own entries are by Serena (D155). */
export function actorOf(by: string): string {
  return by.startsWith('refresh ') ? 'Serena' : by
}

/** A time split into its date and its clock time, so a narrow column breaks only between them (D160). */
export function whenParts(iso: string | null | undefined): [string, string] {
  const text = when(iso)
  const space = text.indexOf(' ')
  return space < 0 ? [text, ''] : [text.slice(0, space), text.slice(space + 1)]
}

/**
 * A logged path's Blob CSID and size, for Past requests' Blob CSID and Size columns (Richard, October 14, 2026): only a
 * Blob path in a shape Serena serves, with a CSID in Serena's format (1 to 64 letters, digits and hyphens). Any other
 * path (a /media/ URL, a bare /blobs/<CSID>) is null: the page shows it whole, shortened in the middle, with "(not a
 * Blob path)". The size is the name asked for: sizeOf() says whether it's one of the museum's.
 */
/**
 * A Media URL's Media CSID and size (pull request 15, D179): …/media/<Media CSID>/blob/content or
 * …/blob/derivatives/<size>/content. Past requests shows it as "Media <CSID…>" with its size.
 */
export function mediaPathOf(path: string): {media: string, size: string} | null {
  const m = /^\/[^/]+\/imageserver\/media\/([A-Za-z0-9-]{1,64})\/blob\/(?:derivatives\/([^/]+)\/)?content$/.exec(path)
  return m ? {media: m[1], size: m[2] || 'original'} : null
}

export function blobPathOf(path: string): {blob: string, size: string} | null {
  const m = /^\/[^/]+\/imageserver\/blobs\/([A-Za-z0-9-]{1,64})\/(?:derivatives\/([^/]+)\/)?content$/.exec(path)
  return m ? {blob: m[1], size: m[2] || 'original'} : null
}

/**
 * Where a size sorts (Richard, October 14, 2026): the museum's sizes, smallest to largest (its derivatives in their
 * configured order, then the original file), then any other name ("(invalid)"), then a path with no size.
 */
export function sizeRank(size: string, sizes: string[]): number {
  if (!size) {
    return sizes.length + 1
  }
  const i = sizes.indexOf(size)
  return i < 0 ? sizes.length : i
}

/** An unserved request's reason, readable: not_listed → "not listed". */
export function reasonOf(reason: string): string {
  return reason.replace(/_/g, ' ')
}

export function stateOf(state: string): string {
  return STATES[state] || state
}

/**
 * From this many times the museum's delta threshold, a check is far past it (issue #120, decided October 27, 2026):
 * fixed, not a setting, since it only adds a note.
 */
export const FAR_PAST_TIMES = 10

/** How many times its delta threshold a check's delta is, or 0 when it isn't past it or had nothing to compare with. */
export function timesOver(check: {previous_rows: number | null, delta_percent: number | null, threshold_percent: number}): number {
  return check.previous_rows && check.delta_percent !== null && check.delta_percent > check.threshold_percent
    ? check.delta_percent / check.threshold_percent : 0
}

/** "3.8" times; from 100 times, a whole number ("5,751"). */
export function timesText(times: number): string {
  return times >= 100 ? Math.round(times).toLocaleString('en-US') : times.toFixed(1)
}

/** Whether a refresh updated only because an admin overrode its delta threshold (issue #110). */
export function byOverride(refresh: {state: string, override?: unknown}): boolean {
  return !!refresh.override && refresh.state === 'updated'
}

/** A refresh's state as the app shows it: one that updated after an override is "Updated by override" (issue #110). */
export function refreshStateOf(refresh: {state: string, override?: unknown}): string {
  return byOverride(refresh) ? 'Updated by override' : stateOf(refresh.state)
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
  // An override's kind goes before its reason, as everywhere else (issue #120): "Reason: Testing: …".
  const kind = typeof details.kind === 'string' && OVERRIDE_KINDS[details.kind]
  if (kind && typeof details.reason === 'string') {
    const rest = Object.fromEntries(Object.entries(details).filter(([key]) => key !== 'kind'))
    return detailLines({...rest, reason: `${kind}: ${details.reason}`})
  }
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

const PATH = /^\/([a-z]+)\/imageserver\/blobs\/([A-Za-z0-9-]{1,64})\/(?:derivatives\/([A-Za-z]+)\/)?content$/
const CSID = /^[0-9a-f]{8}(-[0-9a-f]{4}){2,3}(-[0-9a-f]{12})?$/i

/** Whether a value is a CSID, as CollectionSpace makes them. */
export function isCsid(value: string): boolean {
  return CSID.test(value)
}

/** A logged path's Blob CSID and size, or null for a path with no CSID to look up (a bad CSID): D145. */
export function blobOfPath(path: string): {blob: string, size: string} | null {
  const found = PATH.exec(path)
  return found && CSID.test(found[2]) ? {blob: found[2], size: found[3] || 'original'} : null
}

const SERENA_CSID = /^[A-Za-z0-9-]{1,64}$/ // a CSID in Serena's format (design: URLs)

/**
 * A path or URL as the recall form reads it (Richard, October 14, 2026), with Media look up's forgiving rules: no host,
 * query string or PDF link suffix (a visitor's email address, which never leaves the browser); a missing leading slash
 * or museum is the signed-in museum's. A Blob path gives its Blob CSID, a /media/ path its Media CSID. Another museum's
 * path, or one without a valid CSID, has no CSID: the form sends the cleaned path and Serena says why.
 */
export function csidOfPath(token: string, museum: string): {csid: string | null, path: string} {
  let path = token.trim()
  if (path.includes('://')) {
    try {
      path = new URL(path).pathname
    } catch {
      path = path.replace(/^[a-z]+:\/\/[^/]*/i, '')
    }
  }
  path = path.split(/[?#]/)[0].replace(/\b(linked_pdf|inline_pdf)(:|%3A)[^/]*/gi, '$1:')
  let parts = path.replace(/^\/+/, '').split('/')
  if (parts[0] === 'imageserver') {
    parts = [museum, ...parts]
  } else if (parts[0] === 'blobs' || parts[0] === 'media') {
    parts = [museum, 'imageserver', ...parts]
  }
  const cleaned = `/${parts.join('/')}`
  const own = parts[0] === museum && parts[1] === 'imageserver' && (parts[2] === 'blobs' || parts[2] === 'media')
  return {csid: own && SERENA_CSID.test(parts[3] || '') ? parts[3] : null, path: cleaned}
}

/**
 * The recall form's text with each path or URL cut down to its CSID (csidOfPath), one per line. `cameFrom` records the
 * path each CSID came from, for the summary's "You gave".
 */
export function csidsOfText(text: string, museum: string, cameFrom: Record<string, string>): string {
  return text.split(/[\s,]+/).filter(Boolean).map(token => {
    if (!token.includes('/')) {
      return token.replace(/\b(linked_pdf|inline_pdf)(:|%3A).*/gi, '$1:') // never an email address
    }
    const found = csidOfPath(token, museum)
    if (found.csid) {
      cameFrom[found.csid] = found.path
      return found.csid
    }
    return found.path
  }).join('\n')
}
