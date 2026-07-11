import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В dev фронтенд на порту 3080 проксирует запросы к API (порт 8080),
// чтобы не упираться в CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3080,
    proxy: {
      '/health': 'http://localhost:8080',
      '/system': 'http://localhost:8080',
      '/auth': 'http://localhost:8080',
    },
  },
})
