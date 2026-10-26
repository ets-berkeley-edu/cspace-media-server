import {flushPromises, mount} from '@vue/test-utils'
import {afterEach, describe, expect, it} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import CacheCounts from '@/components/CacheCounts.vue'

// Synthetic counts only (issue #96).
const row = (period: string, first: string, last: string, hits: number, misses: number, extra = {}) => ({
  period, first_day: first, last_day: last, hits, misses, unserved: 1, live: false, partial: false, ...extra
})
const COUNTS = {
  by: 'day', today: '2026-10-26', since: '2026-10-20', totals: {hits: 5493, misses: 1365, unserved: 126},
  rows: [row('2026-10-26', '2026-10-26', '2026-10-26', 3, 1, {live: true}), row('2026-10-25', '2026-10-25', '2026-10-25', 7, 1)],
  live_unavailable: null
}
const WEEKS = {
  ...COUNTS, by: 'week',
  rows: [row('2026-W44', '2026-10-26', '2026-11-01', 3, 1, {live: true}), row('2026-W43', '2026-10-19', '2026-10-25', 7, 1, {partial: true})]
}

async function open() {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push('/pahma/requests')
  return mount(CacheCounts, {props: {museum: 'pahma'}, global: {plugins: [router]}, attachTo: document.body})
}

afterEach(() => window.localStorage.clear())

describe('from the cache or CollectionSpace', () => {
  it('starts collapsed, with the totals since counting began', async () => {
    fakeApi({'GET /museums/pahma/requests/counts?by=day': {body: COUNTS}})
    const wrapper = await open()
    await flushPromises()
    expect(wrapper.find('#cache-counts-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.findAll('#cache-counts-totals > span').map(s => s.text())).toEqual([
      'Since Oct 20, 2026: 6,858 served', 'from the cache 5,493 (80%)', 'from CollectionSpace 1,365 (20%)', 'unserved 126'])
    expect(wrapper.find('#cache-counts-body').exists()).toBe(false)
    expect(wrapper.find('#cache-counts-by').exists()).toBe(false)
    wrapper.unmount()
  })

  it('opens to the counts by day, week, month or year, and remembers it is open', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/requests/counts?by=day': {body: COUNTS},
      'GET /museums/pahma/requests/counts?by=week': {body: WEEKS}
    })
    const wrapper = await open()
    await flushPromises()
    await wrapper.find('#cache-counts-toggle').trigger('click')
    expect(wrapper.find('#cache-counts-toggle').attributes('aria-expanded')).toBe('true')
    expect(window.localStorage.getItem('serena.cacheCountsOpen')).toBe('true')
    const rows = () => wrapper.findAll('#cache-counts-table tbody tr').map(r => r.findAll('td').map(c => c.text()))
    expect(rows()[0].slice(0, 5)).toEqual(['2026-10-26 (today, so far)', '4', '3', '1', '75%'])
    expect(wrapper.find('#cache-counts-table [role="img"]').attributes('aria-label')).toBe('75% from the cache, 25% from CollectionSpace')
    await wrapper.findAll('#cache-counts-by button').find(b => b.text() === 'Week')?.trigger('click')
    await flushPromises()
    expect(calls.map(c => c.path)).toEqual(['/museums/pahma/requests/counts?by=day', '/museums/pahma/requests/counts?by=week'])
    expect(rows().map(r => r[0])).toEqual(['2026-W44 (Oct 26 – Nov 1) (so far)', '2026-W43 (Oct 19 – Oct 25) (from Oct 20)'])
    wrapper.unmount()
    const again = await open()
    await flushPromises()
    expect(again.find('#cache-counts-toggle').attributes('aria-expanded')).toBe('true') // remembered in this browser
    again.unmount()
  })

  it('says when today\'s counts could not be read', async () => {
    fakeApi({'GET /museums/pahma/requests/counts?by=day': {body: {...COUNTS, live_unavailable: 'Try again in a minute.'}}})
    const wrapper = await open()
    await flushPromises()
    expect(wrapper.find('#cache-counts-live').text()).toBe('Today\'s counts couldn\'t be read from the log: Try again in a minute.')
    wrapper.unmount()
  })
})
