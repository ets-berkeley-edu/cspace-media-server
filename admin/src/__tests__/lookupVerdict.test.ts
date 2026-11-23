/** Media look up's verdict for a refusal without a verdict of its own (issue #208). Synthetic CSIDs only. */
import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import {session} from '@/session'
import LookUp from '@/views/LookUp.vue'

const MEDIA = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c50'
const BLOB = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a50'

type Step = {check: string, outcome: string, ok: boolean | null}

function item(kind: string, access: string, steps: Step[], sizes: {size: string, reason: string}[]) {
  return {blob_csid: BLOB, media_csid: MEDIA, kind, access, steps,
    sizes: sizes.map(s => ({...s, served: false, verdict: 'not served', stored: null})),
    cspace: {state: 'exists', media_csid: MEDIA, blob_csid: BLOB, updated_at: '2026-11-07T00:00:00.000Z',
      changed_since_refresh: false, fields: [], next: ''}}
}

const LISTED: Step = {check: 'In the ETL list', outcome: 'Listed in the ETL list of the last ETL list update.', ok: true}
const NO_RECALL: Step = {check: 'Recall', outcome: 'No recall.', ok: true}

async function verdict(it: unknown): Promise<string[]> {
  session.signedIn = [{museum: 'pahma', name: 'PAHMA', user: 'admin'}] as never
  fakeApi({[`GET /museums/pahma/lookup?q=${BLOB}`]: {body: {input: BLOB, refused: null, refresh: null, items: [it]}}})
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push(`/pahma/lookup?q=${BLOB}`)
  const wrapper = mount(LookUp as never, {global: {plugins: [router]}, attachTo: document.body})
  await flushPromises()
  const lines = wrapper.find('#lookup-verdict').findAll('div').map(d => d.text())
  wrapper.unmount()
  return lines
}

describe('Media look up\'s verdict says why, not "not served" twice', () => {
  it('for an audio file, a kind Serena does not serve', async () => {
    const lines = await verdict(item('audio', 'public',
      [LISTED, {check: 'Kind', outcome: 'audio file: not served', ok: false}, {check: 'Access', outcome: 'public', ok: true},
        NO_RECALL],
      [{size: 'original', reason: 'kind_not_served'}, {size: 'Medium', reason: 'kind_not_served'}]))
    expect(lines).toEqual(['Not served: kind not served',
      'Serena doesn\'t serve audio files yet: a request gets the unavailable image.'])
  })

  it('for a size the museum watermarks, where every check passes', async () => {
    const lines = await verdict(item('image', 'public',
      [LISTED, {check: 'Kind', outcome: 'image', ok: true}, {check: 'Access', outcome: 'public', ok: true}, NO_RECALL],
      [{size: 'FullHD', reason: 'watermark_not_built'}]))
    expect(lines[0]).toBe('Not served: watermark not built')
    expect(lines[1]).toBe('The museum watermarks the FullHD size, and Serena doesn\'t watermark files yet: a request '
      + 'gets the unavailable image.')
  })

  it('falls back to the failing check\'s outcome for a reason without a sentence', async () => {
    const lines = await verdict(item('image', 'public',
      [LISTED, {check: 'Kind', outcome: 'image', ok: true}, {check: 'Access', outcome: 'public', ok: true},
        {check: 'Something new', outcome: 'Something new: not served', ok: false}],
      [{size: 'Medium', reason: 'something_new'}]))
    expect(lines).toEqual(['Not served: something new', 'Something new: not served'])
  })
})
