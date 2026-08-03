/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В dev фронтенд на порту 3080 проксирует запросы к API (порт 8080),
// чтобы не упираться в CORS.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Вендоры — отдельными кэшируемыми чанками (echarts/jspdf/html2canvas
        // уезжают в свои чанки автоматически за счёт динамического импорта).
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          grid: ['react-grid-layout', 'react-resizable'],
        },
      },
    },
  },
  server: {
    port: 3080,
    proxy: {
      '/health': 'http://localhost:8080',
      '/system': 'http://localhost:8080',
      '/auth': 'http://localhost:8080',
      '/objects': 'http://localhost:8080',
      '/folders': 'http://localhost:8080',
      '/document-versions': 'http://localhost:8080',
      '/extraction-jobs': 'http://localhost:8080',
      '/dataset-releases': 'http://localhost:8080',
      '/metrics': 'http://localhost:8080',
      '/dashboards': 'http://localhost:8080',
      '/dashboard-pages': 'http://localhost:8080',
      '/dashboard-templates': 'http://localhost:8080',
      '/widgets': 'http://localhost:8080',
      '/home': 'http://localhost:8080',
      '/users': 'http://localhost:8080',
      '/departments': 'http://localhost:8080',
      '/roles': 'http://localhost:8080',
      '/login-events': 'http://localhost:8080',
      '/reports': 'http://localhost:8080',
      '/audit': 'http://localhost:8080',
      '/moderation': 'http://localhost:8080',
      '/catalog': 'http://localhost:8080',
      '/notifications': 'http://localhost:8080',
      '/maintenance': 'http://localhost:8080',
      '/archive': 'http://localhost:8080',
      '/archive-access': 'http://localhost:8080',
      '/appeals': 'http://localhost:8080',
    },
  },
})
