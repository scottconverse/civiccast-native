// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getSourceSetup: vi.fn(),
  createSampleRehearsalUpload: vi.fn(),
  createSetupLiveSource: vi.fn(),
  uploadAssetFile: vi.fn(),
}))

import { getSourceSetup } from '../../api/client'
import type { SourceSetupReport } from '../../types/api.generated'
import { SourceUploadWizard } from './SourceUploadWizard'

function report(overrides: Partial<SourceSetupReport> = {}): SourceSetupReport {
  return {
    generated_at: '2026-08-29T00:00:00Z',
    status: 'not_set_up',
    configured_source_count: 0,
    options: [],
    next_step: 'Choose a source.',
    ...overrides,
  }
}

function renderWizard() {
  vi.mocked(getSourceSetup).mockResolvedValue(report())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SourceUploadWizard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SourceUploadWizard manual link', () => {
  it('links the camera/test-media card into the manual\'s first-workflow walkthrough', async () => {
    renderWizard()
    const link = await screen.findByRole('link', { name: /read the full walkthrough in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#your-first-beta-workflow')
  })
})
