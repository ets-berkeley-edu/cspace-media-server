import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import AuditLog from '@/views/AuditLog.vue'
import Refreshes from '@/views/Refreshes.vue'
import Settings from '@/views/Settings.vue'

const SETTINGS = {
  settings: [
    {name: 'delta_threshold_percent', group: 'check', label: 'Delta threshold (%)', value: 5, default: 5, changed: false,
      kind: 'number', min: 0.1, max: 100},
    {name: 'audit_retention_days', group: 'audit', label: 'How long the audit log is kept (days)', value: 90, default: 90,
      changed: false}
  ],
  audit_retention_choices: [{days: 90, entries_removed: 0}, {days: 183, entries_removed: 0}],
  placeholder: {blob_csid: '59a733dd-d641-4e1a-8552', identification_number: null}
}
const RECORD = '3c4d5e6f-7081-4a92-8b3c-4d5e6f708192' // synthetic
const PLACEHOLDER_SETTING = {name: 'placeholder_media_csid', group: 'placeholder', label: 'Placeholder image (Media CSID)',
  value: null, default: null, changed: false}

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

describe('the placeholder image\'s Media record (October 14, 2026, D166 to D172)', () => {
  it('shows the generic picture until one is named, says why a record won\'t do, and warns about another Blob', async () => {
    const page = {...SETTINGS, settings: [...SETTINGS.settings, PLACEHOLDER_SETTING]}
    const saved = {...page, settings: [...SETTINGS.settings, {...PLACEHOLDER_SETTING, value: RECORD, changed: true}],
      placeholder: {blob_csid: '59a733dd-d641-4e1a-8552', identification_number: 'P-1'},
      warning: 'This Media record\'s Blob (x) isn\'t the one the ETL lists for the placeholder image (y).'}
    const answers: Record<string, {status?: number, body: unknown}> = {
      'GET /museums/pahma/settings': {body: page},
      'PUT /museums/pahma/settings/placeholder_media_csid': {status: 422, body: {detail: 'CollectionSpace has no Media record with this CSID.'}}
    }
    const calls = fakeApi(answers)
    const wrapper = await at('/pahma/settings', Settings)
    expect(wrapper.find('#setting-placeholder_media_csid').text()).toContain('none: the generic picture')
    expect(wrapper.find('#placeholder-help').text()).toContain('generic "Image restricted" picture')
    await wrapper.find('#setting-placeholder_media_csid .change').trigger('click')
    await flushPromises()
    const field = document.querySelector('#setting-value') as HTMLInputElement
    expect(field.value).toBe('') // not "null"
    field.value = RECORD
    field.dispatchEvent(new Event('input'))
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'PAHMA\'s own picture'
    reason.dispatchEvent(new Event('input'))
    await flushPromises();
    (document.querySelector('#save-setting') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('CollectionSpace has no Media record with this CSID.'))
    expect(document.querySelector('#save-setting')).not.toBeNull() // the dialog stays open
    answers['PUT /museums/pahma/settings/placeholder_media_csid'] = {body: saved};
    (document.querySelector('#save-setting') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(wrapper.find('#settings-warning').exists()).toBe(true))
    expect(calls.filter(c => c.method === 'PUT').map(c => c.body)).toEqual(
      [{value: RECORD, reason: 'PAHMA\'s own picture'}, {value: RECORD, reason: 'PAHMA\'s own picture'}])
    expect(wrapper.find('#setting-placeholder_media_csid').text()).toContain('Media P-1')
    expect(wrapper.find('#placeholder-thumbnail').attributes('src')).toBe(`/admin/v1/museums/pahma/media/${RECORD}/preview?size=thumbnail`)
    wrapper.unmount()
  })
})

describe('the Settings page', () => {
  it('changes a setting only with a reason, and shows the default value', async () => {
    const changed = {...SETTINGS, settings: [{...SETTINGS.settings[0], value: 12.5, changed: true}, SETTINGS.settings[1]]}
    const calls = fakeApi({
      'GET /museums/pahma/settings': {body: SETTINGS},
      'PUT /museums/pahma/settings/delta_threshold_percent': {body: changed}
    })
    const wrapper = await at('/pahma/settings', Settings)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA Settings')
    expect(wrapper.find('#setting-delta_threshold_percent').text()).toContain('default value')
    await wrapper.find('#setting-delta_threshold_percent .change').trigger('click')
    await flushPromises()
    const save = () => document.querySelector('#save-setting') as HTMLButtonElement
    const field = document.querySelector('#setting-value') as HTMLInputElement
    field.value = '12.5'
    field.dispatchEvent(new Event('input'))
    await flushPromises()
    // Never disabled (October 14, 2026): without a reason it sends nothing and says why, with focus on the field.
    expect(save().disabled).toBe(false)
    save().click()
    await flushPromises()
    expect(document.body.textContent).toContain('Give a reason first.')
    expect(document.activeElement?.id).toBe('reason')
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(0)
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'PAHMA republishes its images this week'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    save().click()
    await vi.waitFor(() => expect(wrapper.find('#setting-delta_threshold_percent').text()).toContain('changed; default value 5'))
    const put = calls.find(c => c.method === 'PUT')
    expect(put?.body).toEqual({value: '12.5', reason: 'PAHMA republishes its images this week'})
    expect(put?.headers['X-Serena-Admin']).toBe('1')
    expect(wrapper.find('#setting-delta_threshold_percent .reset').text()).toBe('Use default')
    wrapper.unmount()
  })
})

