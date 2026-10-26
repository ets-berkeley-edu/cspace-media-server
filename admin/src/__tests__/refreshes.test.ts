import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import AlertBanner from '@/components/AlertBanner.vue'
import RefreshDetail from '@/views/RefreshDetail.vue'
import Refreshes from '@/views/Refreshes.vue'
import StartRefresh from '@/views/StartRefresh.vue'
import {waiting} from '@/session'
import {pacificDate} from '@/words'

const REFRESH = {
  refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'update_failed', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T10:05:00+00:00', rows: 40, reasons: ['servability update failed after 3 attempts'], newest: true,
  file_name: 'servable-list.pahma.2026-10-10.tsv', upload: null, check: null, update: null, override: null,
  actions: ['retry_update']
}

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return {wrapper, router}
}

describe('a refresh', () => {
  it('retries a servability update only with a reason', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: REFRESH},
      'POST /museums/pahma/refreshes/pahma-2026-10-10-1/retry-update': {body: {...REFRESH, state: 'updating', actions: []}}
    })
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    await wrapper.find('#retry-update').trigger('click')
    await flushPromises()
    const confirm = () => document.querySelector('#confirm-action') as HTMLButtonElement
    // Never disabled (October 14, 2026): without a reason it sends nothing and says why, with focus on the field.
    expect(confirm().disabled).toBe(false)
    confirm().click()
    await flushPromises()
    expect(document.body.textContent).toContain('Give a reason first.')
    expect(document.activeElement?.id).toBe('reason')
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'DynamoDB is back'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    confirm().click()
    await vi.waitFor(() => expect(wrapper.find('#refresh-state').text()).toBe('Updating servability'))
    const post = calls.find(c => c.method === 'POST')
    expect(post?.body).toEqual({reason: 'DynamoDB is back'})
    expect(post?.headers['X-Serena-Admin']).toBe('1')
    wrapper.unmount()
  })
})

describe('overriding the delta threshold', () => {
  it('sends the reason and shows the refresh being checked again', async () => {
    const failed = {...REFRESH, state: 'check_failed', actions: ['override_threshold']}
    const calls = fakeApi({
      'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: failed},
      'POST /museums/pahma/refreshes/pahma-2026-10-10-1/override-threshold':
        {body: {...failed, state: 'checking', actions: [], override: {at: '2026-10-10T16:00:00+00:00'}}}
    })
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#override-threshold').text()).toBe('Override the delta threshold')
    expect(wrapper.find('#override-threshold').classes()).toContain('bg-error') // red: it changes what the public sees (D156)
    await wrapper.find('#override-threshold').trigger('click')
    await flushPromises()
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'PAHMA republished many images'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.querySelector('#confirm-action') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(wrapper.find('#refresh-state').text()).toBe('Checking the servable list'))
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({reason: 'PAHMA republished many images'})
    expect(wrapper.find('#override-threshold').exists()).toBe(false)
    wrapper.unmount()
  })
})

// Issue #108: an override says who, when and why, marks the check it answered, and the page checks again while
// Serena works.
const THRESHOLD = '50% of the rows would change; the threshold is 5.0%'
const FAILED_CHECK = {result: 'failed', rows: 40, added: 0, removed: 20, changed: 0, previous_rows: 40, threshold_percent: 5,
  delta_percent: 50, error_count: 1, errors: [{line: 0, field: 'file', problem: THRESHOLD}], warnings: []}
const OVERRIDE = {at: '2026-10-10T16:00:00+00:00', by: 'pahma-admin', reason: 'PAHMA republished many images'}
const OVERRIDDEN = {...REFRESH, state: 'checking', actions: [], check: FAILED_CHECK, override: OVERRIDE,
  reasons: ['1 problem in the servable list', 'delta threshold overridden by an admin: PAHMA republished many images']}

