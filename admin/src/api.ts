/**
 * Serena's admin API (/admin/v1), through fetch. Every request that changes something carries X-Serena-Admin: 1,
 * which the API requires (design: decided October 10, 2026); cookies are same-origin only.
 */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface Museum {
  key: string
  name: string
}

export interface SignedIn {
  museum: string
  name: string
  user: string
}

export interface Me {
  environment: string
  build: string // which code this is, for example "feature/x @ 1a2b3c4"; empty: not shown
  sessions: SignedIn[]
}

export interface AuditEntry {
  tenant: string
  at: string
  admin: string // as stored: an admin, "ETL (<museum>)" or "refresh <refresh ID>"
  by: string // as shown: a refresh's own entries are by Serena (the refresh is the target or in the details)
  action: string
  target: string
  details: Record<string, unknown>
}

export interface Problem {
  line: number
  field: string
  problem: string
}

export interface Check {
  result: string
  rows: number
  added: number
  removed: number
  changed: number
  previous_rows: number | null
  threshold_percent: number
  delta_percent: number
  error_count: number
  errors: Problem[]
  warnings: string[]
}

export type RefreshAction = 'retry_update' | 'override_threshold'

export interface RefreshSummary {
  refresh_id: string
  refresh_date: string
  state: string
  created_at: string
  updated_at: string
  rows: number | null
  reasons: string[]
  admin_refresh_date: string | null // an admin refresh: the refresh date its servable list is for
}

export interface Refresh extends RefreshSummary {
  newest: boolean
  file_name: string
  upload: {rows: number, bytes: number, sha256: string, uploaded_at: string} | null
  check: Check | null
  update: {deleted: number, written: number, unchanged: number, recalls_ended?: number, recalls_kept?: number} | null
  override: {at: string} | null // an admin overrode the delta threshold for this servable list (D83)
  actions: RefreshAction[]
}

export interface Status {
  newest: Refresh | null
  unacknowledged: number
}

export interface SettingItem {
  name: string // a setting, or size_limit_mb.<kind>
  group: string // watchdog, etl, check, size_limits or audit
  label: string
  value: string | number
  default: string | number // the value in Serena's configuration
  changed: boolean
}

export interface SettingsResponse {
  settings: SettingItem[]
  // For each audit retention a museum may choose: how many of today's entries a change to it would remove (D98).
  audit_retention_choices: {days: number, entries_removed: number}[]
}

export interface AlertItem {
  key: string
  refresh_date: string
  kind: string
  title: string
  subject: string
  message: string
  created_at: string
  acknowledged_by: string | null
  acknowledged_at: string | null
}

const PREFIX = '/admin/v1'

/**
 * Called when Serena answers 401 for a museum the app thought it was signed in to: the session timed out (30 minutes
 * without activity, or 8 hours) or an admin signed everyone out. The router sends the admin to sign in again, saying
 * why, and back to the page afterwards (D161).
 */
let sessionEnded: ((museum: string) => void) | null = null

export function onSessionEnded(handler: ((museum: string) => void) | null): void {
  sessionEnded = handler
}

/** Something other than call() learned the museum's session ended (a file dialog's picture, say). */
export function sessionEndedFor(museum: string): void {
  sessionEnded?.(museum)
}

/** The museum of an admin API path that needs its session: /museums/<museum>/… or DELETE /sessions/<museum>. */
export function museumOfPath(path: string): string | null {
  const found = /^\/(?:museums|sessions)\/([a-z]+)(?:[/?]|$)/.exec(path)
  return found ? found[1] : null
}

async function call<T>(method: string, path: string, body?: unknown, raw?: {file?: Blob, headers: Record<string, string>}): Promise<T> {
  const headers: Record<string, string> = {Accept: 'application/json', ...(raw ? raw.headers : {})}
  if (method !== 'GET') {
    headers['X-Serena-Admin'] = '1'
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(PREFIX + path, {
    method,
    headers,
    credentials: 'same-origin',
    body: raw?.file ? raw.file : body === undefined ? undefined : JSON.stringify(body)
  })
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null // not Serena's JSON: a proxy's error page, say
  }
  if (response.status === 401 && sessionEnded) {
    const museum = museumOfPath(path)
    if (museum) {
      sessionEnded(museum)
    }
  }
  if (!response.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : unexplained(response.status)
    throw new ApiError(response.status, detail)
  }
  return data as T
}

