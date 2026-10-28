import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {KeepAlive, defineComponent, h, ref} from 'vue'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import AlertBanner from '@/components/AlertBanner.vue'
import Overview from '@/views/Overview.vue'
import RefreshDetail from '@/views/RefreshDetail.vue'
import Refreshes from '@/views/Refreshes.vue'
import {session, waiting} from '@/session'
import {pacificDate} from '@/words'

const REFRESH = {
  refresh_id: 'pahma-2026-10-10-1', refresh_date: '2026-10-10', state: 'update_failed', created_at: '2026-10-10T10:00:00+00:00',
  updated_at: '2026-10-10T10:05:00+00:00', rows: 40, reasons: ['ETL list update failed after 3 attempts'], newest: true,
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
  it('retries an ETL list update only with a reason', async () => {
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
    await vi.waitFor(() => expect(wrapper.find('#refresh-state').text()).toBe('Applying the ETL list'))
    const post = calls.find(c => c.method === 'POST')
    expect(post?.body).toEqual({reason: 'DynamoDB is back'})
    expect(post?.headers['X-Serena-Admin']).toBe('1')
    wrapper.unmount()
  })
})

describe('a refresh\'s reasons (issue #120)', () => {
  it('puts each reason in the list Serena says, and says "None." for an empty one', async () => {
    const closed = {...REFRESH, state: 'abandoned', actions: [], reasons: [
      'manual refresh with the ETL list servable-list.tsv: the ETL\'s list didn\'t arrive',
      'a later refresh started before the ETL list update ran'], reason_kinds: ['admin', 'problem']}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: closed}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.text()).not.toContain('Reasons')
    expect(wrapper.find('#refresh-problems').text()).toBe('a later refresh started before the ETL list update ran')
    expect(wrapper.find('#refresh-admin-actions').text()).toContain('the ETL\'s list didn\'t arrive')
    wrapper.unmount()

    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...REFRESH, reasons: [], reason_kinds: []}}})
    const empty = (await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)).wrapper
    expect(empty.find('#refresh-problems-none').text()).toBe('None.')
    expect(empty.find('#refresh-admin-actions-none').text()).toBe('None.')
    empty.unmount()
  })

  it('counts a reason without a kind as what went wrong, never guessing from its words', async () => {
    const before = {...REFRESH, reasons: ['ETL list update retried by an admin: fixed', 'ETL list update failed']}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: before}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.findAll('#refresh-problems li')).toHaveLength(2)
    expect(wrapper.find('#refresh-admin-actions-none').exists()).toBe(true)
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
    // Issue #120: why the change is expected, then at least 20 characters; the button stays enabled and says what's
    // missing, with focus on the first thing missing.
    const confirm = () => (document.querySelector('#confirm-action') as HTMLButtonElement).click()
    const dialogText = () => document.querySelector('.v-dialog')?.textContent || ''
    expect(dialogText()).toContain('Why is the change expected? (required)')
    expect(dialogText()).toContain('Required, at least 20 characters: what changed, and how you know it\'s expected.')
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'many   images'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    confirm()
    await flushPromises()
    expect(dialogText()).toContain('Choose why the change is expected.')
    expect(dialogText()).toContain('Say a little more: at least 20 characters (11 so far).')
    expect(document.activeElement?.id).toBe('override-kind-first_load')
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
    ;(document.querySelector('#override-kind-bulk_change') as HTMLInputElement).click()
    reason.value = 'PAHMA republished many images'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    expect(dialogText()).not.toContain('Choose why the change is expected.')
    expect(dialogText()).not.toContain('Say a little more')
    confirm()
    await vi.waitFor(() => expect(wrapper.find('#refresh-state').text()).toBe('Checking the ETL list'))
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({kind: 'bulk_change', reason: 'PAHMA republished many images'})
    expect(wrapper.find('#override-threshold').exists()).toBe(false)
    wrapper.unmount()
  })
})

// Issue #108: an override says who, when and why, marks the check it answered, and the page checks again while
// Serena works.
const THRESHOLD = '50% of the rows would change; the threshold is 5.0%'
const FAILED_CHECK = {result: 'failed', rows: 40, added: 0, removed: 20, changed: 0, previous_rows: 40, threshold_percent: 5,
  delta_percent: 50, error_count: 1, errors: [{line: 0, field: 'file', problem: THRESHOLD}], warnings: []}
const OVERRIDE = {at: '2026-10-10T16:00:00+00:00', by: 'pahma-admin', kind: 'bulk_change', reason: 'PAHMA republished many images'}
const OVERRIDDEN = {...REFRESH, state: 'checking', actions: [], check: FAILED_CHECK, override: OVERRIDE,
  reasons: ['1 problem in the ETL list',
    'delta threshold overridden by an admin: Known bulk change in CollectionSpace: PAHMA republished many images'],
  reason_kinds: ['problem', 'override']}

