import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {KeepAlive, defineComponent, h, ref} from 'vue'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import Requests from '@/views/Requests.vue'

// Synthetic paths and museum only.
const line = (at: string, outcome: string, reason = '', n = 1) => ({
  at, outcome, reason, path: `/pahma/imageserver/blobs/b${n}/content`, kind: outcome === 'served' ? 'image' : '',
  cache: outcome === 'served' ? 'hit' : '', signed: false
})

const REPORT = {
  range: '24h', start: '2026-10-11T18:00:00+00:00', end: '2026-10-12T18:00:00+00:00', max_lines: 10000,
  truncated: false,
  days: [{day: '2026-10-12', served: 2, unserved: {not_listed: 1, too_large: 1}, unserved_total: 2}],
  top_paths: [{path: '/pahma/imageserver/blobs/b1/content', requests: 3}],
  sizes: ['Thumbnail', 'Small', 'Medium', 'FullHD', 'OriginalJpeg', 'original'],
  served_by_size: [{size: 'Medium', requests: 2}, {size: 'original', requests: 1}],
  served_by_cache: {hit: 1, miss: 1},
  lines: [
    line('2026-10-12T17:00:00.000+00:00', 'served'),
    line('2026-10-12T17:01:00.000+00:00', 'unserved', 'not_listed', 2),
    line('2026-10-12T17:02:00.000+00:00', 'served'),
    line('2026-10-12T17:03:00.000+00:00', 'unserved', 'too_large', 3)
  ],
  read_at: '2026-10-12T18:00:00+00:00', try_again_in: null
}

async function open() {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push('/pahma/requests')
  return mount(Requests as never, {global: {plugins: [router]}, attachTo: document.body})
}

