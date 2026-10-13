<template>
  <v-container fluid>
    <h1 id="page-title" class="text-h5 mb-4">{{ museumName(museum) }} Media look up</h1>
    <p class="mb-4">
      Why Serena serves a file or not. Give a file's URL or path, a Blob CSID or a Media CSID. Serena's answer comes from
      its own records, as a request without a signed link gets it; beside it, what CollectionSpace says now, for
      comparison.
    </p>
    <v-form class="d-flex align-start flex-wrap ga-4 mb-4" @submit.prevent="submit">
      <v-text-field
        id="lookup-input"
        v-model="q"
        label="URL, path, Blob CSID or Media CSID"
        style="min-width: 320px"
        class="flex-grow-1"
      />
      <v-btn
        id="lookup-go"
        type="submit"
        color="primary"
        :loading="loading"
        :disabled="!q.trim()"
      >
        Look up
      </v-btn>
    </v-form>
    <LoadError :message="error" />
    <template v-if="result">
      <v-alert
        v-if="result.refused"
        id="lookup-refused"
        type="warning"
        variant="tonal"
        class="mb-4"
      >
        Not served: {{ reasonOf(result.refused) }}. No CSID was looked up.
      </v-alert>
      <template v-if="item">
        <div v-if="result.items.length > 1" class="mb-3">
          <p class="mb-2">This Media record has {{ result.items.length }} Blobs in the servable list:</p>
          <v-btn-toggle
            id="lookup-blobs"
            v-model="index"
            mandatory
            density="compact"
            variant="outlined"
          >
            <v-btn v-for="(each, i) in result.items" :key="each.blob_csid" :value="i">{{ short(each.blob_csid) }}</v-btn>
          </v-btn-toggle>
        </div>
        <div class="inspector">
          <aside class="inspect-side" aria-label="The file in Serena and in CollectionSpace">
            <section class="panel" aria-label="In Serena">
              <h2 class="panel-title">In Serena</h2>
              <div class="preview">
                <img
                  v-if="largestStored && !broken.serena"
                  id="serena-preview"
                  :src="api.blobPreviewUrl(museum, item.blob_csid, largestStored.size)"
                  alt="Serena's stored copy"
                  @error="broken.serena = true"
                >
                <span class="cap">{{ largestStored ? `Serena's stored ${largestStored.size}` : 'No copy stored in Serena' }}</span>
              </div>
              <details id="serena-details" :open="open.serena" @toggle="open.serena = ($event.target as HTMLDetailsElement).open">
                <summary>Details</summary>
                <dl>
                  <dt>Media CSID</dt><dd class="mono">{{ item.media_csid || 'none' }}</dd>
                  <dt>Blob CSID</dt><dd class="mono">{{ item.blob_csid }}</dd>
                  <dt>Kind</dt><dd>{{ item.kind || 'not known' }}</dd>
                  <dt>Access</dt><dd>{{ item.access || 'not known' }}</dd>
                  <dt>First stored</dt><dd>{{ firstStored ? when(firstStored) : 'never' }}</dd>
                  <dt>Last served</dt><dd>{{ lastServed ? when(lastServed) : 'never' }}</dd>
                </dl>
                <h3 class="text-subtitle-2 mt-2">Checks</h3>
                <ul class="checks">
                  <li v-for="step in item.steps" :key="step.check" :class="step.ok === true ? 'ok' : step.ok === false ? 'no' : 'maybe'">
                    <strong>{{ step.check }}</strong>: {{ step.outcome }}
                  </li>
                </ul>
              </details>
            </section>
            <section class="panel" aria-label="In CollectionSpace now">
              <h2 class="panel-title">In CollectionSpace now</h2>
              <div class="preview">
                <img
                  v-if="hasRecord && cs.media_csid && !broken.cspace"
                  id="cspace-preview"
                  :src="api.previewUrl(museum, cs.media_csid, 'full', 'cspace')"
                  alt="CollectionSpace's file now"
                  @error="broken.cspace = true"
                >
                <span class="cap">{{ cspaceCaption }}</span>
              </div>
              <details
                v-if="hasRecord"
                id="cspace-details"
                :open="open.cspace"
                @toggle="open.cspace = ($event.target as HTMLDetailsElement).open"
              >
                <summary>Details</summary>
                <dl>
                  <dt>Media CSID</dt><dd class="mono">{{ cs.media_csid }}</dd>
                  <dt>State</dt><dd>{{ cs.state === 'deleted' ? 'Soft-deleted' : 'Exists' }}</dd>
                  <dt>Blob CSID</dt>
                  <dd class="mono">
                    {{ cs.blob_csid || 'none' }}
                    <v-chip
                      v-if="blobDiffers"
                      size="x-small"
                      color="warning"
                      class="ml-1"
                    >
                      differs
                    </v-chip>
                  </dd>
                  <div v-for="f in cs.fields || []" :key="f.label" class="pair">
                    <dt>{{ f.label }}</dt><dd>{{ f.value || '(empty)' }}</dd>
                  </div>
                  <dt>Last changed</dt><dd>{{ cs.updated_at ? when(cs.updated_at) : 'not known' }}</dd>
                </dl>
              </details>
            </section>
          </aside>
          <div class="answer">
            <div id="lookup-verdict" class="verdict" :class="verdict.tone">
              <div class="verdict-head">{{ verdict.head }}</div>
              <div>{{ verdict.why }}</div>
            </div>
            <p id="lookup-next" class="mt-2 mb-2">
              {{ verdict.next }}
              <router-link v-if="verdict.recalls" :to="{name: 'recalls', params: {museum}}">Open Recalls</router-link>
            </p>
            <p class="stamps">
              <span><span class="k">Last served</span> {{ lastServed ? when(lastServed) : 'never' }}</span>
              <span><span class="k">First stored in Serena</span> {{ firstStored ? when(firstStored) : 'never' }}</span>
            </p>
            <v-table id="lookup-sizes" density="compact" class="mb-1">
              <thead>
                <tr class="text-no-wrap">
                  <th>Size</th><th>Served</th><th>Why not</th><th>Stored copy</th><th>Last served</th><th>First stored</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="size in item.sizes" :key="size.size">
                  <td>{{ size.size }}</td>
                  <td>{{ size.served ? 'Yes' : 'No' }}</td>
                  <td>{{ size.reason ? reasonOf(size.reason) : '' }}</td>
                  <td>{{ size.stored ? `${size.stored.content_type}, ${bytes(size.stored.size)}` : '—' }}</td>
                  <td>{{ size.stored?.last_served ? when(size.stored.last_served) : '—' }}</td>
                  <td>{{ size.stored ? when(size.stored.fetched_at) : '—' }}</td>
                </tr>
              </tbody>
            </v-table>
            <p class="text-caption text-medium-emphasis mb-4">
              Last served: the day Serena last answered a request with its stored copy (recorded at most once a day).
              First stored: when Serena fetched that size and stored it.
            </p>

            <h2 class="text-h6 mb-2">Serena and CollectionSpace</h2>
            <p v-if="cs.state === 'no_media'" class="mb-2">
              Nothing to compare: this file has no Media record (the museum's placeholder image is served from uploaded
              files).
            </p>
            <v-alert
              v-else-if="cs.state === 'unavailable'"
              id="lookup-cspace-down"
              type="info"
              variant="tonal"
              class="mb-2"
            >
              CollectionSpace can't be reached, so there's nothing to compare with. Serena's answer above doesn't depend on
              it.
            </v-alert>
            <template v-else>
              <v-table
                v-if="hasRecord"
                id="lookup-compare"
                density="compact"
                class="mb-2"
              >
                <thead><tr><th /><th>Serena (the last refresh)</th><th>CollectionSpace now</th></tr></thead>
                <tbody>
                  <tr v-for="row in compare" :key="row.label" :class="{differs: row.differs}">
                    <th scope="row">
                      {{ row.label }}
                      <v-chip
                        v-if="row.differs"
                        size="x-small"
                        color="warning"
                        class="ml-1"
                      >
                        differs
                      </v-chip>
                    </th>
                    <td>{{ row.serena }}</td>
                    <td>{{ row.cspace }}</td>
                  </tr>
                </tbody>
              </v-table>
              <p id="lookup-next-refresh" class="mb-1"><strong>What the next refresh will do:</strong> {{ cs.next }}</p>
              <p class="text-caption text-medium-emphasis">
                The ETL decides what's public from its own rules, partly from the Object record (a sensitive Object, for
                example), which isn't shown here. These are the Media record's fields only.
              </p>
            </template>
          </div>
        </div>
      </template>
      <p id="lookup-refresh" class="text-caption text-medium-emphasis mt-4">
        Looked up {{ result.input }} ·
        <template v-if="result.refresh">
          last servability update: refresh {{ result.refresh.refresh_id }} (refresh date {{ result.refresh.refresh_date }})
        </template>
        <template v-else>no servability update yet</template>
      </p>
    </template>
  </v-container>