// Issue #120: past the delta threshold, the percent is in red and says how many times the threshold it is; from 10 times,
// a note says it's far past it.
const PAST_CHECK = {...FAILED_CHECK, rows: 500, added: 0, removed: 19, previous_rows: 500, delta_percent: 3.8,
  errors: [{line: 0, field: 'file', problem: '3.8% of the rows would change; the threshold is 5.0%'}]}
const FAR_CHECK = {...FAILED_CHECK, rows: 10678, added: 10641, removed: 0, previous_rows: 37, delta_percent: 28756.76,
  errors: [{line: 0, field: 'file', problem: '28756.76% of the rows would change; the threshold is 5.0%'}]}
const FAILED = {...REFRESH, state: 'check_failed', actions: ['override_threshold']}

describe('how far past the delta threshold', () => {
  it('says how many times the threshold a check is, without a note below 10 times', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...FAILED, check: {...PAST_CHECK, delta_percent: 19}}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#check-counts').text()).toBe('500 rows; 0 added, 19 removed, 0 changed (19% of the 500 rows of the ' +
      'last ETL list update; 3.8 times the 5% threshold).')
    expect(wrapper.find('#check-counts .delta-over').text()).toBe('19%')
    expect(wrapper.find('#check-far-past').exists()).toBe(false)
    await wrapper.find('#override-threshold').trigger('click')
    await flushPromises()
    expect(document.querySelector('#override-explanation')?.textContent).toContain('this list changes 19% of the rows, ' +
      '3.8 times the 5% threshold. Do this once')
    expect(document.querySelector('#override-far-past')).toBeNull()
    wrapper.unmount()
  })

  it('from 10 times, says under the check and in the dialog that it\'s far past it', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...FAILED, check: FAR_CHECK}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#check-counts').text()).toContain('5,751 times the 5% threshold')
    const note = 'Far past the delta threshold. 28756.76% is 5,751 times the threshold: the last ETL list update had ' +
      '37 rows, this list has 10678. A change this large is usually a first load or the wrong file. Check that the file ' +
      'is the right one before you override.'
    expect(wrapper.find('#check-far-past').text()).toBe(note)
    await wrapper.find('#override-threshold').trigger('click')
    await flushPromises()
    expect(document.querySelector('#override-explanation')?.textContent).toContain('5,751 times the 5% threshold: far past it.')
    expect(document.querySelector('#override-far-past')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(note)
    wrapper.unmount()
  })

  it('leaves out the advice to check the file where it can\'t be overridden', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...FAILED, actions: [], newest: false, check: FAR_CHECK}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#check-far-past').text()).toContain('usually a first load or the wrong file.')
    expect(wrapper.find('#check-far-past').text()).not.toContain('before you override')
    wrapper.unmount()
  })

  it('says nothing more within the threshold, or with nothing to compare with', async () => {
    const within = {...PAST_CHECK, result: 'passed', delta_percent: 3.8, error_count: 0, errors: []}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...REFRESH, state: 'updated', actions: [], check: within}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#check-counts').text()).toContain('(3.8% of the 500 rows of the last ETL list update; the threshold is 5%)')
    expect(wrapper.find('#check-counts .delta-over').exists()).toBe(false)
    wrapper.unmount()
    const first = {...within, previous_rows: null, delta_percent: null}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...REFRESH, state: 'updated', actions: [], check: first}}})
    const again = (await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)).wrapper
    expect(again.find('#check-counts').text()).toBe('500 rows; 0 added, 19 removed, 0 changed.')
    expect(again.find('#check-far-past').exists()).toBe(false)
    again.unmount()
  })
})

