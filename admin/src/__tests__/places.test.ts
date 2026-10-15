/**
 * Keeping an admin's place (Richard, October 14, 2026): list pages in the address, "← Back to …", and the shorter
 * Past requests paths. Synthetic CSIDs only.
 */
import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import type {RouteLocationNormalized} from 'vue-router'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {backFor} from '@/navigation'
import {routes} from '@/router'
import {session} from '@/session'
import AuditLog from '@/views/AuditLog.vue'
import Requests from '@/views/Requests.vue'
import {middlePath, shortPath} from '@/words'

const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b'
const MEDIA = '20349bfa-cad6-5f47-9acd-dcd34e3f0b98'

function at(name: string, museum = 'pahma', extra: Record<string, unknown> = {}): RouteLocationNormalized {
  return {name, params: {museum, ...extra}, meta: {}, fullPath: `/${museum}/${name}?x=1`} as unknown as RouteLocationNormalized
}

describe('Past requests paths', () => {
  it('leaves out what every row shares', () => {
    expect(shortPath(`/pahma/imageserver/blobs/${BLOB}/derivatives/Medium/content`)).toBe('0f1e2d3c…3f4a5b · Medium')
    expect(shortPath(`/pahma/imageserver/blobs/${BLOB}/content`)).toBe('0f1e2d3c…3f4a5b · original')
    expect(shortPath(`/pahma/imageserver/media/${MEDIA}/blob/derivatives/Medium/content`)).toBe('Media 20349bfa…3f0b98 · Medium')
    expect(shortPath(`/pahma/imageserver/blobs/${BLOB}`)).toBe('0f1e2d3c…3f4a5b')
    expect(shortPath('/pahma/imageserver/blobs/not-a-csid/content')).toBe('not-a-csid · original')
    expect(shortPath('/pahma/other')).toBe('/pahma/other')
  })

  it('shortens a Media CSID in a path like a Blob CSID', () => {
    expect(middlePath(`/pahma/imageserver/media/${MEDIA}/derivatives/Medium/content`))
      .toBe('/pahma/imageserver/media/20349bfa…3f0b98/derivatives/Medium/content')
  })
})

describe('"← Back to …"', () => {
  it('goes back to the page a link came from, and not after the menu, sign-in or another museum', () => {
    expect(backFor(at('lookup'), at('requests'), false, null)).toEqual({path: '/pahma/requests?x=1', title: 'Past requests'})
    expect(backFor(at('refresh', 'pahma', {refreshId: 'r'}), at('alerts'), false, null)?.title).toBe('Alerts')
    expect(backFor(at('lookup'), at('refresh', 'pahma', {refreshId: 'pahma-2026-10-14-1'}), false, null)?.title)
      .toBe('refresh pahma-2026-10-14-1')
    expect(backFor(at('lookup'), at('requests'), true, null)).toBeNull() // the menu: a new task
    expect(backFor(at('lookup'), at('requests', 'cinefiles'), false, null)).toBeNull()
    const signIn = {...at('sign-in'), meta: {public: true}} as RouteLocationNormalized
    expect(backFor(at('lookup'), signIn, false, null)).toBeNull()
    const earlier = {path: '/pahma/requests', title: 'Past requests'}
    expect(backFor(at('lookup'), at('lookup'), false, earlier)).toBe(earlier) // a new look up keeps the way back
  })
})

describe('a list page in the address', () => {
  it('reads its sort, page and filters from the address, and writes them back without the defaults', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}] as never
    const now = new Date().toISOString()
    const entries = Array.from({length: 30}, (_, n) => ({tenant: 'pahma', at: now, admin: `admin${n}`, by: `admin${n}`,
      action: 'sign_in', target: 'pahma', details: {}}))
    fakeApi({'GET /museums/pahma/audit': {body: {days: 30, entries}}})
    const router = createRouter({history: createMemoryHistory('/admin/'), routes})
    await router.push('/pahma/audit?sort=by.asc&page=2')
    const wrapper = mount(AuditLog, {global: {plugins: [router]}, attachTo: document.body})
    await flushPromises()
    expect(wrapper.find('#audit-table').text()).toContain('26-30 of 30') // page 2 of the address
    await wrapper.findAll('#audit-table th')[0].trigger('click') // sort by When instead: back to page 1
    await vi.waitFor(() => expect(router.currentRoute.value.query).toEqual({sort: 'at.asc'}))
    wrapper.unmount()
  })

  it('keeps Past requests\' range and filters in the address', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}] as never
    const report = {range: '7d', start: '', end: '', max_lines: 10000, truncated: false, signed_links: false, days: [],
      top_paths: [], lines: [{at: '2026-10-13T10:00:00Z', outcome: 'unserved', reason: 'recalled', path: '/p', kind: '',
        cache: '', signed: false}]}
    const calls = fakeApi({'GET /museums/pahma/requests?range=7d': {body: report}})
    const router = createRouter({history: createMemoryHistory('/admin/'), routes})
    await router.push('/pahma/requests?range=7d&outcome=unserved&reason=recalled')
    const wrapper = mount(Requests, {global: {plugins: [router]}, attachTo: document.body})
    await flushPromises()
    expect(calls.map(c => c.path)).toEqual(['/museums/pahma/requests?range=7d'])
    expect(router.currentRoute.value.query).toEqual({range: '7d', outcome: 'unserved', reason: 'recalled'}) // kept
    expect(wrapper.findAll('#requests-table th').map(th => th.text())).not.toContain('Signed link') // not Cinefiles
    expect(wrapper.find('#requests-table .file-link').exists()).toBe(false) // '/p' has no CSID: plain text
    expect(wrapper.find('#requests-table [title="/p"]').exists()).toBe(true) // the whole path on hover
    wrapper.unmount()
  })
})
