import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    chunkSizeWarningLimit: 650,
  },
  server: {
    // Finding MINOR-2: portal-operator's dev server proxies /api to the
    // backend; this app had no proxy at all, so `npm run dev` here couldn't
    // reach a backend on a different port without a manual code change or a
    // CIVICCAST_CORS_ALLOWED_ORIGINS opt-in. Override the target with
    // VITE_CIVICCAST_API_PROXY_TARGET when the backend isn't on the default
    // loopback port (e.g. port 8000 is already in use — see README "Run
    // locally").
    proxy: {
      '/api': {
        target: process.env.VITE_CIVICCAST_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
