// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Standalone so the production tsc build never type-checks vitest's nested-vite
// types. Unit/component tests: `npm run test:unit` (or invoke the vitest CLI
// directly per the slice 5 toolchain note).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test-setup.ts'],
  },
})
