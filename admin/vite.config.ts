import {URL, fileURLToPath} from 'node:url'
import vue from '@vitejs/plugin-vue'
import vuetify, {transformAssetUrls} from 'vite-plugin-vuetify'
import {defineConfig} from 'vitest/config'

// Served by Serena under /admin, its API under /admin/v1 (design: Admin web app). In development the app runs on
// Vite's dev server and forwards /admin/v1 to Serena's FastAPI app, so the cookies stay same-origin.
export default defineConfig({
  base: '/admin/',
  plugins: [
    vue({
      template: {transformAssetUrls}
    }),
    // Components are registered by hand in src/plugins/vuetify.ts, as in BOA and the BMU.
    vuetify({
      autoImport: false
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    // Swagger UI (the API documentation page, F6) is one lazily loaded chunk of about 1.4 MB.
    chunkSizeWarningLimit: 1600
  },
  server: {
    host: true,
    port: 5373,
    proxy: {'/admin/v1': {target: process.env.VITE_API_TARGET || 'http://localhost:8300', changeOrigin: false}}
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/browser.ts', './src/__tests__/setup.ts'],
    server: {deps: {inline: ['vuetify']}}
  }
})
