import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Standalone so the production tsc build (tsconfig.node.json includes only
// vite.config.ts) never type-checks vitest's nested-vite types. Unit/component
// tests: `npm run test:unit`.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test-setup.ts'],
  },
})
