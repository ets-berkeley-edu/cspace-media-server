/** Richard's October 14, 2026 changes not covered with their pages' tests. Synthetic CSIDs only. */
import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {api, unexplained} from '@/api'
import {routes} from '@/router'
import {session} from '@/session'
import Alerts from '@/views/Alerts.vue'

const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'

async function at(path: string, component: unknown) {
  session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}] as never
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

describe('an error without Serena\'s explanation', () => {
  it('says what it means and keeps the code', async () => {
    expect(unexplained(502)).toBe('Serena can\'t be reached right now. Try again in a minute. (502)')
    expect(unexplained(504)).toBe('Serena can\'t be reached right now. Try again in a minute. (504)')
    expect(unexplained(500)).toBe('Serena gave an unexpected answer. (500)')
    fakeApi({'GET /museums/pahma/recalls': {status: 503, body: 'not JSON'}})
    await expect(api.recalls('pahma')).rejects.toThrow('Serena can\'t be reached right now. Try again in a minute. (503)')
  })
})

describe('a recall\'s alert', () => {
  it('opens Media look up for one record, and Recalls for several', async () => {
    const alert = {refresh_date: '2026-10-14', kind: 'recall', title: 'An admin recalled Media records',
      created_at: '2026-10-14T17:00:00+00:00', acknowledged_by: null, acknowledged_at: null}
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: [
      {...alert, key: 'a', subject: MEDIA, message: 'An admin recalled Media record 9-1 (1a2b3c4d…3b4c50) for PAHMA. Reason: x'},
      {...alert, key: 'b', subject: '3 Media records', message: 'An admin recalled 3 Media records for PAHMA. Reason: y'}
    ]}}})
    const wrapper = await at('/pahma/alerts', Alerts)
    const hrefs = wrapper.findAll('tbody a').map(a => a.attributes('href'))
    expect(hrefs).toContain(`/admin/pahma/lookup?q=${MEDIA}`)
    expect(hrefs).toContain('/admin/pahma/recalls')
    wrapper.unmount()
  })
})

