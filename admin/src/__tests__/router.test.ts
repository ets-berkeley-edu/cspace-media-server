import {describe, expect, it} from 'vitest'
import type {RouteLocationNormalized} from 'vue-router'
import {fakeApi} from './fake'
import {guard} from '@/router'

function to(name: string, museum?: string, isPublic = false): RouteLocationNormalized {
  return {name, params: museum ? {museum} : {}, meta: isPublic ? {public: true} : {}} as unknown as RouteLocationNormalized
}

describe('the route guard', () => {
  it('sends a museum page to sign-in when not signed in to that museum', async () => {
    fakeApi({'GET /me': {body: {environment: 'Test', sessions: [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]}}})
    expect(await guard(to('overview', 'pahma'))).toBe(true)
    expect(await guard(to('audit', 'cinefiles'))).toEqual({name: 'sign-in', query: {museum: 'cinefiles'}})
  })

  it('opens a signed-in museum from the home page', async () => {
    fakeApi({'GET /me': {body: {environment: 'Test', sessions: [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]}}})
    expect(await guard(to('home', undefined, true))).toEqual({name: 'overview', params: {museum: 'pahma'}})
    expect(await guard(to('sign-in', undefined, true))).toBe(true)
  })
})
