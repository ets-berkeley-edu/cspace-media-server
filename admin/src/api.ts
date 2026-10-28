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

/** Manual refresh's dry run (mockup version 55): the check's result, when, and against which update; nothing kept. */
export interface DryRun {
  check: Check
  checked_at: string
  against: {refresh_id: string, updated_at: string} | null // null: there's no ETL list update yet
}

export interface Check {
  result: string
  rows: number
  added: number
  removed: number
  changed: number
  previous_rows: number | null
  threshold_percent: number
  delta_percent: number | null // null with nothing to compare with (a first ETL list update)
  error_count: number
  errors: Problem[]
  warnings: string[]
}

export type ReasonKind = 'problem' | 'admin' | 'override'

export type RefreshAction = 'retry_update' | 'override_threshold'

/** An admin's override of the delta threshold for a refresh's ETL list (D83): one made before issue #108 has only `at`. */
export interface Override {
  at: string
  by?: string // the admin's CollectionSpace username
  kind?: string // why the change is expected (issue #120): one of OVERRIDE_KINDS; an override made before has none
  reason?: string
}

export interface RefreshSummary {
  refresh_id: string
  refresh_date: string
  state: string
  created_at: string
  updated_at: string
  rows: number | null
  reasons: string[]
  // Which list each reason goes in, one per reason (issue #120): what went wrong, or what admins did
  reason_kinds?: ReasonKind[]
  manual: boolean // a manual refresh (issue #118; "admin refresh" in the earlier decisions)
  admin_refresh_date: string | null // a manual refresh: the refresh date its ETL list is for
  admin_refresh_from: string | null // a manual refresh with one of the ETL's lists: the refresh it came with (issue #118)
  override: Override | null
}

/** One of the ETL's recent ETL lists, by the refresh it came with, and that refresh's outcome (issue #118). */
export interface ServableList {
  refresh_id: string
  refresh_date: string
  state: string
  override: Override | null
  rows: number
  sha256: string
  uploaded_at: string
}

export interface Refresh extends RefreshSummary {
  newest: boolean
  file_name: string
  upload: {rows: number, bytes: number, sha256: string, uploaded_at: string} | null
  check: Check | null
  update: {deleted: number, written: number, unchanged: number, recalls_ended?: number, recalls_kept?: number} | null
  actions: RefreshAction[]
  // When the watchdog's deadline for an ETL refresh's day passes, in UTC (mockup version 55); none for a manual one
  deadline_at?: string | null
  // A failed update: until when Serena tries it again by itself (decided October 28, 2026); none for an older one
  retry_until?: string | null
}

export interface Status {
  newest: Refresh | null
  current: Refresh | null // the newest updated refresh: the ETL list Serena serves from (mockup version 55)
  pending: Refresh | null // the newest refresh while it's open
  unacknowledged: number
}

export interface SettingItem {
  name: string // a setting, or size_limit_mb.<kind>
  group: string // watchdog, etl, check, size_limits, audit or placeholder
  label: string
  value: string | number | null // null: none (the placeholder image's Media CSID before one is named)
  default: string | number | null // the value in Serena's configuration
  changed: boolean
  // What the value must be (D219): a whole number or a number from min to max, a time (HH:MM), one of the audit
  // retention choices, or a Media CSID. The page checks it on Save and shows it as the field's hint.
  kind?: 'whole' | 'number' | 'time' | 'choice' | 'csid'
  min?: number | null
  max?: number | null
}

export interface SettingsResponse {
  settings: SettingItem[]
  // For each audit retention a museum may choose: how many of today's entries a change to it would remove (D98).
  audit_retention_choices: {days: number, entries_removed: number}[]
  // The Blob the museum's ETL lists for its placeholder image (null: it lists none yet), and the named Media record's
  // identification number (D169).
  placeholder: {blob_csid: string | null, identification_number: string | null}
  warning?: string // a saved placeholder record whose Blob isn't the one the ETL lists (D171)
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
  served_by_cache: {hit: number, miss: number} // from Serena's cache, or fetched from CollectionSpace (issue #96)
  lines: RequestLine[]
  read_at: string // when Serena read the log for it: it keeps a report a minute (D108)
  try_again_in: number | null // a refused Refresh (issue #100): the seconds until the next; the kept report came back
}

export type CountsPeriod = 'day' | 'week' | 'month' | 'year'

/** One period's counts from the cache or CollectionSpace (issue #96): hits, misses and unserved requests. */
export interface PeriodCount {
  period: string // "2026-10-25", "2026-W43", "2026-10" or "2026" (UTC; ISO weeks start on Monday)
  first_day: string
  last_day: string
  hits: number
  misses: number
  unserved: number
  live: boolean // holds today (so far), read from the log now
  partial: boolean // the first period counted, which counting began partway through
}

