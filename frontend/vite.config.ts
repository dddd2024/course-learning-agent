import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
//
// ERR_NETWORK fix: the dev server now binds to 127.0.0.1 (matching the
// uvicorn bind in start_windows.ps1) and proxies /api to
// http://127.0.0.1:8000. Combined with API_BASE_URL='/api/v1' (see
// src/config/api.ts), all business requests from the browser are
// same-origin (http://127.0.0.1:5173/api/v1/...) so Authorization
// headers no longer trigger cross-origin preflight — this was the root
// cause of the /logs ERR_NETWORK-with-token failure.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
