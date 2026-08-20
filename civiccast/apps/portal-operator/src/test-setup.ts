// Global test setup: register testing-library's DOM cleanup after every test so
// renders never leak into the next test's document.body (vitest does not provide a
// global afterEach by default). New component tests get this for free.
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(cleanup)