describe('the Past requests page', () => {
  it('shows a spinner while it reads the log, then the counts and the newest lines', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/requests?range=24h': {body: REPORT},
      'GET /museums/pahma/requests?range=7d': {body: {...REPORT, range: '7d', truncated: true}}
    })
    const wrapper = await open()
    expect(wrapper.find('#requests-loading').exists()).toBe(true) // D108
    await flushPromises()
    expect(wrapper.find('#requests-loading').exists()).toBe(false)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA Past requests')
    expect(wrapper.find('#requests-by-day').text()).toContain('not listed 1, too large 1')
    expect(wrapper.find('#requests-top-paths').text()).toContain('b1original') // its Blob CSID, then its size (October 14)
    // The Served card counts every served request in the range by size, smallest to largest (October 14, 2026).
    expect(wrapper.find('#requests-by-size').text()).toBe('by size: Medium\u00a02 · original\u00a01')
    expect(wrapper.find('#requests-by-cache').text()).toBe('from the cache 1 · from CollectionSpace 1') // issue #96
    expect(wrapper.find('#requests-top-paths [title="/pahma/imageserver/blobs/b1/content"]').exists()).toBe(true)
    const times = () => wrapper.findAll('#requests-table tbody tr').map(row => row.find('td').text())
    expect(times()[0]).toBe('2026-10-12 17:03:00 UTC') // newest first
    expect(wrapper.find('#export-requests').attributes('href')).toBe('/admin/v1/museums/pahma/requests/export.csv?range=24h')
    const sevenDays = wrapper.findAll('#request-range button').find(b => b.text() === 'Last 7 days')
    await sevenDays?.trigger('click')
    await flushPromises()
    expect(calls.map(c => c.path).filter(p => p.includes('?range='))).toEqual(
      ['/museums/pahma/requests?range=24h', '/museums/pahma/requests?range=7d'])
    // The counts from the cache or CollectionSpace don't follow the range: read once (issue #96).
    expect(calls.filter(c => c.path.includes('/requests/counts')).length).toBe(1)
    expect(wrapper.find('#requests-truncated').text()).toContain('the table lists the newest 10,000')
    expect(wrapper.find('#export-requests').attributes('href')).toBe('/admin/v1/museums/pahma/requests/export.csv?range=7d')
    wrapper.unmount()
  })

  it('filters the lines, and exports what it shows', async () => {
    fakeApi({'GET /museums/pahma/requests?range=24h': {body: REPORT}})
    const wrapper = await open()
    await flushPromises()
    const vm = wrapper.vm as unknown as {outcome: string, reason: string}
    vm.outcome = 'unserved'
    vm.reason = 'too_large'
    await flushPromises()
    const rows = wrapper.findAll('#requests-table tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('too large')
    expect(wrapper.find('#export-requests').attributes('href')).toBe(
      '/admin/v1/museums/pahma/requests/export.csv?range=24h&outcome=unserved&reason=too_large')
    vm.outcome = 'served' // a served request has no reason
    await flushPromises()
    expect(vm.reason).toBe('')
    expect(wrapper.findAll('#requests-table tbody tr')).toHaveLength(2)
    wrapper.unmount()
  })

  it('says when the log can\'t be read', async () => {
    fakeApi({'GET /museums/pahma/requests?range=24h': {status: 504, body: {
      detail: 'Reading the log took too long. Choose a shorter range, or try again in a minute.'}}})
    const wrapper = await open()
    await flushPromises()
    expect(wrapper.text()).toContain('Choose a shorter range')
    wrapper.unmount()
  })

  it('opens a path\'s file in a dialog, and a bad CSID stays text (D145)', async () => {
    const blob = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b'
    const good = {...line('2026-10-12T17:04:00.000+00:00', 'served'), path: `/pahma/imageserver/blobs/${blob}/derivatives/Medium/content`}
    const bad = {...line('2026-10-12T17:05:00.000+00:00', 'unserved', 'bad_csid'), path: '/pahma/imageserver/blobs/not-a-csid/content'}
    fakeApi({'GET /museums/pahma/requests?range=24h': {body: {...REPORT, lines: [good, bad]}}})
    const wrapper = await open()
    await flushPromises()
    const links = wrapper.findAll('#requests-table .file-link')
    // One line, shortened in the middle; the whole path on hover (D152).
    expect(links.map(l => l.text())).toEqual(['0f1e2d3c…3f4a5b']) // the Blob CSID; the size has its own column
    expect(links[0].attributes('title')).toMatch(/^View this file: \/pahma\/imageserver\/blobs\/[0-9a-f-]{36}\//) // whole
    // A bad CSID stays text: its shortened CSID, the path on hover (October 14, 2026).
    expect(wrapper.findAll('#requests-table .request-path [title]').map(p => p.attributes('title'))).toContain(bad.path)
    expect(wrapper.find('#requests-table tbody').text()).toContain('Medium')
    await links[0].trigger('click')
    await flushPromises()
    const dialog = document.querySelector('#file-dialog')
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(`/admin/v1/museums/pahma/blobs/${blob}/preview?size=Medium`)
    expect(dialog?.textContent).toContain('This request, 2026-10-12 17:04:00 UTC: served.')
    ;(document.querySelector('#file-dialog-dismiss') as HTMLElement).click()
    await flushPromises()
    wrapper.unmount()
  })

  it('shows a Media URL as "Media <CSID…>" with its size, and opens its file (pull request 15, D179)', async () => {
    const media = '20349bfa-cad6-5f47-9acd-dcd34e3f0b98'
    const asked = {...line('2026-10-12T17:06:00.000+00:00', 'served'), path: `/pahma/imageserver/media/${media}/blob/derivatives/Small/content`}
    fakeApi({'GET /museums/pahma/requests?range=24h': {body: {...REPORT, lines: [asked]}}})
    const wrapper = await open()
    await flushPromises()
    const links = wrapper.findAll('#requests-table .file-link')
    expect(links.map(l => l.text())).toEqual(['Media 20349bfa…3f0b98'])
    expect(wrapper.find('#requests-table tbody').text()).toContain('Small')
    expect(wrapper.find('#requests-table tbody').text()).not.toContain('not a Blob path')
    await links[0].trigger('click')
    await flushPromises()
    const dialog = document.querySelector('#file-dialog')
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(`/admin/v1/museums/pahma/media/${media}/preview?size=Small`)
    ;(document.querySelector('#file-dialog-dismiss') as HTMLElement).click()
    await flushPromises()
    wrapper.unmount()
  })
})

// Issue #100: Refresh reads the log again now; Serena allows it once per museum every 10 seconds.
const COUNTS = {by: 'day', today: '2026-10-12', since: null, totals: {hits: 0, misses: 0, unserved: 0}, rows: [],
  live_unavailable: null, read_at: '2026-10-12T18:00:00+00:00', try_again_in: null}