describe('an overridden refresh', () => {
  it('says who overrode it, when and why, and marks the check it answered', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: OVERRIDDEN}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    const banner = wrapper.find('#override-banner')
    // Issue #110: it leads with the check that failed and by how much.
    expect(wrapper.find('#override-lead').text()).toBe('A safety check failed, and an admin overrode it')
    expect(wrapper.find('#override-overshoot').text()).toBe('The servable list changes 50% of the rows; the threshold is 5%.')
    expect(banner.text()).toContain('Delta threshold overridden by pahma-admin at 2026-10-10 16:00:00 UTC.')
    expect(wrapper.find('#override-reason').text()).toBe('Reason: PAHMA republished many images')
    expect(banner.text()).toContain('This page checks again every few seconds')
    // The reason is in the banner, not one more line under Reasons.
    expect(wrapper.find('#refresh-reasons').text()).toBe('1 problem in the servable list')
    expect(wrapper.find('#check-heading').text()).toContain('Servable list check: failed, overridden by admin')
    expect(wrapper.find('#check-overridden').exists()).toBe(false) // the heading says it already
    expect(wrapper.find('#refresh-state').text()).toBe('Checking the servable list')
    const row = wrapper.find('#check-problems tbody tr')
    expect(row.classes()).toContain('overridden-problem')
    expect(row.find('s').text()).toBe(THRESHOLD)
    expect(row.text()).toContain('(overridden)')
    wrapper.unmount()
  })

  it('checks again by itself, in the background, until the update is done', async () => {
    vi.useFakeTimers()
    try {
      const answers = {'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: OVERRIDDEN as unknown}}
      const calls = fakeApi(answers)
      const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
      answers['GET /museums/pahma/refreshes/pahma-2026-10-10-1'] = {body: {...OVERRIDDEN, state: 'updated',
        check: {...FAILED_CHECK, result: 'passed', error_count: 0, errors: [], warnings: ['the delta threshold was overridden']},
        update: {deleted: 20, written: 0, unchanged: 20}}}
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      // Issue #110: once it's updated, it still reads as overridden, never as "passed" or plain "Updated".
      expect(wrapper.find('#refresh-state').text()).toBe('Updated by override')
      expect(wrapper.find('#refresh-state').classes()).toContain('text-warning')
      expect(wrapper.find('#refresh-state').classes()).toContain('refresh-state-overridden')
      expect(calls.at(-1)?.headers['X-Serena-Background']).toBe('1') // not activity: an idle tab still signs out
      expect(wrapper.find('#check-heading').text()).toContain('Servable list check: failed, overridden by admin')
      expect(wrapper.find('#check-heading').text()).not.toContain('passed')
      expect(wrapper.find('#check-overridden').exists()).toBe(false)
      expect(wrapper.find('#check-passed-without-threshold').exists()).toBe(true)
      expect(wrapper.find('#check-problems').exists()).toBe(false)
      expect(wrapper.find('#override-banner').text()).toContain('and updated from it. The team was emailed.')
      const made = calls.length
      await vi.advanceTimersByTimeAsync(15000)
      expect(calls).toHaveLength(made) // done: no more checks
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the chip when a re-check fails on something else, and reads that result', async () => {
    const other = {...FAILED_CHECK, errors: [{line: 3, field: 'kind', problem: 'not a kind Serena serves'}]}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...OVERRIDDEN, state: 'check_failed', check: other}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#check-heading').text()).toContain('Servable list check: failed')
    expect(wrapper.find('#check-heading').text()).not.toContain('overridden by admin')
    expect(wrapper.find('#check-overridden').text()).toBe('Delta threshold overridden')
    wrapper.unmount()
  })

  it('says "an admin" for an override made before it recorded who', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...OVERRIDDEN, state: 'updated', override: {at: OVERRIDE.at}}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#override-banner').text()).toContain('overridden by an admin at')
    expect(wrapper.find('#override-reason').exists()).toBe(false)
    wrapper.unmount()
  })

  it('marks overridden refreshes on Past refreshes: "Updated by override" once updated, a shield before; a bar on the row', async () => {
    const row = (n: number, state: string, override: unknown) => ({...REFRESH, refresh_id: `pahma-2026-10-1${n}-1`,
      refresh_date: `2026-10-1${n}`, state, updated_at: `2026-10-1${n}T11:00:00+00:00`, admin_refresh_date: null, override})
    fakeApi({'GET /museums/pahma/refreshes': {body: {days: 30, refreshes: [
      row(3, 'checking', OVERRIDE), row(2, 'updated', OVERRIDE), row(1, 'updated', null)]}}})
    const {wrapper} = await at('/pahma/refreshes', Refreshes)
    const [rechecking, overridden, plain] = wrapper.findAll('#refreshes-table tbody tr')
    // While Serena re-checks: its state, then the shield with its words for screen readers (issue #108).
    expect(rechecking.find('.override-mark').text()).toBe('Delta threshold overridden by pahma-admin at 2026-10-10 16:00:00 UTC')
    // Once updated (issue #110): "Updated by override" in words, so the shield alone isn't needed.
    expect(overridden.find('.refresh-state-overridden').text()).toBe('Updated by override')
    expect(overridden.find('.override-mark').exists()).toBe(false)
    expect(rechecking.classes()).toContain('override-row')
    expect(overridden.classes()).toContain('override-row')
    expect(plain.classes()).not.toContain('override-row')
    expect(plain.find('.refresh-state-overridden').exists()).toBe(false)
    expect(plain.find('.refresh-state').text()).toBe('Updated')
    expect(plain.find('.override-mark').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('the alert banner', () => {
  it('shows one line while alerts wait, newest first, with a way to the Alerts page', async () => {
    const alert = {key: '2026-10-10#missed_deadline#2026-10-10', refresh_date: '2026-10-10', kind: 'missed_deadline',
      title: 'Today\'s refresh isn\'t finished by the deadline', subject: '2026-10-10', message: 'Not updated by 08:00',
      created_at: '2026-10-10T15:00:00+00:00', acknowledged_by: null, acknowledged_at: null}
    const newer = {...alert, key: 'newer', title: 'A servable list check failed', created_at: '2026-10-10T16:00:00+00:00'}
    const calls = fakeApi({
      'GET /museums/pahma/alerts': {body: {alerts: [alert, newer, {...alert, key: 'old', acknowledged_at: 'x', acknowledged_by: 'admin'}]}}
    })
    const {wrapper} = await at('/pahma', AlertBanner)
    expect(wrapper.find('#alert-banner').text()).toContain('2 alerts:')
    expect(wrapper.find('#alert-banner-title').text()).toBe('A servable list check failed')
    expect(wrapper.find('#open-alerts').attributes('href')).toContain('/pahma/alerts')
    expect(waiting.alerts).toHaveLength(2) // the bell counts these
    // The banner's checks don't count as activity, so an open tab still signs out when idle.
    expect(calls.find(c => c.path.endsWith('/alerts'))?.headers['X-Serena-Background']).toBe('1')
    wrapper.unmount()
  })

  it('stays hidden while no alert waits', async () => {
    fakeApi({'GET /museums/pahma/alerts': {body: {alerts: []}}})
    const {wrapper} = await at('/pahma', AlertBanner)
    expect(wrapper.find('#alert-banner').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('starting an admin refresh', () => {
  it('sends the servable list with the confirmation and opens the new refresh', async () => {
    const calls = fakeApi({
      'POST /museums/pahma/refreshes': {body: {...REFRESH, refresh_id: 'pahma-2026-10-11-1', state: 'checking', actions: []}},
      'GET /museums/pahma/refreshes/pahma-2026-10-11-1': {body: {...REFRESH, refresh_id: 'pahma-2026-10-11-1', state: 'checking', actions: []}}
    })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({method: init.method || 'GET', path: url.replace('/admin/v1', ''), headers: (init.headers || {}) as Record<string, string>, body: init.body})
      const path = url.replace('/admin/v1', '')
      const body = path.endsWith('/refreshes') || path.includes('2026-10-11-1') ? {...REFRESH, refresh_id: 'pahma-2026-10-11-1', state: 'checking', actions: []} : {}
      return new Response(JSON.stringify(body), {status: 200})
    }))
    const {wrapper, router} = await at('/pahma/start-refresh', StartRefresh)
    const file = new File(['blob_csid\tmedia_csid\tkind\taccess\n'], 'servable-list.pahma.2026-10-09.tsv')
    const vm = wrapper.vm as unknown as {$: {setupState: {file: File | null, refreshDate: string, confirmed: boolean, reason: string}}}
    expect(vm.$.setupState.refreshDate).toBe(pacificDate()) // today, to start (D75)
    vm.$.setupState.file = file
    vm.$.setupState.refreshDate = '2026-10-09'
    vm.$.setupState.confirmed = true
    vm.$.setupState.reason = 'ETL log checked: café'
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/pahma/refreshes/pahma-2026-10-11-1'))
    const post = calls.find(c => c.method === 'POST')
    expect(post?.headers['X-Live-Core-Confirmed']).toBe('yes')
    expect(post?.headers['X-Refresh-Date']).toBe('2026-10-09')
    expect(post?.headers['X-File-Name']).toBe('servable-list.pahma.2026-10-09.tsv')
    expect(post?.headers['X-Reason']).toBe('ETL%20log%20checked%3A%20caf%C3%A9')
    expect(post?.headers['X-Serena-Admin']).toBe('1')
    expect(post?.body).toBe(file)
    wrapper.unmount()
  })
})

describe('pacificDate', () => {
  it('is the Pacific date, not the UTC one', () => {
    const evening = new Date('2026-10-11T03:30:00Z') // 20:30 on October 10 in Berkeley
    expect(pacificDate(0, evening)).toBe('2026-10-10')
    expect(pacificDate(1, evening)).toBe('2026-10-09')
  })
})

describe('a page that can\'t load', () => {
  it('says so', async () => {
    fakeApi({'GET /museums/pahma/refreshes': {status: 401, body: {detail: 'Sign in to this museum.'}}})
    const {wrapper} = await at('/pahma/refreshes', Refreshes)
    expect(wrapper.find('#load-error').text()).toContain('Sign in to this museum.')
    wrapper.unmount()
  })
})

describe('a refresh\'s state', () => {
  it('shows a failed refresh in red with a failure icon, and an updated one in green without', async () => {
    const row = (n: number, state: string) => ({...REFRESH, refresh_id: `pahma-2026-10-1${n}-1`, refresh_date: `2026-10-1${n}`,
      state, updated_at: `2026-10-1${n}T11:00:00+00:00`, admin_refresh_date: null})
    fakeApi({'GET /museums/pahma/refreshes': {body: {days: 30, refreshes: [row(2, 'check_failed'), row(1, 'updated')]}}})
    const {wrapper} = await at('/pahma/refreshes', Refreshes)
    const [failed, updated] = wrapper.findAll('#refreshes-table tbody .refresh-state')
    expect(failed.text()).toBe('Servable list check failed') // the label alone is read out
    expect(failed.classes()).toContain('text-error')
    expect(failed.find('.refresh-state-icon').attributes('aria-hidden')).toBe('true')
    expect(updated.text()).toBe('Updated')
    expect(updated.classes()).toContain('text-success')
    expect(updated.classes()).not.toContain('text-error')
    expect(updated.find('.refresh-state-icon').exists()).toBe(false)
    wrapper.unmount()
  })

  it('says the same on the refresh\'s page', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: REFRESH}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#refresh-state').text()).toBe('Servability update failed')
    expect(wrapper.find('#refresh-state').classes()).toContain('text-error')
    expect(wrapper.find('#refresh-state .refresh-state-icon').exists()).toBe(true)
    wrapper.unmount()
  })
})
