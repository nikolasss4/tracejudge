import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.TRACEJUDGE_BACKEND ?? 'http://127.0.0.1:7600'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // Served by `tracejudge serve` and shipped inside the Python package.
    outDir: '../src/tracejudge/static',
    emptyOutDir: true,
  },
  server: {
    proxy: { '/api': backend, '/v1': backend },
  },
})
