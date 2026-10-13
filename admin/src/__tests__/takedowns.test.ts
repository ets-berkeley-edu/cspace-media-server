import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import LookUp from '@/views/LookUp.vue'
import Takedowns from '@/views/Takedowns.vue'

// Synthetic CSIDs only.
const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'
const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50'
const KEPT = {media_csid: MEDIA, blob_csids: [BLOB], by: 'admin', at: '2026-10-14T17:00:00+00:00', reason: 'a complaint',
  kept_by: 'pahma-2026-10-15-1', kept_on: '2026-10-15'}
const PAGE = {
  days: 30, max_in_box: 12, max_in_file: 1000, active: [KEPT],
  ended: [{media_csid: 'other-media', at: '2026-10-15T10:40:00Z', by: 'refresh pahma-2026-10-15-1',
    action: 'takedown_removed', details: {why: 'no longer listed as public'}}]
}
const SUMMARY = {
  records: [{media_csid: MEDIA, blob_csids: [BLOB], kind: 'image', served_today: true, taken_down: false,
    source: 'serena', entered: [BLOB]}],
  not_found: [{csid: 'typo', why: 'not_a_csid', message: 'Not a CSID.'}]
}

async function at(path: string, component: unknown) {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(path)
  const wrapper = mount(component as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  return wrapper
}

function type(selector: string, value: string) {
  const field = document.querySelector(selector) as HTMLInputElement | HTMLTextAreaElement
  field.value = value
  field.dispatchEvent(new Event('input'))
}

describe('the Takedowns page', () => {
  it('lists takedowns, and releases only one a refresh kept', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/takedowns': {body: PAGE},
      [`POST /museums/pahma/takedowns/${MEDIA}/release`]: {body: {released: MEDIA}}
    })
    const wrapper = await at('/pahma/takedowns', Takedowns)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA Takedowns')
    expect(wrapper.find('#active-takedowns').text()).toContain('Still public in CollectionSpace')
    expect(wrapper.find('#ended-takedowns').text()).toContain('Removed by a refresh')
    await wrapper.find('#active-takedowns .release').trigger('click')
    await flushPromises()
    const confirm = () => document.querySelector('#release-confirm') as HTMLButtonElement
    expect(confirm().disabled).toBe(true) // a reason first
    type('#release-reason', 'CollectionSpace is right')
    await flushPromises()
    confirm().click()
    await vi.waitFor(() => expect(calls.some(c => c.path.endsWith('/release'))).toBe(true))
    expect(calls.find(c => c.path.endsWith('/release'))?.body).toEqual({reason: 'CollectionSpace is right'})
    wrapper.unmount()
  })

  it('shows what would be taken down before it takes anything down', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/takedowns': {body: {...PAGE, active: []}},
      'POST /museums/pahma/takedowns/summary': {body: SUMMARY},
      'POST /museums/pahma/takedowns': {body: {...SUMMARY, taken_down: [MEDIA]}}
    })
    const wrapper = await at('/pahma/takedowns', Takedowns)
    await wrapper.find('#take-down').trigger('click')
    await flushPromises()
    type('#takedown-csids', Array.from({length: 13}, (_, n) => `csid-${n}`).join('\n'))
    await flushPromises();
    (document.querySelector('#takedown-summarize') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('More than 12 CSIDs: use a text file instead.'))
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
    type('#takedown-csids', `${BLOB}, typo`)
    await flushPromises();
    (document.querySelector('#takedown-summarize') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('#takedown-summary')).not.toBeNull())
    expect(document.querySelector('#takedown-summary')?.textContent).toContain(MEDIA)
    expect(document.querySelector('#takedown-not-found')?.textContent).toContain('typo: Not a CSID.')
    const thumbnail = document.querySelector('#takedown-summary img') as HTMLImageElement
    expect(thumbnail.getAttribute('src')).toBe(`/admin/v1/museums/pahma/media/${MEDIA}/preview?size=thumbnail`)
    const confirm = () => document.querySelector('#takedown-confirm') as HTMLButtonElement
    expect(confirm().textContent).toContain('Take down 1 Media record')
    expect(confirm().disabled).toBe(true)
    type('#takedown-reason', 'A complaint from a community')
    await flushPromises()
    confirm().click()
    await vi.waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/museums/pahma/takedowns')).toBe(true))
    expect(calls.find(c => c.path === '/museums/pahma/takedowns' && c.method === 'POST')?.body).toEqual(
      {text: `${BLOB}, typo`, reason: 'A complaint from a community'})
    wrapper.unmount()
  })
})

describe('Look up a file', () => {
  it('shows each step and the verdict for each size', async () => {
    const result = {
      input: MEDIA, refused: null, refresh: {refresh_id: 'pahma-2026-10-15-1', refresh_date: '2026-10-15'},
      items: [{blob_csid: BLOB, media_csid: MEDIA, kind: 'image', access: 'public',
        steps: [{check: 'In the servable list', outcome: 'Listed.', ok: true},
          {check: 'Takedown', outcome: 'Taken down by admin.', ok: false}],
        sizes: [{size: 'Medium', served: false, reason: 'taken_down', verdict: 'not served', stored: null}]}]
    }
    const calls = fakeApi({[`GET /museums/pahma/lookup?q=${MEDIA}`]: {body: result}})
    const wrapper = await at('/pahma/lookup', LookUp)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA: Look up a file')
    await wrapper.find('#lookup-input').setValue(MEDIA)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(calls.map(c => c.path)).toEqual([`/museums/pahma/lookup?q=${MEDIA}`])
    expect(wrapper.find('#lookup-refresh').text()).toContain('pahma-2026-10-15-1')
    expect(wrapper.find('.lookup-steps').text()).toContain('Taken down by admin.')
    expect(wrapper.find('.lookup-sizes').text()).toContain('taken down')
    wrapper.unmount()
  })
})
