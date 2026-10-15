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
