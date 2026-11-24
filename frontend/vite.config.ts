import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Local only by default; Docker sets VITE_HOST=0.0.0.0 and publishes the port on localhost.
    host: process.env.VITE_HOST ?? 'localhost',
    port: 5180, // 5173 is often taken by other local Vite apps
    strictPort: true,
    // Behind a tunnel or reverse proxy, list the public hostname(s), comma-separated, e.g.
    // VITE_ALLOWED_HOSTS=hub.example.com. Unset keeps Vite's default (localhost only).
    allowedHosts: process.env.VITE_ALLOWED_HOSTS
      ? process.env.VITE_ALLOWED_HOSTS.split(',').map((h) => h.trim())
      : undefined,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: { environment: 'node' },
})