/**
 * An error without Serena's own explanation (Richard, October 14, 2026): what it means, with the code kept for anyone
 * reporting it. 502, 503 and 504 come from what stands in front of Serena when it's down or slow.
 */
export function unexplained(status: number): string {
  return [502, 503, 504].includes(status)
    ? `Serena can't be reached right now. Try again in a minute. (${status})`
    : `Serena gave an unexpected answer. (${status})`
}

/** One request in the log: served, or unserved with its reason (D103). */
export interface RequestLine {
  at: string
  outcome: 'served' | 'unserved'
  reason: string
  path: string
  kind: string
  cache: string
  signed: boolean
}

export type RequestRange = '1h' | '24h' | '7d'

export interface RequestsReport {
  range: RequestRange
  start: string
  end: string
  max_lines: number
  truncated: boolean // more lines than max_lines: only the newest are listed (D107)
  signed_links: boolean // the museum has signed access (Cinefiles): only its page shows the Signed link column
  days: {day: string, served: number, unserved: Record<string, number>, unserved_total: number}[]
  top_paths: {path: string, requests: number}[]
  sizes: string[] // the museum's sizes, smallest to largest: its derivatives, then "original" (October 14, 2026)
  served_by_size: {size: string, requests: number}[] // every served request in the range, in that order
  lines: RequestLine[]
}

/** A Media record a recall would recall, and how Serena found it (D116). */
export interface RecallRecord {
  media_csid: string
  blob_csids: string[]
  kind: string | null
  served_today: boolean
  recalled: boolean
  source: 'serena' | 'collectionspace'
  entered: string[]
}

export interface RecallSummary {
  records: RecallRecord[]
  not_found: {csid: string, why: string, message: string}[]
  recalled?: string[]
}

export interface Recall {
  media_csid: string
  blob_csids: string[]
  by: string
  at: string
  reason: string
  kept_by: string | null // the refresh that kept it: the same Blob is still public in CollectionSpace (D119)
  kept_on: string | null
  identification_number: string | null // read from CollectionSpace when it was recalled; null: none, or not read
}

export interface EndedRecall {
  media_csid: string
  at: string
  by: string // an admin, or "refresh <refresh ID>"
  action: 'recall_ended' | 'recall_release' | 'recall_cancel'
  details: Record<string, unknown>
}

export interface RecallsPage {
  days: number
  active: Recall[]
  ended: EndedRecall[]
  max_in_box: number
  max_in_file: number
}

export interface LookupStep {
  check: string
  outcome: string
  ok: boolean | null
}

export interface LookupItem {
  blob_csid: string
  media_csid: string | null
  kind: string | null
  access: string | null
  steps: LookupStep[]
  sizes: LookupSize[]
  cspace: LookupCSpace
}

export interface LookupSize {
  size: string
  served: boolean
  reason: string | null
  verdict: string
  stored: {fetched_at: string, last_served: string | null, size: number, content_type: string} | null
}

/** What CollectionSpace says now about the item's Media record (D139 to D141). */
export interface LookupCSpace {
  state: 'exists' | 'deleted' | 'gone' | 'unavailable' | 'no_media'
  media_csid?: string
  blob_csid?: string | null
  identification_number?: string | null // the Media record's identification number: the page's heading (D153)
  updated_at?: string | null
  changed_since_refresh?: boolean
  fields?: {label: string, value: string}[]
  next?: string
}

export interface Lookup {
  input: string
  refused: string | null
  refresh: {refresh_id: string, refresh_date: string, started_at: string} | null
  items: LookupItem[]
}

/** A failed load's message, for the page to show. */
export function problem(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Serena couldn\'t be reached. Reload the page to try again.'
}

