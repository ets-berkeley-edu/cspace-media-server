import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import ManualRefresh from '@/views/ManualRefresh.vue'
import Refreshes from '@/views/Refreshes.vue'
import {session} from '@/session'
import {pacificDate} from '@/words'

// Manual refresh (reworked October 28, 2026, mockup version 55): "Replace with:", a dry run that changes nothing, then
// Apply refresh or Apply with override, which starts a manual refresh that updates by itself; then a summary.
const REFRESH = {
  refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'updated', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T10:05:00+00:00', rows: 41, reasons: [], newest: false, manual: false,
  admin_refresh_date: null, admin_refresh_from: null, file_name: 'servable-list.pahma.2026-10-10.tsv', upload: null,
  check: null, update: null, override: null, actions: []
}
const LISTS = [
  {refresh_id: 'pahma-2026-10-11-1', refresh_date: '2026-10-11', state: 'check_failed', override: null, rows: 40,
    sha256: 'ab'.repeat(32), uploaded_at: '2026-10-11T10:02:04+00:00'},
  {refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'updated', override: null, rows: 41,
    sha256: 'cd'.repeat(32), uploaded_at: '2026-10-10T10:02:04+00:00'}
]
const WAITING = {...REFRESH, refresh_id: 'pahma-2026-10-12-1', refresh_date: '2026-10-12', state: 'received', newest: true}
const STARTED = {...REFRESH, refresh_id: 'pahma-2026-10-12-2', refresh_date: '2026-10-12', state: 'checking', newest: true,
  manual: true, created_at: '2026-10-12T17:00:00+00:00'}
const PASSED = {check: {result: 'passed', rows: 41, added: 1, removed: 0, changed: 0, previous_rows: 40, delta_percent: 2.5,
  threshold_percent: 5, warnings: [], errors: [], error_count: 0}, checked_at: '2026-10-12T16:59:00+00:00',
against: {refresh_id: 'pahma-2026-10-10-1', updated_at: '2026-10-10T10:05:00+00:00'}}
const DELTA = {...PASSED, check: {...PASSED.check, result: 'failed', changed: 20, delta_percent: 50, error_count: 1,
  errors: [{line: 0, field: 'file', problem: '50% of the rows change; the threshold is 5%'}]}}
const OTHER = {...PASSED, check: {...PASSED.check, result: 'failed', error_count: 3,
  errors: [{line: 7, field: 'kind', problem: '"thumbnail" isn\'t a kind Serena serves'}]}}

type Answers = Record<string, {status?: number, body: unknown}>
const choices = (pending: unknown = null): Answers => ({
  'GET /museums/pahma/servable-lists': {body: {lists: LISTS}},
  'GET /museums/pahma/status': {body: {newest: pending || REFRESH, current: REFRESH, pending, unacknowledged: 0}}
})

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}
const setup = (wrapper: {vm: unknown}) => (wrapper.vm as {$: {setupState: Record<string, unknown>}}).$.setupState
const posts = <T extends {method: string}>(calls: T[]) => calls.filter(c => c.method === 'POST')

