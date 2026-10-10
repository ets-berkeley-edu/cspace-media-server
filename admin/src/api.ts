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

const PREFIX = '/admin/v1'

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {Accept: 'application/json'}
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
    body: body === undefined ? undefined : JSON.stringify(body)
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
  etlApiUrl: (museum: string) => `${PREFIX}/museums/${museum}/etl-api.json`
}