export const api = {
  museums: () => call<Museum[]>('GET', '/museums'),
  me: () => call<Me>('GET', '/me'),
  signIn: (museum: string, username: string, password: string) =>
    call<SignedIn>('POST', '/sessions', {museum, username, password}),
  signOut: (museum: string) => call<{museum: string}>('DELETE', `/sessions/${museum}`),
  signOutAll: (museum: string) => call<{sessions_ended: number}>('POST', `/museums/${museum}/sign-out-all`),
  audit: (museum: string) => call<{days: number, entries: AuditEntry[]}>('GET', `/museums/${museum}/audit`),
  // Every entry the museum keeps, as CSV: a plain link, so the browser saves the file (D96).
  auditExportUrl: (museum: string) => `${PREFIX}/museums/${museum}/audit/export.csv`,
  recalls: (museum: string) => call<RecallsPage>('GET', `/museums/${museum}/recalls`),
  recallSummary: (museum: string, text: string) =>
    call<RecallSummary>('POST', `/museums/${museum}/recalls/summary`, {text}),
  recall: (museum: string, text: string, reason: string) =>
    call<RecallSummary>('POST', `/museums/${museum}/recalls`, {text, reason}),
  release: (museum: string, mediaCsid: string, reason: string) =>
    call<{released: string}>('POST', `/museums/${museum}/recalls/${encodeURIComponent(mediaCsid)}/release`, {reason}),
  /** Undoes a recall no refresh has decided yet (D148). */
  cancelRecall: (museum: string, mediaCsid: string, reason: string) =>
    call<{cancelled: string}>('POST', `/museums/${museum}/recalls/${encodeURIComponent(mediaCsid)}/cancel`, {reason}),
  // A Media record's thumbnail or full-size view, through the admin API only, never cached (D129).
  previewUrl: (museum: string, mediaCsid: string, size: 'thumbnail' | 'full' = 'thumbnail', source: 'any' | 'cspace' = 'any') =>
    `${PREFIX}/museums/${museum}/media/${encodeURIComponent(mediaCsid)}/preview?size=${size}` +
    (source === 'cspace' ? '&source=cspace' : ''),
  /** A Blob's file at one size (a derivative, "original", or "full": the largest the museum serves), D144. */
  blobPreviewUrl: (museum: string, blobCsid: string, size = 'full') =>
    `${PREFIX}/museums/${museum}/blobs/${encodeURIComponent(blobCsid)}/preview?size=${encodeURIComponent(size)}`,
  lookup: (museum: string, q: string) =>
    call<Lookup>('GET', `/museums/${museum}/lookup?${new URLSearchParams({q})}`),
  requests: (museum: string, range: RequestRange) =>
    call<RequestsReport>('GET', `/museums/${museum}/requests?range=${range}`),
  // The lines matching the page's range and filters, as CSV: a plain link, so the browser saves the file (D113).
  requestsExportUrl: (museum: string, range: RequestRange, outcome: string, reason: string) => {
    const query = new URLSearchParams({range})
    if (outcome) {
      query.set('outcome', outcome)
    }
    if (reason) {
      query.set('reason', reason)
    }
    return `${PREFIX}/museums/${museum}/requests/export.csv?${query}`
  },
  settings: (museum: string) => call<SettingsResponse>('GET', `/museums/${museum}/settings`),
  changeSetting: (museum: string, name: string, value: string | number, reason: string) =>
    call<SettingsResponse>('PUT', `/museums/${museum}/settings/${encodeURIComponent(name)}`, {value, reason}),
  resetSetting: (museum: string, name: string, reason: string) =>
    call<SettingsResponse>('POST', `/museums/${museum}/settings/${encodeURIComponent(name)}/reset`, {reason}),
  etlApiUrl: (museum: string) => `${PREFIX}/museums/${museum}/etl-api.json`,
  status: (museum: string) => call<Status>('GET', `/museums/${museum}/status`),
  refreshes: (museum: string) => call<{refreshes: RefreshSummary[]}>('GET', `/museums/${museum}/refreshes`),
  refresh: (museum: string, refreshId: string) => call<Refresh>('GET', `/museums/${museum}/refreshes/${refreshId}`),
  retryUpdate: (museum: string, refreshId: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/retry-update`, {reason}),
  overrideThreshold: (museum: string, refreshId: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/override-threshold`, {reason}),
  // An admin refresh, with the servable list as the body. The file name and reason are URL-encoded: a header carries
  // only ASCII.
  startRefresh: (museum: string, file: File, refreshDate: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes`, undefined, {
      file,
      headers: {
        'X-Live-Core-Confirmed': 'yes',
        'X-File-Name': encodeURIComponent(file.name),
        'X-Refresh-Date': refreshDate,
        'X-Reason': encodeURIComponent(reason)
      }
    }),
  // background: the banner's own checks, which don't count as activity (the session still signs out when idle)
  alerts: (museum: string, background = false) => call<{alerts: AlertItem[]}>('GET', `/museums/${museum}/alerts`,
    undefined, background ? {headers: {'X-Serena-Background': '1'}} : undefined),
  acknowledge: (museum: string, key: string) =>
    call<{acknowledged: string}>('POST', `/museums/${museum}/alerts/acknowledge`, {key})
}
