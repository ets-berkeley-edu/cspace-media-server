/**
 * The UI review of October 13, 2026 (D154 to D165): copy buttons, links, the "By" column, a session that ended, the
 * file dialog's reasons and Sign everyone out. Synthetic CSIDs only.
 */
import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {api, museumOfPath} from '@/api'
import router, {routes, safeNext, sessionEnded} from '@/router'
import {session} from '@/session'
import Alerts from '@/views/Alerts.vue'
import AuditLog from '@/views/AuditLog.vue'
import Overview from '@/views/Overview.vue'
import Requests from '@/views/Requests.vue'
import SignIn from '@/views/SignIn.vue'
import {actorOf, short, whenParts} from '@/words'

const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'
const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50'
const SHA = 'ab'.repeat(32)
const PAHMA = {museum: 'pahma', name: 'PAHMA', user: 'admin'}

async function at(path: string, component: unknown) {
  const memory = createRouter({history: createMemoryHistory('/admin/'), routes})
  await memory.push(path)
  const wrapper = mount(component as never, {global: {plugins: [memory]}, attachTo: document.body})
  await flushPromises()
  return {wrapper, memory}
}

describe('words', () => {
  it('shortens a CSID to both ends, splits a time, and names a refresh\'s actor Serena', () => {
    expect(short(MEDIA)).toBe('1a2b3c4d…3b4c50')
    expect(short('59a733dd-d641')).toBe('59a733dd-d641')
    expect(whenParts('2026-10-13T10:01:00.123Z')).toEqual(['2026-10-13', '10:01:00 UTC'])
    expect(actorOf('refresh pahma-2026-10-12-1')).toBe('Serena')
    expect(actorOf('admin')).toBe('admin')
  })
})

describe('a session that ended (D161)', () => {
  it('knows which museum an admin API path needs', () => {
    expect(museumOfPath('/museums/pahma/audit')).toBe('pahma')
    expect(museumOfPath('/sessions/pahma')).toBe('pahma')
    expect(museumOfPath('/sessions')).toBeNull() // signing in
    expect(museumOfPath('/me')).toBeNull()
  })

  it('goes to sign-in, saying why, and back to the same page afterwards', async () => {
    fakeApi({
      'GET /me': {body: {environment: 'Test', sessions: [PAHMA]}},
      'GET /museums/pahma/audit': {status: 401, body: {detail: 'Sign in to this museum.'}}
    })
    await router.push('/pahma/audit?x=1')
    await api.audit('pahma').catch(() => undefined) // what the page asks first
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('sign-in'))
    expect(router.currentRoute.value.query).toEqual({museum: 'pahma', timedOut: '1', next: '/pahma/audit?x=1'})
    expect(session.signedIn).toEqual([])
    sessionEnded('pahma') // a second 401 (the banner's) changes nothing
    expect(router.currentRoute.value.name).toBe('sign-in')
  })

  it('returns only to a page of the museum signed in to', () => {
    expect(safeNext('/pahma/audit', 'pahma')).toBe('/pahma/audit')
    expect(safeNext('/pahma/lookup?q=x', 'pahma')).toBe('/pahma/lookup?q=x')
    expect(safeNext('/cinefiles/audit', 'pahma')).toBeNull()
    expect(safeNext('//example.org/pahma', 'pahma')).toBeNull()
    expect(safeNext('/pahmaother', 'pahma')).toBeNull()
    expect(safeNext('/sign-in', 'pahma')).toBeNull()
    expect(safeNext(undefined, 'pahma')).toBeNull()
  })

  it('says the session ended on the sign-in page, then returns to the page', async () => {
    fakeApi({
      'GET /museums': {body: [{key: 'pahma', name: 'PAHMA'}]},
      'POST /sessions': {body: PAHMA},
      'GET /me': {body: {environment: 'Test', sessions: [PAHMA]}}
    })
    const {wrapper, memory} = await at('/sign-in?museum=pahma&timedOut=1&next=%2Fpahma%2Faudit', SignIn)
    expect(wrapper.find('#sign-in-timed-out').text()).toContain('Your PAHMA session ended')
    expect(wrapper.find('#sign-in-timed-out').text()).toContain('return to the page you were on')
    await wrapper.find('#username').setValue('admin')
    await wrapper.find('#password').setValue('pw-for-the-test')
    await wrapper.find('form').trigger('submit')
    await vi.waitFor(() => expect(memory.currentRoute.value.fullPath).toBe('/pahma/audit'))
    wrapper.unmount()
  })
})

describe('Sign everyone out', () => {
  it('says why when it fails, and links the Overview sentence\'s pages', async () => {
    session.signedIn = [PAHMA]
    fakeApi({
      'GET /museums/pahma/status': {body: {newest: null, unacknowledged: 0}},
      'POST /museums/pahma/sign-out-all': {status: 503, body: {detail: 'Serena\'s sessions table can\'t be reached.'}}
    })
    const {wrapper} = await at('/pahma', Overview)
    const links = wrapper.findAll('#overview-pages a').map(a => a.attributes('href'))
    expect(links).toEqual(['/admin/pahma/requests', '/admin/pahma/lookup'])
    await wrapper.find('#sign-out-all').trigger('click')
    await flushPromises()
    ;(document.querySelector('#confirm-sign-out-all') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('#sign-out-all-error')?.textContent).toContain('can\'t be reached'))
    wrapper.unmount()
  })
})

