/**
 * The Alerts page's "Acknowledge all" and its All · Waiting filter (D207 to D215, October 20, 2026).
 */
import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import AlertBanner from '@/components/AlertBanner.vue'
import Alerts from '@/views/Alerts.vue'
import {alertsChanged} from '@/session'

type Alert = {key: string, refresh_date: string, kind: string, title: string, subject: string, message: string,
  created_at: string, acknowledged_by: string | null, acknowledged_at: string | null}

/** `n` alerts, one a day back from Oct 12, newest first; those at `waiting` (0 is the newest) not acknowledged. */
function alerts(n: number, waiting: number[]): Alert[] {
  return Array.from({length: n}, (_, i) => {
    const day = new Date(Date.UTC(2026, 9, 12) - i * 86_400_000).toISOString().slice(0, 10)
    const done = !waiting.includes(i)
    return {key: `${day}#check_failed#pahma-${day}-1`, refresh_date: day, kind: 'check_failed',
      title: `Check failed ${day}`, subject: `pahma-${day}-1`, message: 'Too many rows removed.',
      created_at: `${day}T10:00:00+00:00`, acknowledged_by: done ? 'admin' : null,
      acknowledged_at: done ? `${day}T11:00:00+00:00` : null}
  })
}

async function at(path: string, component: unknown = Alerts) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return {wrapper, router}
}

const rows = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('#alerts-table tbody tr')

describe('finding the waiting alerts', () => {
  it('shows All by default, with a red bar on the waiting rows (D212, D214)', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(5, [1, 3])}}})
    const {wrapper} = await at('/pahma/alerts')
    expect(rows(wrapper)).toHaveLength(5)
    expect(wrapper.find('#alerts-show-waiting').text()).toBe('Waiting (2)')
    expect(rows(wrapper).map(r => r.classes('waiting'))).toEqual([false, true, false, true, false])
    wrapper.unmount()
  })

  it('shows only the waiting ones, from the address too, and says so when there are none (D212, D213)', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(5, [1, 3])}}})
    const {wrapper, router} = await at('/pahma/alerts?show=waiting')
    expect(rows(wrapper).map(r => r.text())).toEqual([expect.stringContaining('2026-10-11'), expect.stringContaining('2026-10-09')])
    await wrapper.find('#alerts-show-all').trigger('click')
    await flushPromises()
    expect(rows(wrapper)).toHaveLength(5)
    await vi.waitFor(() => expect(router.currentRoute.value.query.show).toBeUndefined()) // the default: left out
    wrapper.unmount()

    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(3, [])}}})
    const none = await at('/pahma/alerts?show=waiting')
    expect(none.wrapper.find('#alerts-table').text()).toContain('No alerts waiting.')
    none.wrapper.unmount()
  })

  it('opens Waiting from the banner (D213)', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(3, [0])}}})
    const {wrapper} = await at('/pahma', AlertBanner)
    expect(wrapper.find('#open-alerts').attributes('href')).toBe('/admin/pahma/alerts?show=waiting')
    wrapper.unmount()
  })
})

describe('acknowledging all', () => {
  it('offers it only while 2 or more wait (D208)', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(4, [2])}}})
    const one = await at('/pahma/alerts')
    expect(one.wrapper.find('#acknowledge-all').exists()).toBe(false)
    one.wrapper.unmount()
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: alerts(4, [0, 2])}}})
    const two = await at('/pahma/alerts')
    expect(two.wrapper.find('#acknowledge-all').text()).toBe('Acknowledge all (2)')
    two.wrapper.unmount()
  })

  it('asks first, listing them, then sends the keys of the ones it listed (D207, D209)', async () => {
    const list = alerts(30, [0, 4, 27])
    const calls = fakeApi({
      'GET /museums/pahma/alerts': {body: {alerts: list}},
      'POST /museums/pahma/alerts/acknowledge-all': {body: {acknowledged: [], skipped: 0}}
    })
    const {wrapper} = await at('/pahma/alerts')
    const before = alertsChanged.value
    await wrapper.find('#acknowledge-all').trigger('click')
    await flushPromises()
    const dialog = document.querySelector('#acknowledge-all-dialog') as HTMLElement
    expect(dialog.textContent).toContain('Acknowledge 3 alerts?')
    expect([...dialog.querySelectorAll('a.alert-jump')].map(a => a.textContent)).toEqual(
      ['Check failed 2026-10-12', 'Check failed 2026-10-08', 'Check failed 2026-09-15']) // all pages, newest first
    ;(document.querySelector('#confirm-acknowledge-all') as HTMLButtonElement).click()
    await flushPromises()
    const sent = calls.find(c => c.method === 'POST')
    expect(sent?.body).toEqual({keys: [list[0].key, list[4].key, list[27].key]})
    expect(sent?.headers['X-Serena-Admin']).toBe('1') // a change (CSRF)
    expect(alertsChanged.value).toBe(before + 1) // the table, the banner and the bell reload
    wrapper.unmount()
  })

  it('shows an alert from the dialog on the page that holds it, marked, acknowledging nothing (D215)', async () => {
    const list = alerts(30, [0, 27])
    const calls = fakeApi({'GET /museums/pahma/alerts': {body: {alerts: list}}})
    const {wrapper, router} = await at('/pahma/alerts')
    await wrapper.find('#acknowledge-all').trigger('click')
    await flushPromises()
    ;(document.querySelectorAll('#acknowledge-all-dialog a.alert-jump')[1] as HTMLAnchorElement).click()
    await flushPromises()
    await vi.waitFor(() => expect(router.currentRoute.value.query.page).toBe('2')) // the 28th of 30: page 2 at 25 a page
    const marked = wrapper.find('#alerts-table tr.marked')
    expect(marked.text()).toContain('2026-09-15')
    expect(marked.classes('waiting')).toBe(true)
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
    wrapper.unmount()
  })
})
