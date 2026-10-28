import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import App from '@/App.vue'
import {routes} from '@/router'
import {session} from '@/session'

const ALERT = {key: 'a', refresh_date: '2026-10-12', kind: 'recall', title: 'An admin recalled Media records',
  subject: 'x', message: 'm', created_at: '2026-10-13T06:02:16+00:00', acknowledged_by: null, acknowledged_at: null}

async function app(alerts: unknown[]) {
  fakeApi({
    'GET /museums/pahma/alerts': {body: {alerts}},
    'GET /museums/pahma/refreshes': {body: {refreshes: [], days: 30}}
  })
  session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}] as never
  session.loaded = true
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push('/pahma/refreshes')
  const wrapper = mount(App, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

describe('the frame', () => {
  it('groups the menu, with Alerts and Settings in the app bar (D137, D138)', async () => {
    const wrapper = await app([])
    expect(wrapper.findAll('.nav-group').map(g => g.text())).toEqual(['Daily refresh', 'Media records', 'Admin'])
    expect(wrapper.findAll('[id^="nav-"]').map(i => i.text())).toEqual([
      'Overview', 'Past refreshes', 'Past requests', 'Media look up', 'Recalls', 'Manual refresh', 'Audit log',
      'API documentation'])
    expect(wrapper.find('#settings-gear').attributes('href')).toContain('/pahma/settings')
    expect(wrapper.find('#settings-gear').attributes('aria-label')).toBe('PAHMA settings')
    expect(wrapper.find('#alerts-bell').attributes('href')).toContain('/pahma/alerts')
    expect(wrapper.find('#alerts-badge').exists()).toBe(false)
    expect(wrapper.find('#alert-banner').exists()).toBe(false)
    wrapper.unmount()
  })

  it('counts unacknowledged alerts on the bell, as the banner does', async () => {
    const wrapper = await app([ALERT, {...ALERT, key: 'b'}, {...ALERT, key: 'c', acknowledged_at: 'x', acknowledged_by: 'admin'}])
    expect(wrapper.find('#alerts-badge').text()).toBe('2')
    expect(wrapper.find('#alerts-bell').attributes('aria-label')).toBe('Alerts: 2 unacknowledged')
    expect(wrapper.find('#alert-banner').text()).toContain('2 alerts: An admin recalled Media records')
    wrapper.unmount()
  })
})
