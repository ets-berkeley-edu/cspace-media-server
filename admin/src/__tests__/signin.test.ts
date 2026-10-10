import {flushPromises, mount} from '@vue/test-utils'
import {describe, expect, it, vi} from 'vitest'
import {createMemoryHistory, createRouter} from 'vue-router'
import {fakeApi} from './fake'
import {routes} from '@/router'
import SignIn from '@/views/SignIn.vue'

async function mounted() {
  const router = createRouter({history: createMemoryHistory('/admin/'), routes})
  await router.push('/sign-in?museum=pahma')
  const wrapper = mount(SignIn, {global: {plugins: [router]}})
  await flushPromises()
  return {wrapper, router}
}

describe('sign-in', () => {
  it('signs in and opens the museum', async () => {
    const calls = fakeApi({
      'GET /museums': {body: [{key: 'pahma', name: 'PAHMA'}]},
      'POST /sessions': {body: {museum: 'pahma', name: 'PAHMA', user: 'admin'}},
      'GET /me': {body: {environment: 'Test', sessions: [{museum: 'pahma', name: 'PAHMA', user: 'admin'}]}}
    })
    const {wrapper, router} = await mounted()
    await wrapper.find('#username').setValue('admin')
    await wrapper.find('#password').setValue('pw-for-the-test')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(calls.find(c => c.method === 'POST')?.body).toEqual({museum: 'pahma', username: 'admin', password: 'pw-for-the-test'})
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/pahma'))
  })

  it('shows Serena\'s reason and clears the password', async () => {
    fakeApi({
      'GET /museums': {body: [{key: 'pahma', name: 'PAHMA'}]},
      'POST /sessions': {status: 403, body: {detail: 'Your PAHMA account doesn\'t have the Serena_Admin role.'}}
    })
    const {wrapper} = await mounted()
    await wrapper.find('#username').setValue('viewer')
    await wrapper.find('#password').setValue('pw-for-the-test')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('#sign-in-error').exists()).toBe(true))
    expect(wrapper.find('#sign-in-error').text()).toContain('Serena_Admin')
    expect((wrapper.find('#password').element as HTMLInputElement).value).toBe('')
  })
})
