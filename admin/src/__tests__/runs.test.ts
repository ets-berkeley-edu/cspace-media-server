import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import AlertBanner from '@/components/AlertBanner.vue'
import RunDetail from '@/views/RunDetail.vue'
import Upload from '@/views/Upload.vue'
import {pacificDate} from '@/words'

const RUN = {
  run_id: 'pahma-2026-10-10-1', night: '2026-10-10', state: 'apply_failed', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T10:05:00+00:00', rows: 40, reasons: ['apply failed after 3 attempts'], newest: true,
  file_name: 'blob-media.pahma.2026-10-10.tsv', upload: null, preflight: null, solr_load: null, apply: null,
  actions: ['retry_apply']
}

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return {wrapper, router}
}

describe('a run', () => {
  it('retries an apply only with a reason', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/runs/pahma-2026-10-10-1': {body: RUN},
      'POST /museums/pahma/runs/pahma-2026-10-10-1/retry-apply': {body: {...RUN, state: 'applying', actions: []}}
    })
    const {wrapper} = await at('/pahma/runs/pahma-2026-10-10-1', RunDetail)
    await wrapper.find('#retry-apply').trigger('click')
    await flushPromises()
    const confirm = () => document.querySelector('#confirm-action') as HTMLButtonElement
    expect(confirm().disabled).toBe(true) // no reason yet
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'DynamoDB is back'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    confirm().click()
    await vi.waitFor(() => expect(wrapper.find('#run-state').text()).toBe('Applying'))
    const post = calls.find(c => c.method === 'POST')
    expect(post?.body).toEqual({reason: 'DynamoDB is back'})
    expect(post?.headers['X-Serena-Admin']).toBe('1')
    wrapper.unmount()
  })
})

describe('the alert banner', () => {
  it('shows unacknowledged alerts and acknowledges one', async () => {
    const alert = {key: '2026-10-10#missed_deadline#2026-10-10', night: '2026-10-10', kind: 'missed_deadline',
      title: 'Tonight\'s run isn\'t finished by the deadline', subject: '2026-10-10', message: 'Not applied by 08:00',
      created_at: '2026-10-10T15:00:00+00:00', acknowledged_by: null, acknowledged_at: null}
    const calls = fakeApi({
      'GET /museums/pahma/alerts': {body: {alerts: [alert, {...alert, key: 'old', acknowledged_at: 'x', acknowledged_by: 'admin'}]}},
      'POST /museums/pahma/alerts/acknowledge': {body: {acknowledged: alert.key}}
    })
    const {wrapper} = await at('/pahma', AlertBanner)
    expect(wrapper.findAll('.acknowledge')).toHaveLength(1)
    expect(wrapper.text()).toContain('Not applied by 08:00')
    expect(wrapper.text().split('2026-10-10')).toHaveLength(2) // the night once: the subject is the same night
    await wrapper.find('.acknowledge').trigger('click')
    await flushPromises()
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({key: alert.key})
    wrapper.unmount()
  })
})

describe('uploading a night\'s file', () => {
  it('sends the file with the confirmation and opens its run', async () => {
    const calls = fakeApi({
      'PUT /museums/pahma/uploads': {body: {...RUN, run_id: 'pahma-2026-10-11-1', state: 'preflighting', actions: []}},
      'GET /museums/pahma/runs/pahma-2026-10-11-1': {body: {...RUN, run_id: 'pahma-2026-10-11-1', state: 'preflighting', actions: []}}
    })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({method: init.method || 'GET', path: url.replace('/admin/v1', ''), headers: (init.headers || {}) as Record<string, string>, body: init.body})
      const path = url.replace('/admin/v1', '')
      const body = path.endsWith('/uploads') || path.includes('2026-10-11-1') ? {...RUN, run_id: 'pahma-2026-10-11-1', state: 'preflighting', actions: []} : {}
      return new Response(JSON.stringify(body), {status: 200})
    }))
    const {wrapper, router} = await at('/pahma/upload', Upload)
    const file = new File(['blob_csid\tmedia_csid\tkind\taccess\n'], 'blob-media.pahma.2026-10-09.tsv')
    const vm = wrapper.vm as unknown as {$: {setupState: {file: File | null, night: string, confirmed: boolean}}}
    expect(vm.$.setupState.night).toBe(pacificDate(1)) // last night, to start
    vm.$.setupState.file = file
    vm.$.setupState.night = '2026-10-09'
    vm.$.setupState.confirmed = true
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/pahma/runs/pahma-2026-10-11-1'))
    const put = calls.find(c => c.method === 'PUT')
    expect(put?.headers['X-Loaded-Confirmed']).toBe('yes')
    expect(put?.headers['X-Night']).toBe('2026-10-09')
    expect(put?.headers['X-File-Name']).toBe('blob-media.pahma.2026-10-09.tsv')
    expect(put?.headers['X-Serena-Admin']).toBe('1')
    expect(put?.body).toBe(file)
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
