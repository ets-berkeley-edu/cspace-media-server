import {vi} from 'vitest'

export interface Call {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

/** Stubs fetch with answers by "METHOD /path"; returns the calls made. */
export function fakeApi(answers: Record<string, {status?: number, body: unknown}>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method || 'GET'
    const path = url.replace('/admin/v1', '')
    calls.push({
      method,
      path,
      headers: (init.headers || {}) as Record<string, string>,
      body: init.body ? JSON.parse(String(init.body)) : undefined
    })
    const answer = answers[`${method} ${path}`] || {status: 404, body: {detail: 'Not Found'}}
    return new Response(JSON.stringify(answer.body), {status: answer.status || 200})
  }))
  return calls
}
