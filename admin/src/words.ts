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

/** Who overrode a refresh's delta threshold: an override made before issue #108 doesn't say. */
export function overrideBy(override: {by?: string}): string {
  return override.by || 'an admin'
}

/** The line Serena adds to a refresh's reasons on an override: its page shows the reason in its banner instead (issue #108). */
export function overrideReason(reason: string): string {
  return `delta threshold overridden by an admin: ${reason}`
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
  return {updated: 'success', started: 'info', received: 'info', checking: 'info', updating: 'info'}[state] || ''
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
