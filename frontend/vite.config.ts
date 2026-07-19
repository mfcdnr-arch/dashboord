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
    },
  },
})
