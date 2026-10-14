<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap ga-4 mb-4">
      <h1 id="page-title" class="text-h5">{{ museumName(museum) }} Recalls</h1>
      <v-spacer />
      <v-btn id="recall" color="error" @click="openForm">Recall…</v-btn>
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
      :sort-by="[{key: 'at', order: 'desc'}]"
      must-sort
      :items-per-page="25"
      :items-per-page-options="PAGE_SIZES"
      :loading="loading"
      item-value="media_csid"
      density="compact"
      no-data-text="No active recalls."
      class="mb-6"
    >
      <template #[`item.media_csid`]="{item}">
        <FileLink class="recall-csid" @open="openCsid(item.media_csid, 'Media CSID')">{{ item.media_csid }}</FileLink>
      </template>
      <template #[`item.blob_csids`]="{item}">
        <span v-for="(blob, i) in item.blob_csids" :key="blob"><template v-if="i">, </template>
          <FileLink class="recall-csid" @open="openCsid(blob, 'Blob CSID')">{{ blob }}</FileLink></span>
      </template>
      <template #[`item.at`]="{item}"><span class="text-no-wrap">{{ when(item.at) }}</span></template>
      <template #[`item.kept_by`]="{item}">
        <template v-if="item.kept_by">
          <span class="text-error">Still public in CollectionSpace</span> (refresh {{ item.kept_by }})
          <v-btn
            class="release ml-2"
            size="small"
            variant="outlined"
            @click="openEnd(item, 'release')"
          >
            Release
          </v-btn>
        </template>
        <template v-else>
          Waiting for a later refresh
          <v-btn
            class="cancel-recall ml-2"
            size="small"
            variant="outlined"
            @click="openEnd(item, 'cancel')"
          >
            Cancel recall
          </v-btn>
        </template>
      </template>
    </v-data-table>

    <h2 class="text-h6 mb-2">Ended in the last {{ page?.days || 30 }} days</h2>
    <v-data-table
      id="ended-recalls"
      :headers="endedHeaders"
      :items="page?.ended || []"
      :sort-by="[{key: 'at', order: 'desc'}]"
      must-sort
      :items-per-page="25"
      :items-per-page-options="PAGE_SIZES"
      density="compact"
      no-data-text="None."
    >
      <template #[`item.at`]="{item}"><span class="text-no-wrap">{{ when(item.at) }}</span></template>
      <template #[`item.action`]="{item}">
        {{ item.action === 'recall_release' ? 'Released' : item.action === 'recall_cancel' ? 'Cancelled' : 'Ended by a refresh' }}
      </template>
      <template #[`item.media_csid`]="{item}">
        <FileLink class="recall-csid" @open="openCsid(item.media_csid, 'Media CSID')">{{ item.media_csid }}</FileLink>
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
                  <td>{{ r.media_csid }}</td>
                  <td>{{ r.blob_csids.join(', ') }}</td>
                  <td>{{ r.kind ? kindWord(r.kind) : 'not known' }}</td>
                  <td>{{ r.recalled ? 'already recalled' : r.served_today ? 'yes' : 'no' }}</td>
                  <td>{{ r.source === 'serena' ? 'Serena' : 'CollectionSpace (not served today)' }}</td>
                  <td>{{ r.entered.join(', ') }}</td>
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
          <v-btn @click="form = false">Cancel</v-btn>
          <v-btn v-if="summary" @click="summary = null">Back</v-btn>
          <v-btn
            v-if="!summary"
            id="recall-summarize"
            color="primary"
            :loading="busy"
            @click="summarize"
          >
            Preview recall
          </v-btn>
          <v-btn
            v-else-if="toRecall.length"
            id="recall-confirm"
            color="error"
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
        <v-card-actions><v-spacer /><v-btn @click="full = false">Close</v-btn></v-card-actions>
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
          <v-btn @click="ending = false">Keep the recall</v-btn>
          <v-btn
            :id="`${endMode}-confirm`"
            color="primary"
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
import {computed, reactive, ref, watch} from 'vue'
import {useRoute} from 'vue-router'
import {museumName} from '@/session'
import type {Recall, RecallRecord, RecallSummary, RecallsPage} from '@/api'
import {api, problem} from '@/api'
import FileDialog from '@/components/FileDialog.vue'
import type {ShownFile} from '@/components/FileDialog.vue'
import FileLink from '@/components/FileLink.vue'
import LoadError from '@/components/LoadError.vue'
import {PAGE_SIZES, kindWord, when} from '@/words'

const activeHeaders = [
  {title: 'Media CSID', key: 'media_csid'},
  {title: 'Blob CSID', key: 'blob_csids', sortable: false},
  {title: 'Recalled by', key: 'by'},
  {title: 'When (UTC)', key: 'at'},
  {title: 'Reason', key: 'reason'},
  {title: 'State', key: 'kept_by'}
]
const endedHeaders = [
  {title: 'Media CSID', key: 'media_csid'},
  {title: 'When (UTC)', key: 'at'},
  {title: 'Ended by', key: 'by'},
  {title: 'How', key: 'action'},
  {title: 'Why', key: 'details', sortable: false}
]

const route = useRoute()
const museum = computed(() => String(route.params.museum))
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
</script>

<style scoped>
.thumbnail {
  max-width: 96px;
  max-height: 96px;
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
  display: inline-block;
  min-width: 64px;
  padding: 8px;
  border: 1px solid rgba(0, 0, 0, 0.2);
  text-align: center;
  font-size: 0.8rem;
}
</style>
