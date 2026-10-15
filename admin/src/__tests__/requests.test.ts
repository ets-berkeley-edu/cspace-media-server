import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it} from 'vitest'
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
  lines: [
    line('2026-10-12T17:00:00.000+00:00', 'served'),
    line('2026-10-12T17:01:00.000+00:00', 'unserved', 'not_listed', 2),
    line('2026-10-12T17:02:00.000+00:00', 'served'),
    line('2026-10-12T17:03:00.000+00:00', 'unserved', 'too_large', 3)
  ]
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
    expect(wrapper.find('#requests-top-paths [title="/pahma/imageserver/blobs/b1/content"]').exists()).toBe(true)
    const times = () => wrapper.findAll('#requests-table tbody tr').map(row => row.find('td').text())
    expect(times()[0]).toBe('2026-10-12 17:03:00 UTC') // newest first
    expect(wrapper.find('#export-requests').attributes('href')).toBe('/admin/v1/museums/pahma/requests/export.csv?range=24h')
    const sevenDays = wrapper.findAll('#request-range button').find(b => b.text() === 'Last 7 days')
    await sevenDays?.trigger('click')
    await flushPromises()
    expect(calls.map(c => c.path)).toEqual(['/museums/pahma/requests?range=24h', '/museums/pahma/requests?range=7d'])
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
})
