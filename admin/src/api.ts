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
  admin: string
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
  update: {deleted: number, written: number, unchanged: number} | null
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
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : `Serena answered ${response.status}.`
    throw new ApiError(response.status, detail)
  }
  return data as T
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
  days: {day: string, served: number, unserved: Record<string, number>, unserved_total: number}[]
  top_paths: {path: string, requests: number}[]
  lines: RequestLine[]
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
