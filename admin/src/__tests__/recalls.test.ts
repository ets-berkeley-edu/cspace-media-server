import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import LookUp from '@/views/LookUp.vue'
import Recalls from '@/views/Recalls.vue'

// Synthetic CSIDs only.
const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'
const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50'
const KEPT = {media_csid: MEDIA, blob_csids: [BLOB], by: 'admin', at: '2026-10-14T17:00:00+00:00', reason: 'a complaint',
  kept_by: 'pahma-2026-10-15-1', kept_on: '2026-10-15'}
const PAGE = {
  days: 30, max_in_box: 12, max_in_file: 1000, active: [KEPT],
  ended: [{media_csid: 'other-media', at: '2026-10-15T10:40:00Z', by: 'refresh pahma-2026-10-15-1',
    action: 'recall_ended', details: {why: 'no longer listed as public'}}]
}
const SUMMARY = {
  records: [{media_csid: MEDIA, blob_csids: [BLOB], kind: 'image', served_today: true, recalled: false,
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

describe('the Recalls page', () => {
  it('lists recalls, and releases only one a refresh kept', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/recalls': {body: PAGE},
      [`POST /museums/pahma/recalls/${MEDIA}/release`]: {body: {released: MEDIA}}
    })
    const wrapper = await at('/pahma/recalls', Recalls)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA Recalls')
    expect(wrapper.find('#active-recalls').text()).toContain('Still public in CollectionSpace')
    expect(wrapper.find('#ended-recalls').text()).toContain('Ended by a refresh')
    await wrapper.find('#active-recalls .release').trigger('click')
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

  it('shows what would be recalled before it takes anything down', async () => {
    const calls = fakeApi({
      'GET /museums/pahma/recalls': {body: {...PAGE, active: []}},
      'POST /museums/pahma/recalls/summary': {body: SUMMARY},
      'POST /museums/pahma/recalls': {body: {...SUMMARY, recalled: [MEDIA]}}
    })
    const wrapper = await at('/pahma/recalls', Recalls)
    await wrapper.find('#recall').trigger('click')
    await flushPromises()
    type('#recall-csids', Array.from({length: 13}, (_, n) => `csid-${n}`).join('\n'))
    await flushPromises();
    (document.querySelector('#recall-summarize') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('More than 12 CSIDs: use a text file instead.'))
    expect(calls.filter(c => c.method === 'POST')).toHaveLength(0)
    type('#recall-csids', `${BLOB}, typo`)
    await flushPromises();
    (document.querySelector('#recall-summarize') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('#recall-summary')).not.toBeNull())
    expect(document.querySelector('#recall-summary')?.textContent).toContain(MEDIA)
    expect(document.querySelector('#recall-not-found')?.textContent).toContain('typo: Not a CSID.')
    const thumbnail = document.querySelector('#recall-summary img') as HTMLImageElement
    expect(thumbnail.getAttribute('src')).toBe(`/admin/v1/museums/pahma/media/${MEDIA}/preview?size=thumbnail`)
    const confirm = () => document.querySelector('#recall-confirm') as HTMLButtonElement
    expect(confirm().textContent).toContain('Recall 1 Media record')
    expect(confirm().disabled).toBe(true)
    type('#recall-reason', 'A complaint from a community')
    await flushPromises()
    confirm().click()
    await vi.waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/museums/pahma/recalls')).toBe(true))
    expect(calls.find(c => c.path === '/museums/pahma/recalls' && c.method === 'POST')?.body).toEqual(
      {text: `${BLOB}, typo`, reason: 'A complaint from a community'})
    wrapper.unmount()
  })
})

describe('Media look up', () => {
  const CS = {state: 'exists', media_csid: MEDIA, blob_csid: BLOB, updated_at: '2026-10-16T06:20:00.000Z',
    changed_since_refresh: true, fields: [{label: 'Publish to', value: 'None'}],
    next: 'The Media record changed in CollectionSpace after the last refresh.'}
  const ITEM = {blob_csid: BLOB, media_csid: MEDIA, kind: 'image', access: 'public',
    steps: [{check: 'In the servable list', outcome: 'Listed.', ok: true},
      {check: 'Recall', outcome: 'Recalled by admin at 2026-10-15T06:02:15+00:00: Testing.', ok: false}],
    sizes: [{size: 'Thumbnail', served: false, reason: 'recalled', verdict: 'not served', stored: null},
      {size: 'Medium', served: false, reason: 'recalled', verdict: 'not served',
        stored: {fetched_at: '2026-10-15T05:48:00Z', last_served: '2026-10-15T05:59:30Z', size: 98304, content_type: 'image/jpeg'}}],
    cspace: CS}
  const RESULT = {input: MEDIA, refused: null,
    refresh: {refresh_id: 'pahma-2026-10-15-1', refresh_date: '2026-10-15', started_at: '2026-10-15T10:01:00+00:00'},
    items: [ITEM]}

  it('shows the verdict, the sizes, and the file in Serena beside CollectionSpace (layout C)', async () => {
    const calls = fakeApi({[`GET /museums/pahma/lookup?q=${MEDIA}`]: {body: RESULT}})
    const wrapper = await at('/pahma/lookup', LookUp)
    expect(wrapper.find('#page-title').text()).toBe('PAHMA Media look up')
    await wrapper.find('#lookup-input').setValue(MEDIA)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(calls.map(c => c.path)).toEqual([`/museums/pahma/lookup?q=${MEDIA}`])
    expect(wrapper.find('#lookup-verdict').text()).toContain('Not served: recalled')
    expect(wrapper.find('#lookup-next').text()).toContain('Open Recalls')
    expect(wrapper.find('#lookup-sizes').text()).toContain('image/jpeg, 96 KB')
    expect(wrapper.find('#lookup-sizes').text()).toContain('2026-10-15 05:59:30 UTC') // last served
    expect(wrapper.find('#serena-preview').attributes('src')).toBe(`/admin/v1/museums/pahma/blobs/${BLOB}/preview?size=Medium`)
    expect(wrapper.find('#cspace-preview').attributes('src')).toBe(`/admin/v1/museums/pahma/media/${MEDIA}/preview?size=full&source=cspace`)
    expect(wrapper.find('#cspace-details').text()).toContain('Publish to')
    const compare = wrapper.find('#lookup-compare')
    expect(compare.findAll('tr.differs').map(r => r.find('th').text().replace(/\s+/g, ' '))).toEqual(['As of differs'])
    expect(wrapper.find('#lookup-next-refresh').text()).toContain('changed in CollectionSpace after the last refresh')
    wrapper.unmount()
  })

  it('looks up its ?q=, and says when CollectionSpace can\'t be reached', async () => {
    fakeApi({[`GET /museums/pahma/lookup?q=${BLOB}`]: {body: {...RESULT, input: BLOB,
      items: [{...ITEM, steps: ITEM.steps.slice(0, 1), sizes: [{...ITEM.sizes[0], served: true, reason: null}],
        cspace: {state: 'unavailable'}}]}}})
    const wrapper = await at(`/pahma/lookup?q=${BLOB}`, LookUp)
    expect(wrapper.find('#lookup-verdict').text()).toContain('Served')
    expect(wrapper.find('#lookup-cspace-down').exists()).toBe(true)
    expect(wrapper.find('#lookup-compare').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('the file dialogs', () => {
  it('opens a recall\'s CSIDs, with Media look up', async () => {
    fakeApi({'GET /museums/pahma/recalls': {body: PAGE}, [`GET /museums/pahma/lookup?q=${MEDIA}`]: {body: {
      input: MEDIA, refused: null, refresh: null, items: []}}})
    const wrapper = await at('/pahma/recalls', Recalls)
    const links = wrapper.findAll('#active-recalls .recall-csid')
    expect(links.map(l => l.text())).toEqual([MEDIA, BLOB])
    await links[1].trigger('click')
    await flushPromises()
    const dialog = document.querySelector('#file-dialog')
    expect(dialog?.textContent).toContain(BLOB)
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(`/admin/v1/museums/pahma/blobs/${BLOB}/preview?size=full`)
    ;(document.querySelector('#file-dialog-dismiss') as HTMLElement).click()
    await flushPromises()
    expect(document.querySelector('#file-dialog')).toBeNull()
    wrapper.unmount()
  })
})