describe('reading the log again', () => {
  it('says when the numbers were read, and Refresh reads the report and today\'s counts again, fresh', async () => {
    const answers: Record<string, {body: unknown}> = {
      'GET /museums/pahma/requests?range=24h': {body: REPORT},
      'GET /museums/pahma/requests/counts?by=day': {body: COUNTS}
    }
    const calls = fakeApi(answers)
    const wrapper = await open()
    await flushPromises()
    expect(wrapper.find('#requests-read-at').text()).toBe('Read 2026-10-12 18:00:00 UTC')
    let answer: (value: Response) => void = () => {}
    const reading = new Promise<Response>(resolve => { answer = resolve })
    const fetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) =>
      url.includes('requests?range=24h&fresh=1') ? reading : fetch(url, init)))
    await wrapper.find('#requests-refresh').trigger('click')
    await flushPromises()
    // While it reads: the numbers stay, and the time's place says so.
    expect(wrapper.find('#requests-read-at').text()).toBe('Reading the log…')
    expect(wrapper.find('#requests-by-day').exists()).toBe(true)
    expect(wrapper.find('#requests-refresh').attributes('aria-busy')).toBe('true')
    answer(new Response(JSON.stringify({...REPORT, read_at: '2026-10-12T18:00:30+00:00',
      days: [{...REPORT.days[0], served: 3}]}), {status: 200}))
    await flushPromises()
    expect(wrapper.find('#requests-read-at').text()).toBe('Read 2026-10-12 18:00:30 UTC')
    expect(wrapper.find('#requests-served').text()).toContain('3')
    expect(wrapper.find('#requests-refresh-note').exists()).toBe(false)
    expect(calls.map(c => c.path)).toContain('/museums/pahma/requests/counts?by=day&fresh=1')
    wrapper.unmount()
  })

  it('says when to try again, when Serena gives the same numbers inside its 10 seconds', async () => {
    fakeApi({
      'GET /museums/pahma/requests?range=24h': {body: REPORT},
      'GET /museums/pahma/requests?range=24h&fresh=1': {body: {...REPORT, try_again_in: 7}},
      'GET /museums/pahma/requests?range=1h': {body: {...REPORT, range: '1h'}},
      'GET /museums/pahma/requests/counts?by=day': {body: COUNTS},
      'GET /museums/pahma/requests/counts?by=day&fresh=1': {body: {...COUNTS, try_again_in: 7}}
    })
    const wrapper = await open()
    await flushPromises()
    await wrapper.find('#requests-refresh').trigger('click')
    await flushPromises()
    expect(wrapper.find('#requests-refresh-note').text()).toBe(
      'Read again less than 10 seconds ago, so Serena gave the same numbers. Try again in 7 seconds.')
    expect(wrapper.find('#requests-refresh-note').attributes('role')).toBe('status')
    const lastHour = wrapper.findAll('#request-range button').find(b => b.text() === 'Last hour')
    await lastHour?.trigger('click')
    await flushPromises()
    expect(wrapper.find('#requests-refresh-note').exists()).toBe(false) // a new range: a new read
    wrapper.unmount()
  })

  it('reads again on coming back once the numbers are over a minute old, not before', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/requests?range=24h': {body: REPORT},
      'GET /museums/pahma/requests/counts?by=day': {body: COUNTS}
    })
    const router = createRouter({history: createMemoryHistory('/admin/'), routes})
    await router.push('/pahma/requests')
    const here = ref(true)
    const Elsewhere = defineComponent({render: () => h('p', 'elsewhere')})
    const Host = defineComponent({setup: () => () => h(KeepAlive, null, [here.value ? h(Requests) : h(Elsewhere)])})
    const wrapper = mount(Host, {global: {plugins: [router]}, attachTo: document.body})
    await flushPromises()
    const reads = () => calls.filter(c => c.path.startsWith('/museums/pahma/requests?')).length
    expect(reads()).toBe(1)
    const now = vi.spyOn(Date, 'now')
    try {
      now.mockReturnValue(Date.parse(REPORT.read_at) + 30_000) // back after 30 seconds: as it was
      here.value = false
      await flushPromises()
      here.value = true
      await flushPromises()
      expect(reads()).toBe(1)
      now.mockReturnValue(Date.parse(REPORT.read_at) + 61_000) // after more than a minute: read again (not fresh)
      here.value = false
      await flushPromises()
      here.value = true
      await flushPromises()
      expect(reads()).toBe(2)
      expect(calls.filter(c => c.path.includes('fresh=1'))).toHaveLength(0)
    } finally {
      now.mockRestore()
      wrapper.unmount()
    }
  })
})
