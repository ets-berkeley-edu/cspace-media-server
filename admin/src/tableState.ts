/**
 * A list page's place in the address (Richard, October 14, 2026): its filters, and each table's sort, page and page
 * size, so coming back (Back, "← Back to …", or a shared link) shows the same view. Defaults are left out of the
 * address. The page reads the address once, when it's made; the app keeps list pages alive (App.vue), so returning
 * finds them as they were, scroll position included.
 */
import type {Ref} from 'vue'
import {reactive, ref, watch} from 'vue'
import type {LocationQuery} from 'vue-router'
import {useRoute, useRouter} from 'vue-router'

type Order = 'asc' | 'desc'

export interface TableState {
  sortBy: {key: string, order: Order}[]
  page: number
  itemsPerPage: number
}

const PAGE_SIZE = 25 // D92

function text(query: LocationQuery, name: string): string | null {
  const value = query[name]
  return typeof value === 'string' ? value : null
}

// The address a write has asked for and the router hasn't reached yet: two writes in one tick (Waiting, which also
// goes back to page 1) each start from it, so the second doesn't undo the first.
let pending: LocationQuery | null = null

/** Puts `changes` into the address in place (no new history entry), only while this page is the one shown. */
function useWriter() {
  const route = useRoute()
  const router = useRouter()
  const own = route.name
  return (changes: Record<string, string | null>) => {
    if (route.name !== own) {
      return // a kept-alive page out of sight: the address is another page's
    }
    const query: LocationQuery = {...(pending ?? route.query)}
    for (const [name, value] of Object.entries(changes)) {
      if (value === null) {
        delete query[name]
      } else {
        query[name] = value
      }
    }
    pending = query
    void router.replace({query}).finally(() => {
      if (pending === query) {
        pending = null
      }
    })
  }
}

/** A table's sort, page and page size, as `<prefix>sort=at.desc`, `<prefix>page=2`, `<prefix>rows=50`. */
export function useTableState(prefix: string, sortKey: string, order: Order = 'desc'): TableState {
  const route = useRoute()
  const write = useWriter()
  const [key, dir] = (text(route.query, `${prefix}sort`) || '').split('.')
  const state = reactive<TableState>({
    sortBy: [{key: key || sortKey, order: dir === 'asc' || dir === 'desc' ? dir : order}],
    page: Math.max(1, Number(text(route.query, `${prefix}page`)) || 1),
    itemsPerPage: Number(text(route.query, `${prefix}rows`)) || PAGE_SIZE
  })
  watch(() => [state.sortBy[0]?.key, state.sortBy[0]?.order, state.page, state.itemsPerPage], () => {
    const sort = state.sortBy[0]
    const isDefault = !sort || (sort.key === sortKey && sort.order === order)
    write({
      [`${prefix}sort`]: isDefault ? null : `${sort.key}.${sort.order}`,
      [`${prefix}page`]: state.page > 1 ? String(state.page) : null,
      [`${prefix}rows`]: state.itemsPerPage !== PAGE_SIZE ? String(state.itemsPerPage) : null
    })
  })
  return state
}

/** A page's filter (Past requests' range, outcome and reason), as `<name>=<value>`; the default is left out. */
export function useQueryValue<T extends string>(name: string, fallback: T, allowed?: readonly T[]): Ref<T> {
  const route = useRoute()
  const write = useWriter()
  const found = text(route.query, name) as T | null
  const state = ref(found !== null && (!allowed || allowed.includes(found)) ? found : fallback) as Ref<T>
  watch(state, value => write({[name]: value === fallback ? null : value}))
  return state
}
