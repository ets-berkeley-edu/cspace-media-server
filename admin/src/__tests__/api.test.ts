import {describe, expect, it} from 'vitest'
import {fakeApi} from './fake'
import {ApiError, api} from '@/api'

describe('the admin API client', () => {
  it('sends the app header with changes, not with reads', async () => {
    const calls = fakeApi({
      'GET /me': {body: {environment: 'Test', sessions: []}},
      'POST /sessions': {body: {museum: 'pahma', name: 'PAHMA', user: 'admin'}}
    })
    await api.me()
    await api.signIn('pahma', 'admin', 'secret-for-the-test')
    expect(calls[0].headers['X-Serena-Admin']).toBeUndefined()
    expect(calls[1].headers['X-Serena-Admin']).toBe('1')
    expect(calls[1].body).toEqual({museum: 'pahma', username: 'admin', password: 'secret-for-the-test'})
  })

  it('turns Serena\'s explanation into the error\'s message', async () => {
    fakeApi({'POST /sessions': {status: 403, body: {detail: 'Your PAHMA account doesn\'t have the Serena_Admin role.'}}})
    const error = await api.signIn('pahma', 'viewer', 'x').catch(e => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(403)
    expect(error.message).toContain('Serena_Admin')
  })
})