describe('links and copy buttons', () => {
  it('links an alert\'s refresh IDs, and shortens a Media CSID it\'s about (D154, D157)', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: [
      {key: 'k1', refresh_date: '2026-10-12', kind: 'recall_kept', title: 'Recalled in Serena, but still public',
        subject: MEDIA, message: 'Refresh pahma-2026-10-12-1 still lists it.', created_at: '2026-10-12T10:41:00Z',
        acknowledged_by: null, acknowledged_at: null},
      {key: 'k2', refresh_date: '2026-10-11', kind: 'check_failed', title: 'A servable list check failed',
        subject: 'pahma-2026-10-11-1', message: 'Too many rows removed.', created_at: '2026-10-11T10:41:00Z',
        acknowledged_by: 'admin', acknowledged_at: '2026-10-11T15:00:00Z'}]}}})
    const {wrapper} = await at('/pahma/alerts', Alerts)
    const refreshes = wrapper.findAll('#alerts-table a.refresh-link').map(a => a.attributes('href'))
    expect(refreshes).toContain('/admin/pahma/refreshes/pahma-2026-10-12-1') // in the message
    expect(refreshes).toContain('/admin/pahma/refreshes/pahma-2026-10-11-1') // the About column
    expect(wrapper.find('#alerts-table').text()).toContain('1a2b3c4d…3b4c50')
    expect(wrapper.find(`#alerts-table a[href="/admin/pahma/lookup?q=${MEDIA}"]`).exists()).toBe(true)
    expect(wrapper.findAll('#alerts-table .column-help').length).toBe(5) // D164
    wrapper.unmount()
  })

  it('shows the Audit log\'s By, links its targets, and copies a whole SHA-256 (D158, D165)', async () => {
    const today = new Date().toISOString()
    const day = today.slice(0, 10)
    fakeApi({'GET /museums/pahma/audit': {body: {days: 30, entries: [
      {tenant: 'pahma', at: today, admin: 'refresh pahma-2026-10-12-1', by: 'Serena', action: 'recall_ended',
        target: MEDIA, details: {why: 'no longer listed', refresh: 'pahma-2026-10-12-1'}},
      {tenant: 'pahma', at: today, admin: 'ETL (pahma)', by: 'ETL (pahma)', action: 'etl_servable_list_upload',
        target: 'pahma-2026-10-12-1', details: {sha256: SHA}},
      {tenant: 'pahma', at: today, admin: 'admin', by: 'admin', action: 'settings_change', target: 'delta_threshold_percent',
        details: {}},
      {tenant: 'pahma', at: today, admin: 'admin', by: 'admin', action: 'alert_acknowledge',
        target: `${day}#check_failed#${day}`, details: {}},
      {tenant: 'pahma', at: today, admin: 'admin', by: 'admin', action: 'alert_acknowledge',
        target: '2026-01-02#check_failed#2026-01-02', details: {}}]}}})
    const {wrapper} = await at('/pahma/audit', AuditLog)
    const table = wrapper.find('#audit-table')
    expect(table.text()).toContain('Serena')
    expect(table.text()).not.toContain('refresh pahma-2026-10-12-1 recall') // the stored actor isn't shown
    expect(table.find(`a[href="/admin/pahma/lookup?q=${MEDIA}"]`).text()).toBe('1a2b3c4d…3b4c50')
    expect(table.findAll('a.refresh-link').map(a => a.text())).toEqual(['pahma-2026-10-12-1', 'pahma-2026-10-12-1'])
    expect(table.find('a[href="/admin/pahma/settings"]').exists()).toBe(true)
    expect(table.findAll('a[href="/admin/pahma/alerts"]')).toHaveLength(1) // only the alert still listed
    expect(table.find('.copy-button[aria-label="Copy SHA-256"]').exists()).toBe(true)
    const header = table.findAll('th').map(th => th.text())
    expect(header.slice(0, 2)).toEqual(['When (UTC)', 'By'])
    wrapper.unmount()
  })

  it('copies the whole path on Past requests (D154)', async () => {
    const path = `/pahma/imageserver/blobs/${BLOB}/derivatives/Medium/content`
    fakeApi({'GET /museums/pahma/requests?range=24h': {body: {range: '24h', start: '', end: '', max_lines: 10000,
      truncated: false, days: [], top_paths: [{path, requests: 2}],
      lines: [{at: '2026-10-13T10:00:00Z', outcome: 'unserved', reason: 'recalled', path, kind: 'card', cache: '', signed: false}]}}})
    const writeText = vi.fn(async () => undefined)
    vi.stubGlobal('navigator', {...navigator, clipboard: {writeText}})
    const {wrapper} = await at('/pahma/requests', Requests)
    const copy = wrapper.find('#requests-table .copy-button')
    await copy.trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(path)
    expect(copy.text()).toBe('Copied')
    expect(wrapper.find('#requests-table').text()).toContain('catalog card') // the kind of an unserved line
    expect(wrapper.find('#requests-top-paths .copy-button').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('the file dialog', () => {
  it('says the one reason there\'s nothing to show', async () => {
    fakeApi({[`GET /museums/pahma/blobs/${BLOB}/preview?size=full`]: {status: 404, body: {
      detail: 'Nothing to show: Serena has no cached copy, and CollectionSpace has no file with this CSID.'}}})
    const FileDialog = (await import('@/components/FileDialog.vue')).default
    const memory = createRouter({history: createMemoryHistory('/admin/'), routes})
    await memory.push('/pahma/recalls')
    const wrapper = mount(FileDialog, {props: {file: {title: 'Blob CSID', name: BLOB,
      url: api.blobPreviewUrl('pahma', BLOB), lookup: BLOB}}, global: {plugins: [memory]}, attachTo: document.body})
    await flushPromises()
    document.querySelector('#file-dialog img')?.dispatchEvent(new Event('error'))
    await vi.waitFor(() => expect(document.querySelector('#file-dialog-none')?.textContent)
      .toContain('CollectionSpace has no file with this CSID'))
    expect(document.querySelector('#file-dialog-none a')).toBeNull() // nothing to open in a new tab
    wrapper.unmount()
  })
})
