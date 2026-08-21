import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Only for `npm run dev` on the host. In containers nginx does this, so the
    // session cookie is same-origin in development exactly as it is in production.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
