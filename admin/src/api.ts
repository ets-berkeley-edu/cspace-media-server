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
  uploaded_refresh_date: string | null // an admin upload: the refresh date the servable list is for
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
  audit: (museum: string) => call<{entries: AuditEntry[]}>('GET', `/museums/${museum}/audit`),
  etlApiUrl: (museum: string) => `${PREFIX}/museums/${museum}/etl-api.json`,
  status: (museum: string) => call<Status>('GET', `/museums/${museum}/status`),
  refreshes: (museum: string) => call<{refreshes: RefreshSummary[]}>('GET', `/museums/${museum}/refreshes`),
  refresh: (museum: string, refreshId: string) => call<Refresh>('GET', `/museums/${museum}/refreshes/${refreshId}`),
  retryUpdate: (museum: string, refreshId: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/retry-update`, {reason}),
  overrideThreshold: (museum: string, refreshId: string, reason: string) =>
    call<Refresh>('POST', `/museums/${museum}/refreshes/${refreshId}/override-threshold`, {reason}),
  // The file name and reason are URL-encoded: a header carries only ASCII.
  upload: (museum: string, file: File, refreshDate: string, reason: string) =>
    call<Refresh>('PUT', `/museums/${museum}/uploads`, undefined, {
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
