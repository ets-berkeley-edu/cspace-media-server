import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import Overview from '@/views/Overview.vue'
import RefreshDetail from '@/views/RefreshDetail.vue'
import {session} from '@/session'

// Mockup version 55 (decided October 28, 2026): waiting or working, the current and pending refreshes, and a pending
// refresh's four steps.
const REFRESH = {
  refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'update_failed', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T10:05:00+00:00', rows: 40, reasons: ['ETL list update failed after 3 attempts'], newest: true,
  file_name: 'servable-list.pahma.2026-10-10.tsv', upload: null, check: null, update: null, override: null,
  actions: ['retry_update']
}
const PAGE = '/pahma/refreshes/pahma-2026-10-10-1'
const GET = 'GET /museums/pahma/refreshes/pahma-2026-10-10-1'

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

describe('waiting or working', () => {
  it('shows a clock while Serena waits for the ETL job, and a spinner while it works', async () => {
    fakeApi({[GET]: {body: {...REFRESH, state: 'started', actions: []}}})
    const waiting = await at(PAGE, RefreshDetail)
    expect(waiting.find('#refresh-state').text()).toBe('Waiting for the ETL list')
    expect(waiting.find('#refresh-state .refresh-state-waiting').exists()).toBe(true)
    expect(waiting.find('#refresh-state .refresh-state-spin').exists()).toBe(false)
    waiting.unmount()
    fakeApi({[GET]: {body: {...REFRESH, state: 'updating', actions: []}}})
    const working = await at(PAGE, RefreshDetail)
    expect(working.find('#refresh-state').text()).toBe('Applying the ETL list')
    expect(working.find('#refresh-state .refresh-state-spin').exists()).toBe(true)
    working.unmount()
  })

  it('says since when and what is normal, and in the warning colour past the deadline', async () => {
    vi.useFakeTimers({now: new Date('2026-10-10T17:03:00Z'), toFake: ['Date']})
    try {
      const body = {...REFRESH, state: 'checking', actions: [], updated_at: '2026-10-10T17:00:00+00:00', deadline_at: '2026-10-10T15:00:00Z'}
      fakeApi({[GET]: {body}})
      const wrapper = await at(PAGE, RefreshDetail)
      const detail = wrapper.find('#state-detail')
      expect(detail.text()).toBe('Checking since 17:00 UTC (3 min): usually a few minutes. Past the 08:00 Pacific deadline: the watchdog has alerted.')
      expect(detail.classes()).toContain('text-warning')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('says the ETL job may have failed while a late refresh still waits for its ETL list', async () => {
    vi.useFakeTimers({now: new Date('2026-10-10T17:01:00Z'), toFake: ['Date']})
    try {
      const body = {...REFRESH, state: 'started', actions: [], updated_at: '2026-10-10T10:01:00+00:00', deadline_at: '2026-10-10T15:00:00Z'}
      fakeApi({[GET]: {body}})
      const wrapper = await at(PAGE, RefreshDetail)
      expect(wrapper.find('#state-detail').text()).toBe('Waiting since 10:01 UTC (7 h 0 min): the ETL job uploads it. Past the 08:00 '
        + 'Pacific deadline: the watchdog has alerted, and the ETL job may have failed.')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('a pending refresh\'s steps', () => {
  it('ticks the steps done, and shows the failed one in red with what to do', async () => {
    fakeApi({[GET]: {body: REFRESH}})
    const wrapper = await at(PAGE, RefreshDetail)
    const steps = wrapper.findAll('#refresh-steps li')
    expect(steps.map(s => s.text())).toEqual(['Started', 'ETL list received', 'ETL list checked', 'ETL list update failed'])
    expect(steps.map(s => s.classes().filter(c => ['done', 'now', 'bad'].includes(c)).join())).toEqual(['done', 'done', 'done', 'bad'])
    expect(wrapper.find('#refresh-steps').attributes('aria-label')).toBe('Progress: step 4 of 4, ETL list update failed')
    expect(wrapper.find('#refresh-fix').text()).toContain('Retry the ETL list update below')
    wrapper.unmount()
  })

  it('shows the current step and the ones to come', async () => {
    fakeApi({[GET]: {body: {...REFRESH, state: 'received', actions: []}}})
    const wrapper = await at(PAGE, RefreshDetail)
    expect(wrapper.findAll('#refresh-steps li').map(s => s.text())).toEqual(['Started', 'ETL list received', 'Check the ETL list', 'Apply the ETL list'])
    expect(wrapper.find('#refresh-fix').exists()).toBe(false)
    wrapper.unmount()
  })

  it('has no steps for a closed refresh, or one a later refresh replaced', async () => {
    fakeApi({[GET]: {body: {...REFRESH, state: 'updated', actions: []}}})
    const closed = await at(PAGE, RefreshDetail)
    expect(closed.find('#refresh-steps').exists()).toBe(false)
    closed.unmount()
    fakeApi({[GET]: {body: {...REFRESH, newest: false, actions: []}}})
    const older = await at(PAGE, RefreshDetail)
    expect(older.find('#refresh-steps').exists()).toBe(false)
    older.unmount()
  })
})

describe('Overview\'s current and pending refreshes', () => {
  it('shows the current refresh, and the pending one that needs an admin in red', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]
    const current = {...REFRESH, refresh_id: 'pahma-2026-10-09-1', state: 'updated', rows: 187402, actions: []}
    const pending = {...REFRESH, state: 'check_failed', actions: ['override_threshold']}
    fakeApi({'GET /museums/pahma/status': {body: {newest: pending, current, pending, unacknowledged: 0}}})
    const wrapper = await at('/pahma', Overview)
    expect(wrapper.find('#current-card').text()).toContain('pahma-2026-10-09-1 · 187,402 rows')
    expect(wrapper.find('#current-refresh-state').text()).toBe('Updated')
    expect(wrapper.find('#pending-card').classes()).toContain('needs-admin')
    expect(wrapper.find('#pending-card').text()).toContain('Pending refresh: needs an admin')
    expect(wrapper.find('#pending-fix').text()).toBe('It failed only on the delta threshold: override it on its page if the change '
      + 'is expected, or apply another ETL list.')
    wrapper.unmount()
  })

  it('says None with no pending refresh, and with no ETL list update yet', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]
    fakeApi({'GET /museums/pahma/status': {body: {newest: null, current: null, pending: null, unacknowledged: 0}}})
    const wrapper = await at('/pahma', Overview)
    expect(wrapper.find('#current-none').text()).toContain('None yet')
    expect(wrapper.find('#pending-none').text()).toBe('None')
    wrapper.unmount()
  })
})
