import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import Overview from '@/views/Overview.vue'
import RefreshDetail from '@/views/RefreshDetail.vue'
import {session} from '@/session'

// A failed update (decided October 28, 2026, mockup version 56): Serena retries it by itself, an admin can retry it
// now, and a retry that comes second says who got there first.
const FAILED = {
  refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'update_failed', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T16:41:30+00:00', rows: 40, reasons: ['ETL list update failed after 3 attempts'], newest: true,
  file_name: 'servable-list.pahma.2026-10-10.tsv', upload: null, check: null, update: null, override: null,
  actions: ['retry_update'], retry_until: '2026-10-10T22:41:30+00:00'
}
const PAGE = '/pahma/refreshes/pahma-2026-10-10-1'
const GET = 'GET /museums/pahma/refreshes/pahma-2026-10-10-1'
const POST = 'POST /museums/pahma/refreshes/pahma-2026-10-10-1/retry-update'

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

function during<T>(now: string, run: () => Promise<T>): Promise<T> {
  vi.useFakeTimers({now: new Date(now), toFake: ['Date']})
  return run().finally(() => vi.useRealTimers())
}

describe('a failed update Serena retries', () => {
  it('says until when Serena retries it, on the page and in the dialog', () => during('2026-10-10T17:00:00Z', async () => {
    fakeApi({[GET]: {body: FAILED}})
    const wrapper = await at(PAGE, RefreshDetail)
    expect(wrapper.find('#refresh-fix').text()).toBe('Serena serves some of each ETL list. Serena tries the update again '
      + 'every 10 minutes, until 22:41 UTC. Retry the ETL list update below to try now, or apply another ETL list.')
    await wrapper.find('#retry-update').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Serena runs the ETL list update again now, doing only what\'s left. '
      + 'Do this once whatever stopped it is fixed; Serena also tries again by itself every 10 minutes until 22:41 UTC.')
    wrapper.unmount()
  }))

  it('says Serena has stopped retrying once its time is up', () => during('2026-10-10T23:00:00Z', async () => {
    fakeApi({[GET]: {body: FAILED}})
    const wrapper = await at(PAGE, RefreshDetail)
    expect(wrapper.find('#refresh-fix').text()).toContain('Serena has stopped retrying it. Retry the ETL list update below')
    wrapper.unmount()
  }))

  it('shows who got there first, and the refresh as it is now, when a retry comes second', async () => {
    const answers: Record<string, unknown> = {
      [GET]: {body: FAILED},
      [POST]: {status: 409, body: {detail: 'Not retried: pahma-admin retried it first, and Serena is applying the ETL '
        + 'list now. This page shows the refresh as it is.'}}
    }
    fakeApi(answers as never)
    const wrapper = await at(PAGE, RefreshDetail)
    await wrapper.find('#retry-update').trigger('click')
    await flushPromises()
    answers[GET] = {body: {...FAILED, state: 'updating', actions: [], retry_until: null}}
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'DynamoDB is back'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.querySelector('#confirm-action') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(wrapper.find('#refresh-state').text()).toBe('Applying the ETL list'))
    expect(wrapper.text()).toContain('Not retried: pahma-admin retried it first')
    expect(wrapper.find('#retry-update').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('partly replaced', () => {
  it('flags the current refresh while the pending one\'s update has failed', () => during('2026-10-10T17:00:00Z', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]
    const current = {...FAILED, refresh_id: 'pahma-2026-10-09-1', state: 'updated', actions: [], retry_until: null}
    fakeApi({'GET /museums/pahma/status': {body: {newest: FAILED, current, pending: FAILED, unacknowledged: 0}}})
    const wrapper = await at('/pahma', Overview)
    expect(wrapper.find('#partly-replaced').text()).toBe('partly replaced')
    expect(wrapper.find('#partly-replaced-detail').text()).toBe('pahma-2026-10-10-1\'s update stopped partway, so Serena '
      + 'serves some of each ETL list, never a file either one restricts or drops. Serena tries the update again every 10 '
      + 'minutes, until 22:41 UTC.')
    wrapper.unmount()
  }))

  it('doesn\'t flag it otherwise', async () => {
    session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]
    const current = {...FAILED, state: 'updated', actions: [], retry_until: null}
    fakeApi({'GET /museums/pahma/status': {body: {newest: current, current, pending: null, unacknowledged: 0}}})
    const wrapper = await at('/pahma', Overview)
    expect(wrapper.find('#partly-replaced').exists()).toBe(false)
    wrapper.unmount()
  })
})
