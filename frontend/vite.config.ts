import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

/**
 * The backend's published host port, from the repository's .env.
 *
 * Read rather than hardcoded because the port moves: another project on the
 * machine may already hold 8000, and `docker compose` takes BACKEND_PORT from
 * .env while this file previously did not. The result was `npm run dev`
 * proxying to a dead port and the API appearing broken only in dev mode —
 * one source of truth avoids repeating that.
 */
function backendPort(): string {
  try {
    const env = fs.readFileSync(path.resolve(__dirname, '../.env'), 'utf8')
    const match = env.match(/^\s*BACKEND_PORT\s*=\s*(\d+)/m)
    if (match) return match[1]
  } catch {
    // No .env (a fresh clone, or CI). The compose default is the right guess.
  }
  return '8000'
}

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
      '/api': `http://localhost:${backendPort()}`,
    },
  },
})
