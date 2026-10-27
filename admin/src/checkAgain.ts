/**
 * Checking again while Serena works: a page showing a refresh that's checking or updating loads again every 5 seconds
 * until none is, so the worker's progress shows without a reload. A refresh's page has since issue #108; Past
 * refreshes and Overview since October 27, 2026. The page sends these loads as background requests, which don't count
 * as activity, so an open tab still signs out when idle. A page kept alive (App.vue) stops while another page is shown.
 */
import {onActivated, onBeforeUnmount, onDeactivated} from 'vue'

export const WORKING = ['checking', 'updating']
export const AGAIN_MS = 5000

export function working(refreshes: ({state: string} | null | undefined)[]): boolean {
  return refreshes.some(r => !!r && WORKING.includes(r.state))
}

/** Call what it returns after each load, saying whether a refresh shown is still working; `again` loads in the background. */
export function useCheckAgain(again: () => Promise<void>): (stillWorking: boolean) => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let shown = true
  function after(stillWorking: boolean) {
    clearTimeout(timer)
    timer = shown && stillWorking ? setTimeout(() => void again(), AGAIN_MS) : undefined
  }
  // Coming back, a kept-alive page loads again itself, and that load calls after().
  onActivated(() => { shown = true })
  onDeactivated(() => { shown = false; after(false) })
  onBeforeUnmount(() => { shown = false; after(false) })
  return after
}
