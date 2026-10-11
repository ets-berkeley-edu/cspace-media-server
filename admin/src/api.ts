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

export interface Preflight {
  result: string
  rows: number
  added: number
  removed: number
  changed: number
  previous_rows: number | null
  threshold_percent: number
  change_percent: number
  error_count: number
  errors: Problem[]
  warnings: string[]
}

export type RunAction = 'retry_apply' | 'record_load' | 'override_threshold'

export interface RunSummary {
  run_id: string
  night: string
  state: string
  created_at: string
  updated_at: string
  rows: number | null
  reasons: string[]
}

export interface Run extends RunSummary {
  newest: boolean
  file_name: string
  upload: {rows: number, bytes: number, sha256: string, uploaded_at: string} | null
  preflight: Preflight | null
  solr_load: {outcome: string, rows: number | null, recorded_by_admin?: boolean} | null
  apply: {deleted: number, written: number, unchanged: number} | null
  actions: RunAction[]
}

export interface Override {
  armed_by: string
  armed_at: number
  expires_at: number
  after_run: string
  reason: string
}

export interface Status {
  newest: Run | null
  override: Override | null
  unacknowledged: number
}

export interface AlertItem {
  key: string
  night: string
  kind: string
  title: string
  subject: string
  message: string
  created_at: string
  acknowledged_by: string | null
  acknowledged_at: string | null
}

const PREFIX = '/admin/v1'

async function call<T>(method: string, path: string, body?: unknown, raw?: {file: Blob, headers: Record<string, string>}): Promise<T> {
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
    body: raw ? raw.file : body === undefined ? undefined : JSON.stringify(body)
  })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : `Serena answered ${response.status}.`
    throw new ApiError(response.status, detail)
  }
  return data as T
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
  runs: (museum: string) => call<{runs: RunSummary[]}>('GET', `/museums/${museum}/runs`),
  run: (museum: string, runId: string) => call<Run>('GET', `/museums/${museum}/runs/${runId}`),
  retryApply: (museum: string, runId: string, reason: string) =>
    call<Run>('POST', `/museums/${museum}/runs/${runId}/retry-apply`, {reason}),
  recordLoad: (museum: string, runId: string, rows: number | null, reason: string) =>
    call<Run>('POST', `/museums/${museum}/runs/${runId}/record-load`, {confirmed: true, rows, reason}),
  overrideThreshold: (museum: string, runId: string, reason: string) =>
    call<{override: Override}>('POST', `/museums/${museum}/runs/${runId}/override-threshold`, {reason}),
  cancelOverride: (museum: string) => call<{override: null}>('DELETE', `/museums/${museum}/threshold-override`),
  upload: (museum: string, file: File, night: string) =>
    call<Run>('PUT', `/museums/${museum}/uploads`, undefined, {
      file,
      headers: {'X-Loaded-Confirmed': 'yes', 'X-File-Name': file.name, 'X-Night': night}
    }),
  alerts: (museum: string) => call<{alerts: AlertItem[]}>('GET', `/museums/${museum}/alerts`),
  acknowledge: (museum: string, key: string) =>
    call<{acknowledged: string}>('POST', `/museums/${museum}/alerts/acknowledge`, {key})
}
