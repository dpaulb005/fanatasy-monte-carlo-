/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // Proxy API calls to Django in local dev so the frontend can use /api/v1
    // without CORS. VITE_API_BASE overrides this when set (e.g. in Docker).
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split the heavy charting library and other vendor code into their own
        // chunks so the initial app payload stays small and caches well.
        manualChunks(id: string) {
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    // Playwright specs live in e2e/ and must not be collected by vitest.
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
