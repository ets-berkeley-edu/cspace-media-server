/**
 * Runs before every test file: Vuetify for every mounted component, and a fresh session state. The tests stand in
 * for Serena's API by stubbing fetch.
 */
import {config} from '@vue/test-utils'
import {afterEach, beforeEach, vi} from 'vitest'
import vuetify from '@/plugins/vuetify'
import {session} from '@/session'

config.global.plugins = [vuetify]

beforeEach(() => {
  session.environment = ''
  session.signedIn = []
  session.loaded = false
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
