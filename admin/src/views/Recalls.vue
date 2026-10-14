<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <h1 id="page-title" class="text-h5">{{ museumName(museum) }} Recalls</h1>
      <v-spacer />
      <v-btn
        id="recall"
        color="error"
        variant="flat"
        @click="openForm"
      >
        Recall…
      </v-btn>
    </div>
    <p class="mb-4">
      A recall stops Serena serving a Media record's file at once, until CollectionSpace and a later refresh catch up.
      Change the record in CollectionSpace too: a refresh, on a later day, ends the recall once its servable list
      no longer has the file as public. If the list still has it as public, the recall stays and Serena raises an
      alert, and an admin can release it if CollectionSpace is right. Until a refresh decides it, an admin can cancel a
      recall made by mistake.
    </p>
    <LoadError :message="error" />

    <h2 class="text-h6 mb-2">Active recalls</h2>
    <v-data-table
      id="active-recalls"
      :headers="activeHeaders"
      :items="page?.active || []"
      :sort-by="activeTable.sortBy"
      must-sort
      :items-per-page="activeTable.itemsPerPage"
      :page="activeTable.page"
      :items-per-page-options="PAGE_SIZES"
      :loading="loading"
      :expanded="openActive"
      item-value="media_csid"
      show-expand
      density="compact"
      no-data-text="No active recalls."
      class="mb-6"
      @update:expanded="(open: string[]) => openActive = open"
      @update:sort-by="(v: {key: string, order: 'asc' | 'desc'}[]) => activeTable.sortBy = v"
      @update:page="(v: number) => activeTable.page = v"
      @update:items-per-page="(v: number) => activeTable.itemsPerPage = v"
    >
      <!-- Vue 3 keys a template v-for on the template itself; BOA's rules also carry Vue 2's rule against it. -->
      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="h in activeHeaders" :key="h.key" #[`header.${h.key}`]="slot">
        <ColumnHeader v-bind="slot" :help="h.help" />
      </template>
      <template #[`item.data-table-expand`]="{item, internalItem, isExpanded, toggleExpand}">
        <button
          type="button"
          class="row-expand"
          :aria-expanded="isExpanded(internalItem) ? 'true' : 'false'"
          :aria-label="`${isExpanded(internalItem) ? 'Hide' : 'Show'} the CSIDs of ${numberOrCsid(item)}`"
          @click="toggleExpand(internalItem)"
        >
          {{ isExpanded(internalItem) ? '▾' : '▸' }}
        </button>
      </template>
      <template #[`item.identification_number`]="{item}"><RecordName :number="item.identification_number" :csid="item.media_csid" /></template>
      <template #expanded-row="{columns, item}">
        <tr class="row-details">
          <td :colspan="columns.length">
            <dl class="row-detail">
              <dt>Media CSID</dt>
              <dd>
                <FileLink class="mono recall-csid" @open="openCsid(item.media_csid, 'Media CSID')">{{ item.media_csid }}</FileLink>
                <CopyButton :value="item.media_csid" label="Media CSID" />
              </dd>
              <!-- eslint-disable-next-line vue/no-v-for-template-key -->
              <template v-for="blob in item.blob_csids" :key="blob">
                <dt>Blob CSID</dt>
                <dd>
                  <FileLink class="mono recall-csid" @open="openCsid(blob, 'Blob CSID')">{{ blob }}</FileLink>
                  <CopyButton :value="blob" label="Blob CSID" />
                </dd>
              </template>
              <dt />
              <dd><router-link :to="{name: 'lookup', params: {museum}, query: {q: item.media_csid}}">Media look up</router-link></dd>
            </dl>
          </td>
        </tr>
      </template>

      <template #[`item.at`]="{item}"><WhenText :at="item.at" /></template>
      <template #[`item.kept_by`]="{item}">
        <template v-if="item.kept_by">
          <v-chip size="small" color="error" variant="tonal">Still public in CollectionSpace</v-chip>
          <div class="text-medium-emphasis text-no-wrap">kept by <RefreshLink :id="item.kept_by" /></div>
        </template>
        <v-chip
          v-else
          size="small"
          color="info"
          variant="tonal"
        >
          Waiting for a later refresh
        </v-chip>
      </template>
      <template #[`item.actions`]="{item}">
        <v-btn
          v-if="item.kept_by"
          class="release"
          size="small"
          variant="outlined"
          @click="openEnd(item, 'release')"
        >
          Release…
        </v-btn>
        <v-btn
          v-else
          class="cancel-recall"
          size="small"
          variant="outlined"
          @click="openEnd(item, 'cancel')"
        >
          Cancel recall…
        </v-btn>
      </template>
    </v-data-table>

    <h2 class="text-h6 mb-2">Ended in the last {{ page?.days || 30 }} days</h2>
    <v-data-table
      id="ended-recalls"
      :headers="endedHeaders"
      :items="ended"
      :sort-by="endedTable.sortBy"
      must-sort
      :items-per-page="endedTable.itemsPerPage"
      :page="endedTable.page"
      :items-per-page-options="PAGE_SIZES"
      :expanded="openEnded"
      item-value="row_key"
      show-expand
      density="compact"
      no-data-text="None."
      @update:expanded="(open: string[]) => openEnded = open"
      @update:sort-by="(v: {key: string, order: 'asc' | 'desc'}[]) => endedTable.sortBy = v"
      @update:page="(v: number) => endedTable.page = v"
      @update:items-per-page="(v: number) => endedTable.itemsPerPage = v"
    >
      <!-- Vue 3 keys a template v-for on the template itself; BOA's rules also carry Vue 2's rule against it. -->
      <!-- eslint-disable-next-line vue/no-v-for-template-key -->
      <template v-for="h in endedHeaders" :key="h.key" #[`header.${h.key}`]="slot">
        <ColumnHeader v-bind="slot" :help="h.help" />
      </template>
      <template #[`item.at`]="{item}"><WhenText :at="item.at" /></template>
      <template #[`item.action`]="{item}">
        <template v-if="item.action === 'recall_release'">Released</template>
        <template v-else-if="item.action === 'recall_cancel'">Cancelled</template>
        <template v-else-if="item.by.startsWith('refresh ')">Ended by refresh <RefreshLink :id="item.by.slice(8)" /></template>
        <template v-else>Ended by a refresh</template>
      </template>
      <template #[`item.by`]="{item}">{{ actorOf(item.by) }}</template>
      <template #[`item.data-table-expand`]="{item, internalItem, isExpanded, toggleExpand}">
        <button
          type="button"
          class="row-expand"
          :aria-expanded="isExpanded(internalItem) ? 'true' : 'false'"
          :aria-label="`${isExpanded(internalItem) ? 'Hide' : 'Show'} the CSIDs of ${numberOrCsid(item)}`"
          @click="toggleExpand(internalItem)"
        >
          {{ isExpanded(internalItem) ? '▾' : '▸' }}
        </button>
      </template>
      <template #[`item.identification_number`]="{item}"><RecordName :number="item.identification_number" :csid="item.media_csid" /></template>
      <template #expanded-row="{columns, item}">
        <tr class="row-details">
          <td :colspan="columns.length">
            <dl class="row-detail">
              <dt>Media CSID</dt>
              <dd>
                <FileLink class="mono recall-csid" @open="openCsid(item.media_csid, 'Media CSID')">{{ item.media_csid }}</FileLink>
                <CopyButton :value="item.media_csid" label="Media CSID" />
              </dd>
              <!-- eslint-disable-next-line vue/no-v-for-template-key -->
              <template v-for="blob in blobsOf(item)" :key="blob">
                <dt>Blob CSID</dt>
                <dd>
                  <FileLink class="mono recall-csid" @open="openCsid(blob, 'Blob CSID')">{{ blob }}</FileLink>
                  <CopyButton :value="blob" label="Blob CSID" />
                </dd>
              </template>
              <dt />
              <dd><router-link :to="{name: 'lookup', params: {museum}, query: {q: item.media_csid}}">Media look up</router-link></dd>
            </dl>
          </td>
        </tr>
      </template>
      <template #[`item.details`]="{item}">{{ item.details.reason || item.details.why || '' }}</template>
    </v-data-table>
    <FileDialog :file="shownFile" @close="shownFile = null" />

    <v-dialog v-model="form" max-width="1100" scrollable>
      <v-card>
        <v-card-title>Recall Media records</v-card-title>
        <v-card-text>
          <template v-if="!summary">
            <p class="mb-3">
              Give up to {{ page?.max_in_box || 12 }} Media or Blob CSIDs, separated by new lines, commas or spaces, or a
              text file of up to {{ (page?.max_in_file || 1000).toLocaleString('en-US') }}, one per line. Nothing is recalled
              until you confirm.
            </p>
            <v-textarea
              id="recall-csids"
              v-model="box"
              label="Media or Blob CSIDs"
              rows="4"
              :disabled="!!file"
            />
            <v-file-input
              id="recall-file"
              v-model="file"
              label="Or a text file of CSIDs"
              accept=".txt,text/plain"
              show-size
            />
            <v-alert
              v-if="formError"
              type="error"
              density="compact"
              class="mb-2"
            >
              {{ formError }}
            </v-alert>
          </template>
          <template v-else>
            <p class="mb-3">
              {{ toRecall.length }} Media record{{ toRecall.length === 1 ? '' : 's' }} to recall. Click a
              thumbnail to see the full size.
            </p>
            <v-table id="recall-summary" density="compact" class="mb-4">
              <thead>
                <tr><th /><th>Media CSID</th><th>Blob CSID</th><th>Kind</th><th>Served today</th><th>Found in</th><th>You gave</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in summary.records" :key="r.media_csid" :class="{'text-disabled': r.recalled}">
                  <td>
                    <span v-if="r.kind === '3D'" class="preview-placeholder">3D</span>
                    <button
                      v-else
                      type="button"
                      class="preview-button"
                      :aria-label="`Full size of ${r.media_csid}`"
                      @click="openFull(r)"
                    >
                      <img
                        v-if="!broken[r.media_csid]"
                        class="thumbnail"
                        :src="api.previewUrl(museum, r.media_csid)"
                        alt=""
                        @error="broken[r.media_csid] = true"
                      >
                      <span v-else class="preview-placeholder">{{ r.kind === 'pdf' ? 'PDF' : 'No preview' }}</span>
                    </button>
                  </td>
                  <td><ShortCsid :csid="r.media_csid" label="Media CSID" /></td>
                  <td>
                    <div v-for="blob in r.blob_csids" :key="blob"><ShortCsid :csid="blob" label="Blob CSID" /></div>
                  </td>
                  <td>{{ r.kind ? kindWord(r.kind) : 'not known' }}</td>
                  <td>{{ r.recalled ? 'already recalled' : r.served_today ? 'yes' : 'no' }}</td>
                  <td>{{ r.source === 'serena' ? 'Serena' : 'CollectionSpace (not served today)' }}</td>
                  <td>
                    <div v-for="given in r.entered" :key="given">
                      <ShortCsid v-if="isCsid(given)" :csid="given" label="CSID" />
                      <template v-else>{{ given }}</template>
                    </div>
                  </td>
                </tr>
              </tbody>
            </v-table>
            <template v-if="summary.not_found.length">
              <p class="mb-1">Not recalled:</p>
              <ul id="recall-not-found" class="mb-4 ml-6">
                <li v-for="n in summary.not_found" :key="n.csid">{{ n.csid }}: {{ n.message }}</li>
              </ul>
            </template>
            <v-textarea
              v-if="toRecall.length"
              id="recall-reason"
              v-model="reason"
              label="Reason (required)"
              rows="2"
            />
            <v-alert
              v-if="formError"
              type="error"
              density="compact"
              class="mb-2"
            >
              {{ formError }}
            </v-alert>
          </template>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="form = false">Cancel</v-btn>
          <v-btn
            v-if="summary"
            id="recall-change"
            variant="outlined"
            @click="summary = null"
          >
            Change CSIDs
          </v-btn>
          <v-btn
            v-if="!summary"
            id="recall-summarize"
            color="primary"
            variant="flat"
            :loading="busy"
            @click="summarize"
          >
            Preview recall
          </v-btn>
          <v-btn
            v-else-if="toRecall.length"
            id="recall-confirm"
            color="error"
            variant="flat"
            :loading="busy"
            :disabled="!reason.trim()"
            @click="confirm"
          >
            Recall {{ toRecall.length }} Media record{{ toRecall.length === 1 ? '' : 's' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="full" max-width="1200">
      <v-card v-if="fullRecord">
        <v-card-title>{{ fullRecord.media_csid }}</v-card-title>
        <v-card-text>
          <a
            v-if="fullRecord.kind === 'pdf'"
            id="full-pdf"
            :href="api.previewUrl(museum, fullRecord.media_csid, 'full')"
            target="_blank"
            rel="noopener"
          >Open the document</a>
          <img
            v-else
            id="full-image"
            class="full-image"
            :src="api.previewUrl(museum, fullRecord.media_csid, 'full')"
            alt=""
          >
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn variant="outlined" @click="full = false">Close</v-btn></v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Release (a recall a refresh kept, D119) and Cancel recall (one no refresh has decided yet, D148) share it. -->
    <v-dialog v-model="ending" max-width="560">
      <v-card>
        <v-card-title>{{ endMode === 'release' ? 'Release a recall' : 'Cancel a recall' }}</v-card-title>
        <v-card-text>
          <p v-if="endMode === 'release'" class="mb-3">
            Refresh {{ endOf?.kept_by }} still lists Media record {{ endOf?.media_csid }} as public. Release the
            recall only if CollectionSpace is right and the file should be served again.
          </p>
          <p v-else class="mb-3">
            No refresh has decided the recall of Media record {{ endOf?.media_csid }} yet. Cancel it only if it was a
            mistake: Serena serves its files again at once.
          </p>
          <v-textarea
            :id="`${endMode}-reason`"
            v-model="endReason"
            label="Reason (required)"
            rows="2"
          />
          <v-alert v-if="formError" type="error" density="compact">{{ formError }}</v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="outlined" @click="ending = false">Keep the recall</v-btn>
          <v-btn
            :id="`${endMode}-confirm`"
            color="error"
            variant="flat"
            :loading="busy"
            :disabled="!endReason.trim()"
            @click="confirmEnd"
          >
            {{ endMode === 'release' ? 'Release' : 'Cancel recall' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script setup lang="ts">
import {computed, onActivated, reactive, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {EndedRecall, Recall, RecallRecord, RecallSummary, RecallsPage} from '@/api'
import {api, problem} from '@/api'
import FileDialog from '@/components/FileDialog.vue'
import type {ShownFile} from '@/components/FileDialog.vue'
import ColumnHeader from '@/components/ColumnHeader.vue'
import CopyButton from '@/components/CopyButton.vue'
import FileLink from '@/components/FileLink.vue'
import LoadError from '@/components/LoadError.vue'
import RecordName from '@/components/RecordName.vue'
import RefreshLink from '@/components/RefreshLink.vue'
import ShortCsid from '@/components/ShortCsid.vue'
import WhenText from '@/components/WhenText.vue'
import {PAGE_SIZES, actorOf, isCsid, kindWord} from '@/words'
import {useTableState} from '@/tableState'

// The state as a tag, and the one action a recall allows in its own column at the right (D155).
// Each row opens (▸) to show its Media CSID and Blob CSID; the first column names the record as staff know it, by its
// identification number (Richard, October 14, 2026).
const NUMBER_HELP = 'The Media record\'s identification number in CollectionSpace, read when it was recalled (its shortened Media CSID if it has none). ▸ shows its Media CSID and Blob CSID.'
const activeHeaders = [
  {title: '', key: 'data-table-expand', sortable: false},
  {title: 'Identification number', key: 'identification_number', help: NUMBER_HELP,
   value: (r: Recall) => r.identification_number || r.media_csid},
  {title: 'Recalled (UTC)', key: 'at', help: 'When the admin recalled it.'},
  {title: 'By', key: 'by', help: 'The admin who recalled it.'},
  {title: 'Reason', key: 'reason', help: 'The reason the admin gave.'},
  {title: 'State', key: 'kept_by', help: 'Waiting for a later refresh: no refresh has decided it yet, so it can be cancelled. Still public in CollectionSpace: a refresh on a later day still listed the file as public, so the recall stays until it\'s released.'},
  {title: '', key: 'actions', sortable: false, align: 'end' as const}
]
const endedHeaders = [
  {title: '', key: 'data-table-expand', sortable: false},
  {title: 'Identification number', key: 'identification_number', help: NUMBER_HELP,
   value: (r: EndedRow) => r.identification_number || r.media_csid},
  {title: 'Ended (UTC)', key: 'at', help: 'When the recall ended.'},
  {title: 'How', key: 'action', help: 'Ended by a refresh (its servable list no longer had the file as public), released, or cancelled.'},
  {title: 'By', key: 'by', help: 'The admin who released or cancelled it, or Serena for a refresh.'},
  {title: 'Why', key: 'details', sortable: false, help: 'The admin\'s reason, or why the refresh ended it.'}
]

const route = useRoute()
// Each table's place in the address (October 14, 2026): a.sort, a.page, … and e.sort, e.page, ….
const activeTable = useTableState('a.', 'at')
const endedTable = useTableState('e.', 'at')
// Kept alive, one per museum (App.vue): always this museum's, whichever page the address shows now.
const ownMuseum = String(route.params.museum)
const museum = computed(() => ownMuseum)
const shownFile = ref<ShownFile | null>(null)

// A Media record's or Blob's CSID opens its file, the largest size the museum serves, in a dialog (D145), titled
// "Media CSID" or "Blob CSID" above the CSID: a CSID shown next to a label is always called that.
function openCsid(csid: string, what: 'Media CSID' | 'Blob CSID') {
  shownFile.value = {
    title: what,
    name: csid,
    url: what === 'Blob CSID' ? api.blobPreviewUrl(museum.value, csid, 'full') : api.previewUrl(museum.value, csid, 'full'),
    lookup: csid
  }
}
const page = ref<RecallsPage | null>(null)
const openActive = ref<string[]>([])
const openEnded = ref<string[]>([])

// An ended recall's row: its audit entry, with the identification number and Blobs it recorded.
type EndedRow = EndedRecall & {row_key: string, identification_number: string | null}
const ended = computed<EndedRow[]>(() => (page.value?.ended || []).map(e => ({
  ...e, row_key: `${e.at}#${e.media_csid}`,
  identification_number: typeof e.details.identification_number === 'string' ? e.details.identification_number : null
})))

function blobsOf(row: EndedRow): string[] {
  const blobs = row.details.blob_csids
  return Array.isArray(blobs) ? blobs.filter((b): b is string => typeof b === 'string') : []
}

function numberOrCsid(row: {identification_number: string | null, media_csid: string}): string {
  return row.identification_number || row.media_csid
}
const loading = ref(false)
const error = ref('')

const form = ref(false)
const box = ref('')
const file = ref<File | File[] | null>(null)
const summary = ref<RecallSummary | null>(null)
const reason = ref('')
const busy = ref(false)
const formError = ref('')
const broken = reactive<Record<string, boolean>>({})
const full = ref(false)
const fullRecord = ref<RecallRecord | null>(null)
const ending = ref(false)
const endMode = ref<'release' | 'cancel'>('release')
const endOf = ref<Recall | null>(null)
const endReason = ref('')
let sent = ''

const toRecall = computed(() => (summary.value?.records || []).filter(r => !r.recalled))

async function load() {
  loading.value = true
  error.value = ''
  try {
    page.value = await api.recalls(museum.value)
  } catch (e) {
    error.value = problem(e)
  } finally {
    loading.value = false
  }
}

watch(museum, load, {immediate: true})

function openForm() {
  box.value = ''
  file.value = null
  summary.value = null
  reason.value = ''
  formError.value = ''
  form.value = true
}

async function textToSend(): Promise<string | null> {
  const chosen = Array.isArray(file.value) ? file.value[0] : file.value
  if (chosen) {
    return chosen.text()
  }
  const count = box.value.split(/[\s,]+/).filter(Boolean).length
  const most = page.value?.max_in_box || 12
  if (count > most) {
    formError.value = `More than ${most} CSIDs: use a text file instead.`
    return null
  }
  return box.value
}

async function summarize() {
  formError.value = ''
  const text = await textToSend()
  if (text === null) {
    return
  }
  if (!text.trim()) {
    formError.value = 'Give at least one Media or Blob CSID.'
    return
  }
  busy.value = true
  try {
    sent = text
    summary.value = await api.recallSummary(museum.value, text)
  } catch (e) {
    formError.value = problem(e)
  } finally {
    busy.value = false
  }
}

async function confirm() {
  busy.value = true
  formError.value = ''
  try {
    await api.recall(museum.value, sent, reason.value.trim())
    form.value = false
    await load()
  } catch (e) {
    formError.value = problem(e)
  } finally {
    busy.value = false
  }
}

function openFull(record: RecallRecord) {
  fullRecord.value = record
  full.value = true
}

function openEnd(recall: Recall, mode: 'release' | 'cancel') {
  endMode.value = mode
  endOf.value = recall
  endReason.value = ''
  formError.value = ''
  ending.value = true
}

async function confirmEnd() {
  if (!endOf.value) {
    return
  }
  busy.value = true
  formError.value = ''
  try {
    const end = endMode.value === 'release' ? api.release : api.cancelRecall
    await end(museum.value, endOf.value.media_csid, endReason.value.trim())
    ending.value = false
    await load()
  } catch (e) {
    formError.value = problem(e)
  } finally {
    busy.value = false
  }
}

// Kept alive (App.vue): coming back shows it as it was, with any change since.
let shown = false
onActivated(() => {
  if (shown) {
    void load()
  }
  shown = true
})
</script>

<style scoped>
.row-expand {
  width: 24px;
  height: 24px;
  border: 1px solid rgba(var(--v-border-color), 0.35);
  border-radius: 4px;
  background: none;
  color: inherit;
  cursor: pointer;
  font-size: 0.75rem;
}
.row-detail {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 14px;
  margin: 2px 0 6px;
  font-size: 0.85rem;
}
.row-detail dt {
  color: rgba(var(--v-theme-on-surface), 0.6);
}
.mono {
  font-family: monospace;
}

/* One size for every thumbnail, so the summary's rows line up whatever the files' shapes. */
.thumbnail {
  width: 96px;
  height: 72px;
  object-fit: cover;
  border-radius: 4px;
  display: block;
}

.full-image {
  max-width: 100%;
  display: block;
}

.preview-button {
  background: none;
  border: 0;
  padding: 0;
  cursor: zoom-in;
}

.preview-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 96px;
  height: 72px;
  border: 1px solid rgba(0, 0, 0, 0.2);
  text-align: center;
  font-size: 0.8rem;
}
</style>
