import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'

function civicCastVersion() {
  if (process.env.VITE_CIVICCAST_VERSION) return process.env.VITE_CIVICCAST_VERSION
  const versionFile = readFileSync('../../_version.py', 'utf8')
  const match = versionFile.match(/__version__\s*=\s*"([^"]+)"/)
  return match?.[1] ?? 'dev'
}

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  define: {
    'import.meta.env.VITE_CIVICCAST_VERSION': JSON.stringify(civicCastVersion()),
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