describe('checking a value on Save (October 20, 2026, D219 to D221)', () => {
  const POLL = {name: 'etl_poll_interval_seconds', group: 'etl', label: 'ETL poll interval (seconds)', value: 15,
    default: 15, changed: false, kind: 'whole', min: 5, max: 300}
  const DEADLINE = {name: 'watchdog_deadline', group: 'watchdog', label: 'Deadline for today\'s refresh (HH:MM, Pacific)',
    value: '08:00', default: '08:00', changed: false, kind: 'time', min: null, max: null}
  const SIZE = {name: 'size_limit_mb.pdf', group: 'size_limits', label: 'Largest PDF file fetched (MB)', value: 200,
    default: 200, changed: false, kind: 'whole', min: 1, max: 2048}

  async function dialogFor(wrapper: ReturnType<typeof mount>, name: string, value: string) {
    await wrapper.find(`#setting-${name.replace('.', '-')} .change`).trigger('click')
    await flushPromises()
    const field = document.querySelector('#setting-value') as HTMLInputElement
    field.value = value
    field.dispatchEvent(new Event('input'))
    const reason = document.querySelector('#reason') as HTMLTextAreaElement
    reason.value = 'A test'
    reason.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.querySelector('#save-setting') as HTMLButtonElement).click()
    await flushPromises()
  }
  const closeDialog = async () => {
    (document.querySelector('.v-dialog .v-card-actions .v-btn--variant-outlined') as HTMLButtonElement).click()
    await flushPromises()
  }

  it('says what a value must be, under the field, sends nothing and keeps the dialog open', async () => {
    const page = {...SETTINGS, settings: [DEADLINE, POLL, ...SETTINGS.settings, SIZE]}
    const calls = fakeApi({'GET /museums/pahma/settings': {body: page}})
    const wrapper = await at('/pahma/settings', Settings)
    const cases: [string, string, string][] = [
      ['delta_threshold_percent', '5d', 'Give a number from 0.1 to 100.'],
      ['delta_threshold_percent', '0.05', 'Give a number from 0.1 to 100.'],
      ['etl_poll_interval_seconds', '12.5', 'Give a whole number from 5 to 300.'],
      ['etl_poll_interval_seconds', '301', 'Give a whole number from 5 to 300.'],
      ['size_limit_mb.pdf', '4096', 'Give a whole number from 1 to 2,048.'],
      ['watchdog_deadline', '8am', 'Give a time as HH:MM, from 00:00 to 23:59.']
    ]
    for (const [name, value, problem] of cases) {
      await dialogFor(wrapper, name, value)
      expect(document.querySelector('.v-dialog')?.textContent, `${name} ${value}`).toContain(problem)
      expect(document.activeElement?.id).toBe('setting-value')
      await closeDialog()
    }
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(0)
    expect(wrapper.find('#settings-error').exists()).toBe(false)
    // The hint is the range Serena sent.
    await wrapper.find('#setting-size_limit_mb-pdf .change').trigger('click')
    await flushPromises()
    expect(document.querySelector('.v-dialog')?.textContent).toContain('1 to 2,048')
    wrapper.unmount()
  })

  it('shows a value Serena refuses under the field too, the dialog open (D220)', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/settings': {body: SETTINGS},
      'PUT /museums/pahma/settings/delta_threshold_percent': {status: 422,
        body: {detail: 'Delta threshold (%): give a number from 0.1 to 100.'}}
    })
    const wrapper = await at('/pahma/settings', Settings)
    await dialogFor(wrapper, 'delta_threshold_percent', '12.5')
    await vi.waitFor(() => expect(document.querySelector('.v-dialog')?.textContent).toContain('Give a number from 0.1 to 100.'))
    expect(document.querySelector('#save-setting')).not.toBeNull()
    expect(wrapper.find('#settings-error').exists()).toBe(false)
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('the tables', () => {
  it('sort and page the last 30 days', async () => {
    const refreshes = Array.from({length: 30}, (_, i) => ({
      refresh_id: `pahma-2026-10-${String(i + 1).padStart(2, '0')}-1`, refresh_date: `2026-10-${String(i + 1).padStart(2, '0')}`,
      state: 'updated', created_at: '', updated_at: `2026-10-${String(i + 1).padStart(2, '0')}T11:00:00+00:00`,
      rows: 100 - i, reasons: [], admin_refresh_date: null
    }))
    fakeApi({'GET /museums/pahma/refreshes': {body: {days: 30, refreshes}}})
    const wrapper = await at('/pahma/refreshes', Refreshes)
    const ids = () => wrapper.findAll('#refreshes-table tbody tr').map(row => row.find('td').text())
    expect(ids()).toHaveLength(25) // a page
    expect(ids()[0]).toBe('pahma-2026-10-30-1') // newest first
    const rows = wrapper.findAll('#refreshes-table thead th').find(th => th.text().startsWith('Rows'))
    await rows?.trigger('click') // ascending: the fewest rows first, across all 30
    await flushPromises()
    expect(ids()[0]).toBe('pahma-2026-10-30-1')
    await rows?.trigger('click') // descending
    await flushPromises()
    expect(ids()[0]).toBe('pahma-2026-10-01-1')
    await rows?.trigger('click') // ascending again: never unsorted
    await flushPromises()
    expect(ids()[0]).toBe('pahma-2026-10-30-1')
    wrapper.unmount()
  })

  it('offers the audit log as CSV', async () => {
    fakeApi({'GET /museums/pahma/audit': {body: {days: 30, entries: []}}})
    const wrapper = await at('/pahma/audit', AuditLog)
    expect(wrapper.find('#export-audit').attributes('href')).toBe('/admin/v1/museums/pahma/audit/export.csv')
    expect(wrapper.text()).toContain('Nothing recorded in the last 30 days.')
    wrapper.unmount()
  })
})
