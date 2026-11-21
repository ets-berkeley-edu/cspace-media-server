import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import LookUp from '@/views/LookUp.vue'

// Synthetic CSIDs only.
const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'
const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50'

// Issue #208: the generic verdict branch used the size's verdict ("not served") as the second line, repeating the
// heading. A kind not served says why from the kind; a reason without a sentence of its own gets the failing
// check's outcome.
describe("the look up verdict's second line", () => {
  async function verdictLines(body: unknown) {
    fakeApi({[`GET /museums/pahma/lookup?q=${BLOB}`]: {body}})
    const router = createRouter({history: createMemoryHistory('/admin/'), routes})
    await router.push(`/pahma/lookup?q=${BLOB}`)
    const wrapper = mount(LookUp as never, {global: {plugins: [router]}, attachTo: document.body})
    await flushPromises()
    const lines = wrapper.find('#lookup-verdict').findAll('div').map(d => d.text())
    wrapper.unmount()
    return lines
  }

  it("names the kind for a kind not served, not the size's verdict", async () => {
    const lines = await verdictLines({input: BLOB, refused: null, refresh: null, items: [{
      blob_csid: BLOB, media_csid: MEDIA, kind: 'video', access: 'public',
      steps: [{check: 'In the ETL list', outcome: 'Listed in the ETL list of the last ETL list update.', ok: true},
        {check: 'Kind', outcome: 'video: not served', ok: false},
        {check: 'Access', outcome: 'public', ok: true},
        {check: 'Recall', outcome: 'No recall.', ok: true}],
      sizes: [{size: 'original', served: false, reason: 'kind_not_served', verdict: 'not served', stored: null}],
      cspace: {state: 'exists', media_csid: MEDIA, blob_csid: BLOB, updated_at: '2026-11-07T00:00:00.000Z',
        changed_since_refresh: false, fields: [], next: ''}}]})
    expect(lines[0]).toBe('Not served: kind not served')
    expect(lines[1]).toContain('video')
    expect(lines[1]).not.toBe('not served')
    expect(lines[1]).toContain('unavailable image')
  })

  it("falls back to the failing check's outcome when there is no sentence", async () => {
    const lines = await verdictLines({input: BLOB, refused: null, refresh: null, items: [{
      blob_csid: BLOB, media_csid: MEDIA, kind: 'image', access: 'restricted',
      steps: [{check: 'In the ETL list', outcome: 'Listed in the ETL list of the last ETL list update.', ok: true},
        {check: 'Kind', outcome: 'image', ok: true},
        {check: 'Access', outcome: 'restricted: not served', ok: false},
        {check: 'Recall', outcome: 'No recall.', ok: true}],
      sizes: [{size: 'original', served: false, reason: 'restricted', verdict: 'not served', stored: null}],
      cspace: {state: 'exists', media_csid: MEDIA, blob_csid: BLOB, updated_at: '2026-11-07T00:00:00.000Z',
        changed_since_refresh: false, fields: [], next: ''}}]})
    expect(lines[0]).toBe('Not served: restricted')
    expect(lines[1]).toBe('restricted: not served')
  })
})