</template>

<script setup lang="ts">
import {computed, reactive, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {museumName} from '@/session'
import type {Lookup, LookupCSpace, LookupItem} from '@/api'
import {api, problem} from '@/api'
import LoadError from '@/components/LoadError.vue'
import {reasonOf, when} from '@/words'

// Media look up, layout C from the UI review (decided October 13, 2026, D139 to D145): Serena's answer, with the file
// in Serena and in CollectionSpace side by side.
const route = useRoute()
const router = useRouter()
const museum = computed(() => String(route.params.museum))
const q = ref('')
const result = ref<Lookup | null>(null)
const index = ref(0)
const loading = ref(false)
const error = ref('')
const open = reactive({serena: false, cspace: false}) // each Details stays as the admin leaves it
const broken = reactive({serena: false, cspace: false})

const item = computed<LookupItem | null>(() => result.value?.items[Math.min(index.value, result.value.items.length - 1)] || null)
const cs = computed<LookupCSpace>(() => item.value?.cspace || {state: 'unavailable'})
const hasRecord = computed(() => cs.value.state === 'exists' || cs.value.state === 'deleted')
const blobDiffers = computed(() => !!item.value?.kind && !!cs.value.blob_csid && cs.value.blob_csid !== item.value.blob_csid)
const stored = computed(() => (item.value?.sizes || []).filter(s => s.stored))
const largestStored = computed(() => stored.value.length ? stored.value[stored.value.length - 1] : null)
const firstStored = computed(() => stored.value.map(s => s.stored!.fetched_at).sort()[0] || null)
const lastServed = computed(() => stored.value.map(s => s.stored!.last_served).filter(Boolean).sort().reverse()[0] || null)

const cspaceCaption = computed(() => {
  switch (cs.value.state) {
  case 'no_media': return 'No Media record'
  case 'unavailable': return 'CollectionSpace can\'t be reached'
  case 'gone': return 'Not in CollectionSpace'
  default: return `CollectionSpace's file now${cs.value.state === 'deleted' ? ' (soft-deleted)' : ''}, not stored`
  }
})

const compare = computed(() => {
  const it = item.value
  const c = cs.value
  if (!it) {
    return []
  }
  const fields = (c.fields || []).map(f => `${f.label}: ${f.value || '(empty)'}`).join('; ') || 'none configured'
  const refresh = result.value?.refresh
  return [
    {label: 'Media CSID', serena: it.media_csid ? short(it.media_csid) : 'not listed',
     cspace: `${c.state === 'deleted' ? 'Soft-deleted' : 'Exists'} · ${short(c.media_csid || '')}`,
     differs: c.state === 'deleted' || (!!it.media_csid && c.media_csid !== it.media_csid)},
    {label: 'Blob CSID', serena: it.kind ? short(it.blob_csid) : 'not listed', cspace: c.blob_csid ? short(c.blob_csid) : 'none',
     differs: blobDiffers.value},
    {label: 'Access', serena: it.access || 'not listed', cspace: fields, differs: false},
    {label: 'As of', serena: refresh ? `Refresh ${refresh.refresh_id}, started ${when(refresh.started_at)}` : 'no refresh yet',
     cspace: c.updated_at ? `Last changed ${when(c.updated_at)}` : 'not known', differs: !!c.changed_since_refresh}
  ]
})

interface Verdict {
  tone: 'served' | 'not' | 'depends'
  head: string
  why: string
  next: string
  recalls?: boolean
}

const verdict = computed<Verdict>(() => {
  const it = item.value!
  const refresh = result.value?.refresh?.refresh_id
  const step = (check: string) => it.steps.find(s => s.check === check)
  if (!it.kind) {
    return {tone: 'not', head: 'Not served: not in the servable list',
            why: `${refresh ? `Refresh ${refresh}'s` : 'The'} servable list doesn't have this CSID, as a Blob or a Media record.`,
            next: cs.value.next || 'Check the record in CollectionSpace: a change there shows here after the next refresh.'}
  }
  const access = step('Access')
  if (access && access.ok === null) {
    return {tone: 'depends', head: 'Served only on a signed link', why: `Access is ${access.outcome}.`,
            next: 'A plain link, without a signature, gets the unavailable image.'}
  }
  const recall = step('Recall')
  if (recall && recall.ok === false) {
    return {tone: 'not', head: 'Not served: recalled', why: recall.outcome, recalls: true,
            next: recall.outcome.includes('kept it')
              ? 'Change the record in CollectionSpace; or, if the recall was a mistake, release it on the Recalls page.'
              : 'It stays recalled until a refresh on a later day no longer lists the Media record as public. If that refresh still lists it, Serena alerts, and an admin can then release it.'}
  }
  const placeholder = step('Placeholder image')
  if (placeholder && placeholder.ok === false) {
    return {tone: 'not', head: 'Not served: the placeholder image isn\'t uploaded', why: placeholder.outcome,
            next: 'Upload its files (coming in pull request 14b).'}
  }
  const served = it.sizes.filter(s => s.served)
  const one = it.sizes.length === 1 ? it.sizes[0] : null
  if (served.length === it.sizes.length) {
    return {tone: 'served', head: 'Served',
            why: one ? `Every check passes for the ${one.size} size.` : 'Every check passes for every size.',
            next: one
              ? (one.stored ? 'Serena has a stored copy, so it\'s served without asking CollectionSpace.' : 'Serena has no copy yet: the next request fetches it from CollectionSpace and stores it.')
              : 'A size with a stored copy is served from it; any other size is fetched from CollectionSpace on its first request, then stored.'}
  }
  if (served.length) {
    return {tone: 'served', head: 'Served (stored sizes only)',
            why: 'Serena lists it, so its stored sizes are served; a size without a stored copy would be refused by the fetch.',
            next: 'To stop serving it now, recall it.', recalls: true}
  }
  const first = it.sizes.find(s => s.reason)
  if (first?.reason === 'media_deleted' || first?.reason === 'media_gone') {
    const how = first.reason === 'media_deleted' ? 'soft-deleted' : 'gone'
    return {tone: 'not', head: `Not served: the Media record is ${how} in CollectionSpace`,
            why: `Serena has no stored copy${it.sizes.length === 1 ? ` of ${it.sizes[0].size}` : ''}, and a fetch would find the Media record ${how}.`,
            next: cs.value.next || ''}
  }
  return {tone: 'not', head: `Not served: ${first ? reasonOf(first.reason!) : 'see the sizes'}`,
          why: first ? first.verdict : '', next: cs.value.next || ''}
})

function short(csid: string): string {
  return csid.length > 20 ? `${csid.slice(0, 8)}…${csid.slice(-4)}` : csid
}

function bytes(n: number): string {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} bytes`
}

watch(museum, () => {
  result.value = null
  error.value = ''
})

// The page looks up its ?q= (so the file dialogs on Past requests and Recalls can open it), and puts each look up
// there, so it can be reloaded or shared with another admin.
watch(() => route.query.q, value => {
  const asked = typeof value === 'string' ? value : ''
  if (asked && asked !== result.value?.input) {
    q.value = asked
    void look(asked)
  }
}, {immediate: true})

async function submit() {
  const asked = q.value.trim()
  if (route.query.q === asked) {
    await look(asked)
  } else {
    await router.push({query: {q: asked}})
  }
}

async function look(asked: string) {
  loading.value = true
  error.value = ''
  broken.serena = broken.cspace = false
  try {
    result.value = await api.lookup(museum.value, asked)
    const at = result.value.items.findIndex(i => i.blob_csid === asked)
    index.value = Math.max(at, 0)
  } catch (e) {
    result.value = null
    error.value = problem(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.inspector {
  display: grid;
  grid-template-columns: minmax(220px, 300px) 1fr;
  gap: 20px;
  align-items: start;
}
@media (max-width: 900px) {
  .inspector { grid-template-columns: 1fr; }
}
.panel {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.panel-title {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.preview {
  position: relative;
  aspect-ratio: 4 / 3;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(var(--v-border-color), 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview img { width: 100%; height: 100%; object-fit: contain; }
.preview .cap {
  position: absolute;
  bottom: 6px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(var(--v-theme-surface), 0.9);
  border-radius: 10px;
  font-size: 0.75rem;
  padding: 1px 8px;
  white-space: nowrap;
}
details summary { cursor: pointer; margin-top: 8px; color: rgb(var(--v-theme-primary)); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; margin-top: 6px; font-size: 0.85rem; }
.pair { display: contents; }
dt { color: rgba(var(--v-theme-on-surface), 0.6); }
dd { overflow-wrap: anywhere; }
.mono { font-family: monospace; }
.checks { list-style: none; padding: 0; font-size: 0.85rem; }
.checks li.no strong { color: rgb(var(--v-theme-error)); }
.checks li.maybe strong { color: rgb(var(--v-theme-warning)); }
.verdict { border-radius: 8px; padding: 10px 14px; }
.verdict.served { background: rgba(var(--v-theme-success), 0.12); }
.verdict.not { background: rgba(var(--v-theme-error), 0.1); }
.verdict.depends { background: rgba(var(--v-theme-warning), 0.12); }
.verdict-head { font-weight: 700; font-size: 1.05rem; }
.stamps { display: flex; flex-wrap: wrap; gap: 6px 22px; font-size: 0.85rem; }
.stamps .k {
  color: rgba(var(--v-theme-on-surface), 0.6);
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  margin-right: 6px;
  text-transform: uppercase;
}
tr.differs { background: rgba(var(--v-theme-warning), 0.08); }
</style>
