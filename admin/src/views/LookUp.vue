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
        variant="flat"
        :loading="loading"
        :disabled="!q.trim()"
      >
        Look up
      </v-btn>
    </v-form>
    <LoadError :message="error" />
    <v-alert
      v-if="result?.refused && result.items.length"
      id="lookup-bare-blob"
      type="info"
      variant="tonal"
      class="mb-4"
    >
      <template v-if="mediaUrl">
        Serena doesn't serve /media/ URLs yet (pull request 15): a request for one gets the unavailable image, reason
        "{{ reasonOf(result.refused) }}". Below, its Media record, looked up on its own.
      </template>
      <template v-else>
        This URL isn't one Serena serves (it needs /content or /derivatives/&lt;size&gt;/content): a request for it gets
        the unavailable image, reason "{{ reasonOf(result.refused) }}". Below, its Blob CSID, looked up on its own.
      </template>
    </v-alert>
    <h2 v-if="heading" id="lookup-heading" class="text-h6 mb-3">
      <!-- Shown whole: one click selects it, and there's no ⧉ (Richard, October 14, 2026). -->
      {{ heading.prefix }}<span class="sel-all">{{ heading.name }}</span>
      <span v-if="heading.csid" class="text-body-2 text-medium-emphasis ml-2">Media CSID <span class="mono sel-all">{{ heading.csid }}</span></span>
    </h2>
    <template v-if="result">
      <v-alert
        v-if="result.refused && !result.items.length"
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
            <v-btn
              v-for="(each, i) in result.items"
              :key="each.blob_csid"
              :value="i"
              :title="each.blob_csid"
            >
              {{ short(each.blob_csid) }}
            </v-btn>
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
                  alt="Serena's cached copy"
                  @error="broken.serena = true"
                >
                <span v-if="!largestStored || broken.serena" class="cap">{{ largestStored ? 'Serena\'s copy can\'t be shown' : 'No cached copy in Serena' }}</span>
              </div>
              <details id="serena-details" :open="open.serena" @toggle="open.serena = ($event.target as HTMLDetailsElement).open">
                <summary>Details</summary>
                <dl>
                  <dt>Media CSID</dt><dd class="mono" :class="{'sel-all': item.media_csid}">{{ item.media_csid || 'none' }}</dd>
                  <dt>Blob CSID</dt><dd class="mono sel-all">{{ item.blob_csid }}</dd>
                  <dt>Kind</dt><dd>{{ item.kind ? kindWord(item.kind) : 'not known' }}</dd>
                  <dt>Access</dt><dd>{{ item.access || 'not known' }}</dd>
                  <dt>First cached</dt><dd>{{ firstStored ? when(firstStored) : 'never' }}</dd>
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
                  :alt="`CollectionSpace's ${noun} now`"
                  @error="broken.cspace = true"
                >
                <span v-if="cspaceCaption" class="cap">{{ cspaceCaption }}</span>
              </div>
              <details
                v-if="hasRecord"
                id="cspace-details"
                :open="open.cspace"
                @toggle="open.cspace = ($event.target as HTMLDetailsElement).open"
              >
                <summary>Details</summary>
                <dl>
                  <dt>Media CSID</dt><dd class="mono sel-all">{{ cs.media_csid }}</dd>
                  <dt>State</dt><dd>{{ cs.state === 'deleted' ? 'Soft-deleted' : 'Exists' }}</dd>
                  <dt>Blob CSID</dt>
                  <dd class="mono">
                    <span :class="{'sel-all': cs.blob_csid}">{{ cs.blob_csid || 'none' }}</span>
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
              <span><span class="k">First cached in Serena</span> {{ firstStored ? when(firstStored) : 'never' }}</span>
            </p>
            <!-- The sizes fold away under a line that says what their rows would (Richard, October 14, 2026): open to
                 start only when the sizes differ, then as the admin leaves it. One size (a path's) has no box. -->
            <details
              v-if="item.sizes.length > 1"
              id="lookup-sizes-box"
              class="sizes-box"
              :open="sizesOpen"
              @toggle="sizesToggled(($event.target as HTMLDetailsElement).open)"
            >
              <summary>{{ sizesSummary }}</summary>
              <SizesTable :sizes="item.sizes" @open="openSize" />
            </details>
            <SizesTable v-else :sizes="item.sizes" @open="openSize" />
            <p class="text-caption text-medium-emphasis mb-4">
              Last served: the day Serena last answered a request with its cached copy (recorded at most once a day).
              First cached: when Serena fetched that size and cached it.
            </p>

            <h2 id="lookup-compare-heading" class="text-h6 mb-2">
              Serena and CollectionSpace
              <span
                v-if="sync"
                id="lookup-sync"
                class="text-body-1 font-weight-bold ml-1"
                :class="sync.differs ? 'text-warning' : 'text-success'"
                :title="sync.differs ? 'Rows where Serena\'s records and CollectionSpace differ are highlighted below.' : 'Serena\'s records match what CollectionSpace says now.'"
              >{{ sync.text }}</span>
            </h2>
            <p v-if="cs.state === 'no_media'" class="mb-2">
              Nothing to compare: this {{ noun }} has no Media record (the museum's placeholder image is served from
              uploaded files).
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
                    <td>
                      <ShortCsid v-if="row.serenaCsid" :csid="row.serenaCsid" :label="row.label" />
                      <template v-else>{{ row.serena }}</template>
                    </td>
                    <td>
                      <template v-if="row.cspacePrefix">{{ row.cspacePrefix }} · </template>
                      <ShortCsid v-if="row.cspaceCsid" :csid="row.cspaceCsid" :label="row.label" />
                      <template v-else>{{ row.cspace }}</template>
                    </td>
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
    <FileDialog :file="file" @close="file = null" />
  </v-container>
</template>

<script setup lang="ts">
import {computed, reactive, ref, watch} from 'vue'
import {useRoute, useRouter} from 'vue-router'
import {museumName} from '@/session'
import type {Lookup, LookupCSpace, LookupItem} from '@/api'
import {api, problem} from '@/api'
import FileDialog from '@/components/FileDialog.vue'
import type {ShownFile} from '@/components/FileDialog.vue'
import LoadError from '@/components/LoadError.vue'
import ShortCsid from '@/components/ShortCsid.vue'
import SizesTable from '@/components/SizesTable.vue'
import {kindWord, reasonOf, short, when} from '@/words'

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
// Each Details stays as the admin leaves it; the sizes box too, once opened or closed (undefined: as it starts).
const open = reactive<{serena: boolean, cspace: boolean, sizes?: boolean}>({serena: false, cspace: false})
const file = ref<ShownFile | null>(null)
const broken = reactive({serena: false, cspace: false})

const item = computed<LookupItem | null>(() => result.value?.items[Math.min(index.value, result.value.items.length - 1)] || null)
const cs = computed<LookupCSpace>(() => item.value?.cspace || {state: 'unavailable'})
// Which Media record this is, as staff know it (D153): "Media <identification number>", with its CSID beside;
// without a number (none, CollectionSpace can't be reached, or no such record), "Media <Media CSID>".
const heading = computed<{prefix: string, name: string, csid?: string} | null>(() => {
  const it = item.value
  if (!it) {
    return null
  }
  if (cs.value.state === 'no_media') {
    return {prefix: '', name: 'Placeholder image'}
  }
  const media = cs.value.media_csid || it.media_csid
  if (!media) {
    return null
  }
  const number = cs.value.identification_number
  return number ? {prefix: 'Media ', name: number, csid: media} : {prefix: 'Media ', name: media}
})
// A /media/ URL, which Serena serves from pull request 15: its Media record is looked up on its own.
const mediaUrl = computed(() => /\/imageserver\/media\//.test(result.value?.input || ''))

// The sizes box's line, for example "Sizes (6): none served (recalled) · cached: Medium".
const sizesSummary = computed(() => {
  const sizes = item.value?.sizes || []
  const served = sizes.filter(s => s.served).length
  const reasons = [...new Set(sizes.filter(s => !s.served && s.reason).map(s => reasonOf(s.reason!)))]
  const cached = sizes.filter(s => s.stored).map(s => s.size)
  const what = served === sizes.length ? 'all served' : served === 0 ? `none served (${reasons.join(', ')})` : `${served} of ${sizes.length} served`
  return `Sizes (${sizes.length}): ${what} · ${cached.length ? `cached: ${cached.join(', ')}` : 'none cached'}`
})
const sizesOpen = computed(() => {
  if (open.sizes !== undefined) {
    return open.sizes
  }
  const served = (item.value?.sizes || []).filter(s => s.served).length
  return served > 0 && served < (item.value?.sizes.length || 0)
})

// Only the admin's own opening or closing is kept: the toggle that follows the page's own :open is ignored.
function sizesToggled(now: boolean) {
  if (now !== sizesOpen.value) {
    open.sizes = now
  }
}

// A size opens that size's file in the file dialog (Richard, October 14, 2026), without "Media look up": this is it.
function openSize(size: string) {
  const it = item.value
  if (!it) {
    return
  }
  const path = `/${museum.value}/imageserver/blobs/${it.blob_csid}/${size === 'original' ? '' : `derivatives/${size}/`}content`
  file.value = {
    title: size === 'original' ? `Original ${noun.value}` : size,
    name: path,
    url: api.blobPreviewUrl(museum.value, it.blob_csid, size)
  }
}
const hasRecord = computed(() => cs.value.state === 'exists' || cs.value.state === 'deleted')
const blobDiffers = computed(() => !!item.value?.kind && !!cs.value.blob_csid && cs.value.blob_csid !== item.value.blob_csid)
const stored = computed(() => (item.value?.sizes || []).filter(s => s.stored))
// How the page names this file: "image", "catalog card", "PDF", "3D model", or "file" when the kind isn't known (D151).
const noun = computed(() => kindWord(item.value?.kind))
const largestStored = computed(() => stored.value.length ? stored.value[stored.value.length - 1] : null)
const firstStored = computed(() => stored.value.map(s => s.stored!.fetched_at).sort()[0] || null)
const lastServed = computed(() => stored.value.map(s => s.stored!.last_served).filter(Boolean).sort().reverse()[0] || null)

const cspaceCaption = computed(() => {
  switch (cs.value.state) {
  case 'no_media': return 'No Media record'
  case 'unavailable': return 'CollectionSpace can\'t be reached'
  case 'gone': return 'Not in CollectionSpace'
  default:
    // A picture that shows needs no caption; a caption says why there's none, or that the file is soft-deleted.
    if (broken.cspace || !cs.value.media_csid) {
      return `CollectionSpace's ${noun.value} can't be shown`
    }
    return cs.value.state === 'deleted' ? 'Soft-deleted in CollectionSpace' : ''
  }
})

interface CompareRow {
  label: string
  serena: string
  cspace: string
  differs: boolean
  serenaCsid?: string // a CSID: shown shortened, with ⧉ (D154)
  cspaceCsid?: string
  cspacePrefix?: string
}

const compare = computed<CompareRow[]>(() => {
  const it = item.value
  const c = cs.value
  if (!it) {
    return []
  }
  const fields = (c.fields || []).map(f => `${f.label}: ${f.value || '(empty)'}`).join('; ') || 'none configured'
  const refresh = result.value?.refresh
  return [
    {label: 'Media CSID', serena: 'not listed', serenaCsid: it.media_csid || undefined,
     cspacePrefix: c.state === 'deleted' ? 'Soft-deleted' : 'Exists', cspace: '', cspaceCsid: c.media_csid || undefined,
     differs: c.state === 'deleted' || (!!it.media_csid && c.media_csid !== it.media_csid)},
    {label: 'Blob CSID', serena: 'not listed', serenaCsid: it.kind ? it.blob_csid : undefined,
     cspace: 'none', cspaceCsid: c.blob_csid || undefined, differs: blobDiffers.value},
    {label: 'Access', serena: it.access || 'not listed', cspace: fields, differs: false},
    {label: 'As of', serena: refresh ? `Refresh ${refresh.refresh_id}, started ${when(refresh.started_at)}` : 'no refresh yet',
     cspace: c.updated_at ? `Last changed ${when(c.updated_at)}` : 'not known', differs: !!c.changed_since_refresh}
  ]
})

// Whether Serena's records and CollectionSpace agree, beside the heading (D162): green, or amber naming the rows.
const sync = computed<{text: string, differs: boolean} | null>(() => {
  if (!hasRecord.value) {
    return null
  }
  const differing = compare.value.filter(r => r.differs).map(r => r.label)
  if (!differing.length) {
    return {text: '✓ (No differences)', differs: false}
  }
  const n = differing.length
  return {text: `⚠ (${n} difference${n === 1 ? '' : 's'}: ${differing.join(', ')})`, differs: true}
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
              ? (one.stored ? 'Serena has a cached copy, so it\'s served without asking CollectionSpace.' : 'Serena has no copy yet: the next request fetches it from CollectionSpace and caches it.')
              : 'A size with a cached copy is served from it; any other size is fetched from CollectionSpace on its first request, then cached.'}
  }
  if (served.length) {
    return {tone: 'served', head: 'Served (cached sizes only)',
            why: 'Serena lists it, so its cached sizes are served; a size without a cached copy would be refused by the fetch.',
            next: 'To stop serving it now, recall it.', recalls: true}
  }
  const first = it.sizes.find(s => s.reason)
  if (first?.reason === 'media_deleted' || first?.reason === 'media_gone') {
    const how = first.reason === 'media_deleted' ? 'soft-deleted' : 'gone'
    return {tone: 'not', head: `Not served: the Media record is ${how} in CollectionSpace`,
            why: `Serena has no cached copy${it.sizes.length === 1 ? ` of ${it.sizes[0].size}` : ''}, and a fetch would find the Media record ${how}.`,
            next: cs.value.next || ''}
  }
  return {tone: 'not', head: `Not served: ${first ? reasonOf(first.reason!) : 'see the sizes'}`,
          why: first ? first.verdict : '', next: cs.value.next || ''}
})

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
.sizes-box > summary { font-weight: 600; margin: 4px 0 6px; }
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