describe('an overridden refresh', () => {
  it('says who overrode it, when and why, and marks the check it answered', async () => {
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: OVERRIDDEN}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    const banner = wrapper.find('#override-banner')
    // Issue #110: it leads with the check that failed and by how much.
    expect(wrapper.find('#override-lead').text()).toBe('A safety check failed, and an admin overrode it')
    // Issue #120: in red, with how many times the threshold it is.
    expect(wrapper.find('#override-overshoot').text()).toBe('The ETL list changes 50% of the rows, 10.0 times the 5% threshold: far past it.')
    expect(wrapper.find('#override-overshoot .delta-over').text()).toBe('50%')
    expect(wrapper.find('#check-far-past').exists()).toBe(false) // the banner says it
    expect(banner.text()).toContain('Delta threshold overridden by pahma-admin at 2026-10-10 16:00:00 UTC.')
    expect(wrapper.find('#override-reason').text()).toBe('Reason: Known bulk change in CollectionSpace: PAHMA republished many images')
    expect(banner.text()).toContain('This page checks again every few seconds')
    // Issue #120: the reasons in two lists, as Serena records them; the override's reason is in the banner, and its
    // line under What admins did says who and when.
    expect(wrapper.find('#refresh-problems').text()).toBe('1 problem in the ETL list')
    expect(wrapper.find('#refresh-admin-actions').text()).toBe('Delta threshold overridden by pahma-admin at ' +
      '2026-10-10 16:00:00 UTC; its reason is in the banner above.')
    expect(wrapper.find('#check-heading').text()).toContain('ETL list check: failed, overridden by admin')
    expect(wrapper.find('#check-overridden').exists()).toBe(false) // the heading says it already
    expect(wrapper.find('#refresh-state').text()).toBe('Checking the ETL list')
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
      expect(wrapper.find('#check-heading').text()).toContain('ETL list check: failed, overridden by admin')
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
    expect(wrapper.find('#check-heading').text()).toContain('ETL list check: failed')
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

  it('gives the reason alone for an override made before it had a kind (issue #120)', async () => {
    const before = {...OVERRIDE, kind: undefined}
    fakeApi({'GET /museums/pahma/refreshes/pahma-2026-10-10-1': {body: {...OVERRIDDEN, state: 'updated', override: before,
      reasons: ['delta threshold overridden by an admin: PAHMA republished many images']}}})
    const {wrapper} = await at('/pahma/refreshes/pahma-2026-10-10-1', RefreshDetail)
    expect(wrapper.find('#override-reason').text()).toBe('Reason: PAHMA republished many images')
    // No kinds from before issue #120: its override's own line is still the override's, under What admins did.
    expect(wrapper.find('#refresh-problems-none').text()).toBe('None.')
    expect(wrapper.find('#refresh-admin-actions').text()).toContain('its reason is in the banner above.')
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

  it('shows only the overridden ones, from the address too, and All from the menu (issue #120)', async () => {
    const row = (n: number, override: unknown) => ({...REFRESH, refresh_id: `pahma-2026-10-1${n}-1`,
      refresh_date: `2026-10-1${n}`, state: 'updated', updated_at: `2026-10-1${n}T11:00:00+00:00`, admin_refresh_date: null, override})
    const list = {body: {days: 30, refreshes: [row(3, null), row(2, OVERRIDE), row(1, null)]}}
    fakeApi({'GET /museums/pahma/refreshes': list})
    const {wrapper, router} = await at('/pahma/refreshes', Refreshes)
    const ids = () => wrapper.findAll('#refreshes-table tbody tr').map(r => r.find('a').text())
    expect(ids()).toHaveLength(3)
    expect(wrapper.find('#refreshes-show-all').classes()).toContain('v-btn--active')
    expect(wrapper.find('#refreshes-show-overridden').text()).toBe('Overridden (1)')
    await wrapper.find('#refreshes-show-overridden').trigger('click')
    await flushPromises()
    expect(ids()).toEqual(['pahma-2026-10-12-1'])
    await vi.waitFor(() => expect(router.currentRoute.value.query.show).toBe('overridden'))
    // The menu's link has no show=, so the page, kept alive, goes back to All.
    await router.push('/pahma/refreshes')
    await flushPromises()
    expect(ids()).toHaveLength(3)
    wrapper.unmount()

    fakeApi({'GET /museums/pahma/refreshes': list})
    const shared = await at('/pahma/refreshes?show=overridden', Refreshes)
    expect(shared.wrapper.findAll('#refreshes-table tbody tr')).toHaveLength(1)
    shared.wrapper.unmount()

    fakeApi({'GET /museums/pahma/refreshes': {body: {days: 30, refreshes: [row(3, null)]}}})
    const none = await at('/pahma/refreshes?show=overridden', Refreshes)
    expect(none.wrapper.find('#refreshes-show-overridden').text()).toBe('Overridden (0)')
    expect(none.wrapper.find('#refreshes-table').text()).toContain('No overridden refreshes in the last 30 days.')
    none.wrapper.unmount()
  })
})

describe('the alert banner', () => {
  it('shows one line while alerts wait, newest first, with a way to the Alerts page', async () => {
    const alert = {key: '2026-10-10#missed_deadline#2026-10-10', refresh_date: '2026-10-10', kind: 'missed_deadline',
      title: 'Today\'s refresh isn\'t finished by the deadline', subject: '2026-10-10', message: 'Not updated by 08:00',
      created_at: '2026-10-10T15:00:00+00:00', acknowledged_by: null, acknowledged_at: null}
    const newer = {...alert, key: 'newer', title: 'An ETL list check failed', created_at: '2026-10-10T16:00:00+00:00'}
    const calls = fakeApi({
      'GET /museums/pahma/alerts': {body: {alerts: [alert, newer, {...alert, key: 'old', acknowledged_at: 'x', acknowledged_by: 'admin'}]}}
    })
    const {wrapper} = await at('/pahma', AlertBanner)
    expect(wrapper.find('#alert-banner').text()).toContain('2 alerts:')
    expect(wrapper.find('#alert-banner-title').text()).toBe('An ETL list check failed')
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
    expect(failed.text()).toBe('ETL list check failed') // the label alone is read out
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
    expect(wrapper.find('#refresh-state').text()).toBe('ETL list update failed')
    expect(wrapper.find('#refresh-state').classes()).toContain('text-error')
    expect(wrapper.find('#refresh-state .refresh-state-icon').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('Past refreshes and Overview, while a refresh is working', () => {
  const row = (state: string) => ({...REFRESH, state, actions: [], admin_refresh_date: null})
  const list = (state: string) => ({body: {days: 30, refreshes: [row(state)]}})

  it('Past refreshes loads again by itself, in the background, until none is checking or updating', async () => {
    vi.useFakeTimers()
    try {
      const answers = {'GET /museums/pahma/refreshes': list('checking')}
      const calls = fakeApi(answers)
      const {wrapper} = await at('/pahma/refreshes', Refreshes)
      expect(wrapper.find('#refreshes-table tbody .refresh-state').text()).toBe('Checking the ETL list')
      expect(calls[0].headers['X-Serena-Background']).toBeUndefined() // opening the page is activity
      answers['GET /museums/pahma/refreshes'] = list('updated')
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(calls).toHaveLength(2)
      expect(calls[1].headers['X-Serena-Background']).toBe('1') // not activity: an idle tab still signs out
      expect(wrapper.find('#refreshes-table tbody .refresh-state').text()).toBe('Updated')
      await vi.advanceTimersByTimeAsync(15000)
      expect(calls).toHaveLength(2) // done: no more loads
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('Past refreshes doesn\'t load again when nothing is working', async () => {
    vi.useFakeTimers()
    try {
      const calls = fakeApi({'GET /museums/pahma/refreshes': list('check_failed')})
      const {wrapper} = await at('/pahma/refreshes', Refreshes)
      await vi.advanceTimersByTimeAsync(15000)
      expect(calls).toHaveLength(1)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('Past refreshes stops while another page is shown, and starts again on coming back', async () => {
    vi.useFakeTimers()
    try {
      const calls = fakeApi({'GET /museums/pahma/refreshes': list('updating')})
      const router = createRouter({history: createMemoryHistory('/admin/'), routes})
      await router.push('/pahma/refreshes')
      const shown = ref(true)
      // As App.vue does: the page is kept alive while another is shown.
      const Host = defineComponent({setup: () => () => h(KeepAlive, null, {default: () => shown.value ? h(Refreshes) : h('div')})})
      const wrapper = mount(Host, {global: {plugins: [router]}, attachTo: document.body})
      await flushPromises()
      expect(calls).toHaveLength(1)
      shown.value = false
      await flushPromises()
      await vi.advanceTimersByTimeAsync(15000)
      expect(calls).toHaveLength(1) // away: no loads
      shown.value = true
      await flushPromises()
      expect(calls).toHaveLength(2) // coming back loads again, as it always has
      expect(calls[1].headers['X-Serena-Background']).toBeUndefined()
      await vi.advanceTimersByTimeAsync(5000)
      expect(calls).toHaveLength(3) // and, still working, checks again in the background
      expect(calls[2].headers['X-Serena-Background']).toBe('1')
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('Overview loads again by itself while its newest refresh is working', async () => {
    vi.useFakeTimers()
    try {
      session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]
      const checking = row('checking')
      const answers = {'GET /museums/pahma/status': {body: {newest: checking, current: null, pending: checking, unacknowledged: 0} as unknown}}
      const calls = fakeApi(answers)
      const {wrapper} = await at('/pahma', Overview)
      expect(wrapper.find('#pending-refresh-state').text()).toBe('Checking the ETL list')
      const updated = row('updated')
      answers['GET /museums/pahma/status'] = {body: {newest: updated, current: updated, pending: null, unacknowledged: 0}}
      await vi.advanceTimersByTimeAsync(5000)
      await flushPromises()
      expect(calls).toHaveLength(2)
      expect(calls[1].headers['X-Serena-Background']).toBe('1')
      expect(wrapper.find('#current-refresh-state').text()).toBe('Updated')
      expect(wrapper.find('#pending-none').text()).toBe('None')
      await vi.advanceTimersByTimeAsync(15000)
      expect(calls).toHaveLength(2)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
