/**
 * "← Back to …" (Richard, October 14, 2026): a page reached through a link in the app (a path on Past requests, a
 * refresh ID on Alerts, a target on the Audit log) offers the way back to the page it came from, as it was left. A
 * page opened from the menu, the bell, the gear, a bookmark or a shared link has none. Each browser history entry
 * keeps its own (in history.state), so Back and Forward show the right one.
 */
import {ref} from 'vue'
import type {RouteLocationNormalized, Router} from 'vue-router'

export interface BackTo {
  path: string // the page's whole address, its filters, sort and page included (tableState.ts)
  title: string
}

/** What the link says, by the page it goes back to. */
const TITLES: Record<string, string> = {
  overview: 'Overview', refreshes: 'Past refreshes', 'manual-refresh': 'Manual refresh', alerts: 'Alerts',
  requests: 'Past requests', recalls: 'Recalls', lookup: 'Media look up', settings: 'Settings', audit: 'Audit log',
  api: 'API documentation'
}

/** The link the page being shown offers, or null. */
export const backTo = ref<BackTo | null>(null)

/** Set by the menu, the bell, the gear and the banner just before they navigate: a new task, nothing to go back to. */
export const navigation = {byMenu: false}

export function markMenuNavigation(): void {
  navigation.byMenu = true
}

/**
 * The way back for a new history entry: the page navigated from, unless the menu was used, either page is the
 * sign-in page, or it's another museum. Staying on the same page (a new look up, a filter) keeps the way back it had.
 */
export function backFor(to: RouteLocationNormalized, from: RouteLocationNormalized, byMenu: boolean,
  previous: BackTo | null): BackTo | null {
  if (byMenu || !from.name || from.meta.public || to.meta.public || to.params.museum !== from.params.museum) {
    return null
  }
  if (to.name === from.name) {
    return previous
  }
  const name = String(from.name)
  const title = name === 'refresh' ? `refresh ${String(from.params.refreshId)}` : TITLES[name]
  return title ? {path: from.fullPath, title} : null
}

const KEY = 'serenaBack'

/** Records each new history entry's way back in history.state, and shows the current entry's. */
export function trackBack(router: Router): void {
  let previous: BackTo | null = null
  router.beforeEach(() => {
    previous = (window.history.state?.[KEY] as BackTo | null | undefined) ?? null
    return true
  })
  router.afterEach((to, from, failure) => {
    const byMenu = navigation.byMenu
    navigation.byMenu = false
    if (failure) {
      return
    }
    const state = window.history.state || {}
    if (!(KEY in state)) {
      window.history.replaceState({...state, [KEY]: backFor(to, from, byMenu, previous)}, '')
    }
    backTo.value = (window.history.state?.[KEY] as BackTo | null) ?? null
  })
}

/** Back to the page: the browser's own Back when that's the entry before (it keeps the scroll position). */
export async function goBack(router: Router): Promise<void> {
  const target = backTo.value
  if (!target) {
    return
  }
  if (window.history.state?.back === target.path) {
    router.back()
  } else {
    await router.push(target.path)
  }
}
