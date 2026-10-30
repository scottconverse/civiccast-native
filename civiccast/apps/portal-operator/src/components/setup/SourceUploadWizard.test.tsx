// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

import { createSampleRehearsalUpload, createSetupLiveSource, getSourceSetup } from '../../api/client'
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

function renderWizard(props: Parameters<typeof SourceUploadWizard>[0] = {}) {
  vi.mocked(getSourceSetup).mockResolvedValue(report())
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SourceUploadWizard {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SourceUploadWizard manual link', () => {
  it('links the camera/test-media card into the manual\'s first-workflow walkthrough', async () => {
    renderWizard()
    const link = await screen.findByRole('link', { name: /read the full walkthrough in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#ch-before-meeting')
  })

  it('saves to the named selected channel and does not claim playback readiness', async () => {
    vi.mocked(createSetupLiveSource).mockResolvedValue({ status: 'ready', live_source_id: 'internal-source-123',
      source_type: 'rtsp', message: 'Council Room Camera is saved.', next_step: 'Run preflight.' })
    renderWizard({ defaultChannelId: 'gov-ch12', channels: [
      { channel_id: 'gov-ch12', display_name: 'Government Channel 12', purpose: 'Meetings' },
      { channel_id: 'education', display_name: 'Education Channel', purpose: 'Education' },
    ] })
    fireEvent.click(await screen.findByRole('button', { name: /Hardware encoder or AV system/i }))
    fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'education' } })
    fireEvent.change(screen.getByRole('textbox', { name: /Encoder stream address/ }), { target: { value: 'rtsp://encoder.example.local/live' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save meeting source' }))
    await waitFor(() => expect(createSetupLiveSource).toHaveBeenCalledWith({ kind: 'encoder',
      channel_id: 'education', label: 'Council Room Camera', endpoint: 'rtsp://encoder.example.local/live' }))
    expect(await screen.findByText('Saved: Council Room Camera')).toBeTruthy()
    expect(screen.queryByText(/internal-source-123/)).toBeNull()
    expect(screen.getByText('Saving media or a source does not prove playback or publish it.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Check broadcast readiness' }).getAttribute('href')).toBe('/health')
  })
})

it('routes the recorded sample to private readiness instead of a dead RTMP source', async () => {
  vi.mocked(createSampleRehearsalUpload).mockResolvedValue({ status: 'ready', title: 'CivicCast sample rehearsal', message: 'Sample recording created.', next_step: 'Check broadcast readiness.', live_source_id: null, source_type: null })
  renderWizard()
  fireEvent.click(await screen.findByRole('button', { name: /Bundled sample video/i }))
  fireEvent.click(screen.getByRole('button', { name: 'Create sample media' }))
  expect((await screen.findByRole('link', { name: 'Check broadcast readiness' })).getAttribute('href')).toBe('/health')
})