export interface RequestCounts {
  by: CountsPeriod
  today: string
  since: string | null // the first day counted
  totals: {hits: number, misses: number, unserved: number} // every day counted, and today so far
  rows: PeriodCount[] // newest first
  live_unavailable: string | null // why today's counts couldn't be read from the log
  read_at: string // when today's counts were read from the log (issue #100)
  try_again_in: number | null
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
  // A Media record's thumbnail or full-size view, or one size the museum serves ("original" or a derivative, for a
  // Media URL on Past requests, D179), through the admin API only, never cached (D129).
  previewUrl: (museum: string, mediaCsid: string, size = 'thumbnail', source: 'any' | 'cspace' = 'any') =>
    `${PREFIX}/museums/${museum}/media/${encodeURIComponent(mediaCsid)}/preview?size=${encodeURIComponent(size)}` +
    (source === 'cspace' ? '&source=cspace' : ''),
  /** A Blob's file at one size (a derivative, "original", or "full": the largest the museum serves), D144. */
  blobPreviewUrl: (museum: string, blobCsid: string, size = 'full') =>
    `${PREFIX}/museums/${museum}/blobs/${encodeURIComponent(blobCsid)}/preview?size=${encodeURIComponent(size)}`,
  lookup: (museum: string, q: string) =>
    call<Lookup>('GET', `/museums/${museum}/lookup?${new URLSearchParams({q})}`),
  // fresh: Past requests' Refresh (issue #100), reading the log again now rather than taking the minute's kept answer
  requests: (museum: string, range: RequestRange, fresh = false) =>
    call<RequestsReport>('GET', `/museums/${museum}/requests?range=${range}${fresh ? '&fresh=1' : ''}`),
  requestCounts: (museum: string, by: CountsPeriod, fresh = false) =>
    call<RequestCounts>('GET', `/museums/${museum}/requests/counts?by=${by}${fresh ? '&fresh=1' : ''}`),
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
  // background: Overview, Past refreshes and a refresh's page checking again while Serena works (checkAgain.ts),
  // which doesn't count as activity
  status: (museum: string, background = false) => call<Status>('GET', `/museums/${museum}/status`, undefined,
    background ? {headers: {'X-Serena-Background': '1'}} : undefined),
  refreshes: (museum: string, background = false) => call<{refreshes: RefreshSummary[]}>('GET',
    `/museums/${museum}/refreshes`, undefined, background ? {headers: {'X-Serena-Background': '1'}} : undefined),
  refresh: (museum: string, refreshId: string, background = false) => call<Refresh>('GET',
    `/museums/${museum}/refreshes/${refreshId}`, undefined, background ? {headers: {'X-Serena-Background': '1'}} : undefined),
  retryUpdate: (museum: string, refreshId: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/retry-update`, {reason}),
  overrideThreshold: (museum: string, refreshId: string, kind: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/override-threshold`, {kind, reason}),
  // Manual refresh (mockup version 55): a dry run of an ETL list, which changes nothing, then Apply, which starts a
  // manual refresh that checks and updates by itself. An upload is sent with each. The file name and reason are
  // URL-encoded: a header carries only ASCII. openRefresh: the pending refresh the admin was shown and confirmed
  // stopping (rule D); kind: Apply with override.
  dryRunUpload: (museum: string, file: File) =>
    call<DryRun>('POST', `/museums/${museum}/servable-lists/dry-run`, undefined, {file, headers: {}}),
  dryRunList: (museum: string, refreshId: string) =>
    call<DryRun>('POST', `/museums/${museum}/servable-lists/${refreshId}/dry-run`),
  startRefresh: (museum: string, file: File, refreshDate: string, reason: string, openRefresh = '', kind = '') =>
    call<Refresh>('POST', `/museums/${museum}/refreshes`, undefined, {
      file,
      headers: {
        'X-Live-Core-Confirmed': 'yes',
        'X-File-Name': encodeURIComponent(file.name),
        'X-Refresh-Date': refreshDate,
        'X-Reason': encodeURIComponent(reason),
        'X-Open-Refresh': openRefresh,
        'X-Override-Kind': kind
      }
    }),
  startFromList: (museum: string, refreshId: string, reason: string, openRefresh = '', kind = '') =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/from-list`,
      {refresh_id: refreshId, reason, open_refresh: openRefresh, kind}),
  servableLists: (museum: string) => call<{lists: ServableList[]}>('GET', `/museums/${museum}/servable-lists`),
  // background: the banner's own checks, which don't count as activity (the session still signs out when idle)
  alerts: (museum: string, background = false) => call<{alerts: AlertItem[]}>('GET', `/museums/${museum}/alerts`,
    undefined, background ? {headers: {'X-Serena-Background': '1'}} : undefined),
  acknowledge: (museum: string, key: string) =>
    call<{acknowledged: string}>('POST', `/museums/${museum}/alerts/acknowledge`, {key}),
  /** The alerts the page shows as waiting (D207); one acknowledged meanwhile is skipped. */
  acknowledgeAll: (museum: string, keys: string[]) =>
    call<{acknowledged: string[], skipped: number}>('POST', `/museums/${museum}/alerts/acknowledge-all`, {keys})
}
