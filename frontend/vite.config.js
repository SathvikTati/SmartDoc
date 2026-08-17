import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 5173,
    // Calls go to /api/* and are proxied to FastAPI, so the browser only
    // ever talks to one origin in development. The backend also sets CORS
    // headers, which is what a separately-hosted production build needs.
    proxy: {
      '/api': {
        target: process.env.PORT6_API_URL ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
