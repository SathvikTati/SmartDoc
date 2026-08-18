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
  // The app never imports React itself, so JSX must compile to the
  // automatic runtime. The react plugin does this for the app build;
  // stating it here covers the test transform too.
  esbuild: { jsx: 'automatic' },

  // Rendering is what the build does not check. A page can compile
  // cleanly and still crash on its first render — a component given
  // children when it expected an `options` array, for instance.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.jsx'],
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