describe('Manual refresh', () => {
  it('shows the current and pending refreshes, and the check only once an ETL list is chosen', async () => {
    fakeApi(choices(WAITING))
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    expect(wrapper.find('#manual-current').text()).toContain('pahma-2026-10-10-1')
    expect(wrapper.find('#manual-current').text()).toContain('Serena serves from it')
    expect(wrapper.find('#manual-pending').text()).toContain('pahma-2026-10-12-1')
    expect(wrapper.find('#manual-pending').text()).toContain('ETL list received')
    expect(wrapper.find('#manual-check').exists()).toBe(false) // hidden, not disabled
    expect(wrapper.find('#manual-lists').exists()).toBe(false)
    setup(wrapper).source = 'etl'
    await flushPromises()
    expect(wrapper.find('#manual-chosen').text()).toContain('none yet')
    expect(wrapper.find('#manual-check').exists()).toBe(false)
    await wrapper.find('#pick-pahma-2026-10-10-1').setValue(true)
    expect(wrapper.find('#manual-chosen').text()).toContain('the one for 2026-10-10, 41 rows')
    expect(wrapper.find('#manual-check').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('checks a previous ETL list with a dry run, then applies it after confirming the older list and the stop', async () => {
    const calls = fakeApi({...choices(WAITING),
      'POST /museums/pahma/servable-lists/pahma-2026-10-10-1/dry-run': {body: PASSED},
      'POST /museums/pahma/refreshes/from-list': {status: 201, body: STARTED}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-10-1').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(posts(calls).map(c => c.path)).toEqual(['/museums/pahma/servable-lists/pahma-2026-10-10-1/dry-run'])
    expect(wrapper.find('#manual-dry-head').text()).toBe('The dry run passed')
    expect(wrapper.find('#manual-dry').text()).toContain('against the last ETL list update (pahma-2026-10-10-1). Nothing has changed.')
    expect(wrapper.find('#manual-counts').text()).toContain('41 rows; 1 added')
    expect(wrapper.find('#manual-older').text()).toContain('1 day older than the newest (2026-10-11)') // MR6
    expect(wrapper.find('#manual-open').text()).toContain('Applying your ETL list stops it') // rule D
    // Apply needs a reason: pressed without one, it says so and sends nothing.
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Give a reason first.')
    expect(posts(calls)).toHaveLength(1)
    setup(wrapper).reason = 'tonight failed'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    const dialog = document.querySelector('#manual-confirm-dialog')?.textContent || ''
    expect(dialog).toContain('Stop pahma-2026-10-12-1 and apply this ETL list?')
    expect(dialog).toContain('The ETL list for 2026-10-10 isn\'t the newest')
    expect(posts(calls)).toHaveLength(1) // asked first
    ;(document.querySelector('#manual-confirm') as HTMLButtonElement).click()
    await flushPromises()
    expect(posts(calls).at(-1)?.body).toEqual({refresh_id: 'pahma-2026-10-10-1', reason: 'tonight failed',
      open_refresh: 'pahma-2026-10-12-1', kind: ''})
    const summary = wrapper.find('#manual-applied').text()
    expect(summary).toContain('Applied: pahma-2026-10-12-2 started')
    expect(summary).toContain('with the ETL list for 2026-10-10, from pahma-2026-10-10-1. Reason: tonight failed.')
    expect(wrapper.find('#manual-replaced').text()).toContain('pahma-2026-10-12-1, which is now Abandoned')
    expect(summary).toContain('Follow it on Past refreshes or Overview')
    await wrapper.find('#manual-again').trigger('click')
    expect(wrapper.find('#manual-applied').exists()).toBe(false)
    expect(setup(wrapper).source).toBe('')
    wrapper.unmount()
  })

  it('drops the dry run\'s result when another ETL list is chosen', async () => {
    fakeApi({...choices(), 'POST /museums/pahma/servable-lists/pahma-2026-10-10-1/dry-run': {body: PASSED}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-10-1').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#manual-dry').exists()).toBe(true)
    setup(wrapper).pickerOpen = 'picker'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-11-1').setValue(true)
    expect(wrapper.find('#manual-dry').exists()).toBe(false)
    expect(wrapper.find('#manual-check').exists()).toBe(true)
    wrapper.unmount()
  })

  it('uploads a file for the dry run, and again with Apply, with the upload\'s fields', async () => {
    const answers: Answers = {...choices(),
      'POST /museums/pahma/servable-lists/dry-run': {body: PASSED},
      'POST /museums/pahma/refreshes': {status: 201, body: {...STARTED, admin_refresh_date: '2026-10-09'}}}
    const calls: {method: string, path: string, headers: Record<string, string>, body: unknown}[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method || 'GET', path = url.replace('/admin/v1', '')
      calls.push({method, path, headers: (init.headers || {}) as Record<string, string>, body: init.body})
      const answer = answers[`${method} ${path}`] || {status: 404, body: {detail: 'Not Found'}}
      return new Response(JSON.stringify(answer.body), {status: answer.status || 200})
    }))
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    const state = setup(wrapper)
    state.source = 'upload'
    await flushPromises()
    expect(state.refreshDate).toBe(pacificDate()) // today, to start (D75)
    const file = new File(['blob_csid\tmedia_csid\tkind\taccess\n'], 'servable-list.pahma.2026-10-09.tsv')
    Object.assign(state, {file, refreshDate: '2026-10-09'})
    await flushPromises()
    expect(wrapper.find('#manual-chosen').text()).toContain('an uploaded file, servable-list.pahma.2026-10-09.tsv')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(posts(calls)[0].path).toBe('/museums/pahma/servable-lists/dry-run')
    expect(posts(calls)[0].body).toBe(file)
    state.reason = 'ETL log checked: café'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Confirm the ETL list was made from the live public core.')
    expect(posts(calls)).toHaveLength(1)
    state.confirmed = true
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    const post = posts(calls)[1]
    expect(post.path).toBe('/museums/pahma/refreshes')
    expect(post.body).toBe(file) // sent again: nothing was stored in between
    expect(post.headers).toMatchObject({'X-Live-Core-Confirmed': 'yes', 'X-Refresh-Date': '2026-10-09',
      'X-File-Name': 'servable-list.pahma.2026-10-09.tsv', 'X-Reason': 'ETL%20log%20checked%3A%20caf%C3%A9',
      'X-Open-Refresh': '', 'X-Override-Kind': ''})
    expect(wrapper.find('#manual-applied').text()).toContain('the uploaded file servable-list.pahma.2026-10-09.tsv')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('offers Apply with override after a dry run that failed only on the delta threshold', async () => {
    const calls = fakeApi({...choices(), 'POST /museums/pahma/servable-lists/pahma-2026-10-11-1/dry-run': {body: DELTA},
      'POST /museums/pahma/refreshes/from-list': {status: 201, body: STARTED}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-11-1').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#manual-dry-head').text()).toBe('The dry run failed only on the delta threshold')
    expect(wrapper.find('#manual-far-past').text()).toContain('Check that the file is the right one before you override.')
    expect(wrapper.find('#manual-apply').text()).toBe('Apply with override')
    setup(wrapper).reason = 'PAHMA republished half its images'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Choose why the change is expected.')
    expect(posts(calls)).toHaveLength(1) // only the dry run
    ;(document.querySelector('#override-kind-bulk_change') as HTMLInputElement).click()
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(posts(calls).at(-1)?.body).toEqual({refresh_id: 'pahma-2026-10-11-1', reason: 'PAHMA republished half its images',
      open_refresh: '', kind: 'bulk_change'})
    expect(wrapper.find('#manual-applied').text()).toContain('Known bulk change in CollectionSpace')
    expect(wrapper.find('#manual-applied').text()).toContain('the delta threshold is overridden for it')
    wrapper.unmount()
  })

  it('lists other problems, which can\'t be overridden, and Cancel goes back to the choice', async () => {
    fakeApi({...choices(), 'POST /museums/pahma/servable-lists/pahma-2026-10-11-1/dry-run': {body: OTHER}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-11-1').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#manual-dry-head').text()).toBe('The dry run found 3 problems')
    expect(wrapper.find('#manual-problems').text()).toContain('isn\'t a kind Serena serves')
    expect(wrapper.find('#manual-apply').exists()).toBe(false)
    await wrapper.find('#manual-cancel').trigger('click')
    expect(setup(wrapper).source).toBe('')
    expect(wrapper.find('#manual-dry').exists()).toBe(false)
    wrapper.unmount()
  })

  it('says to wait while the pending refresh is being checked, and sends nothing', async () => {
    const busy = {...WAITING, state: 'checking'}
    const calls = fakeApi({...choices(busy), 'POST /museums/pahma/servable-lists/pahma-2026-10-10-1/dry-run': {body: PASSED}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-10-1').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#manual-open').text()).toContain('pahma-2026-10-12-1 is checking its ETL list')
    setup(wrapper).reason = 'now'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(wrapper.find('#manual-error').text()).toContain('wait for it to finish (a few minutes), then apply')
    expect(posts(calls)).toHaveLength(1) // only the dry run
    wrapper.unmount()
  })

  it('replaces a failed pending refresh without asking', async () => {
    const failed = {...WAITING, state: 'update_failed', actions: ['retry_update']}
    const calls = fakeApi({...choices(failed), 'POST /museums/pahma/servable-lists/pahma-2026-10-11-1/dry-run': {body: PASSED},
      'POST /museums/pahma/refreshes/from-list': {status: 201, body: STARTED}})
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    expect(wrapper.find('#manual-pending').text()).toContain('Pending refresh, needs an admin')
    expect(wrapper.find('#manual-partly').text()).toBe('partly replaced')
    setup(wrapper).source = 'etl'
    await flushPromises()
    await wrapper.find('#pick-pahma-2026-10-11-1').setValue(true) // the newest: no older-list warning either
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#manual-open').exists()).toBe(false)
    setup(wrapper).reason = 'the update keeps failing'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    expect(document.querySelector('#manual-confirm-dialog')).toBeNull()
    expect(posts(calls).at(-1)?.path).toBe('/museums/pahma/refreshes/from-list')
    expect(wrapper.find('#manual-replaced').text()).toContain('pahma-2026-10-12-1')
    wrapper.unmount()
  })

  it('makes an ETL list from the simulator, checks it and applies it, only where the simulator is every museum\'s', async () => {
    const made = {file_name: 'simulator-pahma-20261029T221005.tsv', rows: 2, records: 4, made_at: '2026-10-29T22:10:05+00:00',
      left_out: {'soft-deleted': 1, 'no file': 1}, tsv: 'blob_csid\tmedia_csid\tkind\taccess\n'}
    const answers: Answers = {...choices(),
      'GET /museums/pahma/simulator/servable-list': {body: made},
      'POST /museums/pahma/servable-lists/dry-run': {body: PASSED},
      'POST /museums/pahma/refreshes': {status: 201, body: STARTED}}
    const calls: {method: string, path: string, headers: Record<string, string>, body: unknown}[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method || 'GET', path = url.replace('/admin/v1', '')
      calls.push({method, path, headers: (init.headers || {}) as Record<string, string>, body: init.body})
      const answer = answers[`${method} ${path}`] || {status: 404, body: {detail: 'Not Found'}}
      return new Response(JSON.stringify(answer.body), {status: answer.status || 200})
    }))
    session.simulated = false
    const hidden = await at('/pahma/manual-refresh', ManualRefresh)
    expect(hidden.find('#source-simulator').exists()).toBe(false)
    hidden.unmount()
    session.simulated = true
    const wrapper = await at('/pahma/manual-refresh', ManualRefresh)
    expect(wrapper.find('#source-simulator').exists()).toBe(true)
    const state = setup(wrapper)
    state.source = 'simulator'
    await flushPromises()
    expect(wrapper.find('#manual-check-step').exists()).toBe(false) // nothing made yet
    await wrapper.find('#simulator-make').trigger('click')
    await flushPromises()
    expect(wrapper.find('#simulator-made').text()).toContain('2 rows from 4 records; not listed: 1 soft-deleted, 1 no file')
    expect(wrapper.find('#manual-chosen').text()).toContain('simulator-pahma-20261029T221005.tsv')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const dryRun = posts(calls)[0]
    expect(dryRun.path).toBe('/museums/pahma/servable-lists/dry-run')
    expect((dryRun.body as File).name).toBe(made.file_name)
    expect(wrapper.find('#confirm-live-core').exists()).toBe(false) // the simulator stands in for the live core
    state.reason = 'Testing a BMU upload'
    await flushPromises()
    await wrapper.find('#manual-apply').trigger('click')
    await flushPromises()
    const post = posts(calls)[1]
    expect(post.path).toBe('/museums/pahma/refreshes')
    expect((post.body as File).name).toBe(made.file_name)
    expect(post.headers).toMatchObject({'X-Live-Core-Confirmed': 'simulator', 'X-Refresh-Date': '',
      'X-File-Name': made.file_name})
    expect(wrapper.find('#manual-applied').text()).toContain(`the ETL list ${made.file_name}, made from the simulator`)
    wrapper.unmount()
    session.simulated = false
    vi.unstubAllGlobals()
  })
})

describe('a manual refresh on Past refreshes', () => {
  it('is tagged with where its ETL list came from', async () => {
    const manual = {...REFRESH, manual: true, admin_refresh_date: '2026-10-09', admin_refresh_from: 'pahma-2026-10-09-1'}
    fakeApi({'GET /museums/pahma/refreshes': {body: {days: 30, refreshes: [manual,
      {...manual, refresh_id: 'pahma-2026-10-10-2', admin_refresh_from: null, admin_refresh_date: '2026-10-10'},
      {...REFRESH, refresh_id: 'pahma-2026-10-09-1', refresh_date: '2026-10-09'}]}}})
    const list = await at('/pahma/refreshes', Refreshes)
    expect(list.findAll('.manual-tag').map(t => t.text())).toEqual(['manual refresh · ETL list for 2026-10-09',
      'manual refresh · uploaded list'])
    list.unmount()
  })
})
