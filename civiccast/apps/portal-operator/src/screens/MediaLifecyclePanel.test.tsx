import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ToastContext } from '../components/toast-context'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getAssetReadiness: vi.fn(),
  setAssetLegalHold: vi.fn(),
  replaceAssetSource: vi.fn(),
}))

import { getAssetReadiness, replaceAssetSource, setAssetLegalHold } from '../api/client'
import type { AssetReadinessResponse } from '../types/api.generated'
import { MediaLifecyclePanel } from './MediaLifecyclePanel'

afterEach(cleanup)

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const push = vi.fn()
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ToastContext.Provider value={{ push }}>
          <MediaLifecyclePanel assetId="asset-1" />
        </ToastContext.Provider>
      </QueryClientProvider>,
    ),
    push,
  }
}

function baseReadiness(overrides: Partial<AssetReadinessResponse> = {}): AssetReadinessResponse {
  return {
    asset_id: 'asset-1',
    readiness_state: 'ready',
    readiness_reason: null,
    loudness_status: 'ok',
    measured_lufs: -16.2,
    in_flight_transcode_jobs: [],
    archive_complete: false,
    archive_portal_verified: true,
    archive_ia_verified: false,
    archive_nas_verified: false,
    legal_hold: false,
    updated_at: '2026-08-21T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MediaLifecyclePanel', () => {
  it('shows readiness state, loudness, and archive tiers', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(baseReadiness())
    const { findByText } = renderPanel()

    expect(await findByText('Ready')).toBeTruthy()
    expect(await findByText(/OK \(-16.2 LUFS\)/)).toBeTruthy()
    expect(await findByText('Not archive-complete yet')).toBeTruthy()
  })

  it('shows the archive-complete confirmation when all three tiers are verified', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(
      baseReadiness({ archive_complete: true, archive_ia_verified: true, archive_nas_verified: true }),
    )
    const { findByText } = renderPanel()
    expect(await findByText('✓ Archive-complete')).toBeTruthy()
  })

  it('does not place a legal hold until the operator confirms', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(baseReadiness())
    vi.mocked(setAssetLegalHold).mockResolvedValue(baseReadiness({ legal_hold: true }))
    const { findByRole } = renderPanel()

    fireEvent.click(await findByRole('button', { name: /Place legal hold/ }))
    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain('Place a legal hold on this asset?')
    expect(setAssetLegalHold).not.toHaveBeenCalled()

    fireEvent.click(await findByRole('button', { name: 'Place legal hold' }))
    await waitFor(() =>
      expect(setAssetLegalHold).toHaveBeenCalledWith('asset-1', { legal_hold: true, reason: null }),
    )
  })

  it('does not clear a legal hold until the operator confirms', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(baseReadiness({ legal_hold: true }))
    vi.mocked(setAssetLegalHold).mockResolvedValue(baseReadiness({ legal_hold: false }))
    const { findByRole } = renderPanel()

    fireEvent.click(await findByRole('button', { name: /Clear legal hold/ }))
    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain('Clear the legal hold on this asset?')
    expect(setAssetLegalHold).not.toHaveBeenCalled()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear legal hold' }))
    await waitFor(() =>
      expect(setAssetLegalHold).toHaveBeenCalledWith('asset-1', { legal_hold: false }),
    )
  })

  it('shows an error state when readiness fails to load', async () => {
    vi.mocked(getAssetReadiness).mockRejectedValue(new Error('boom'))
    const { findByRole } = renderPanel()
    expect(await findByRole('alert')).toBeTruthy()
  })

  it('does not replace the source file merely because a file was picked -- stages it, then requires confirm', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(baseReadiness())
    vi.mocked(replaceAssetSource).mockResolvedValue(baseReadiness())
    const { findByLabelText, findByRole } = renderPanel()

    const input = (await findByLabelText('Replacement video file')) as HTMLInputElement
    const file = new File(['content'], 'meeting-2026-08-30.mp4', { type: 'video/mp4' })
    fireEvent.change(input, { target: { files: [file] } })

    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain("Replace this asset's source file?")
    expect(dialog.textContent).toContain('meeting-2026-08-30.mp4')
    expect(replaceAssetSource).not.toHaveBeenCalled()

    fireEvent.click(await findByRole('button', { name: 'Replace source file' }))
    await waitFor(() => expect(replaceAssetSource).toHaveBeenCalledWith('asset-1', file))
  })

  it('replaces nothing when the operator cancels the staged file', async () => {
    vi.mocked(getAssetReadiness).mockResolvedValue(baseReadiness())
    const { findByLabelText, findByRole, queryByRole } = renderPanel()

    const input = (await findByLabelText('Replacement video file')) as HTMLInputElement
    const file = new File(['content'], 'meeting-2026-08-30.mp4', { type: 'video/mp4' })
    fireEvent.change(input, { target: { files: [file] } })

    await findByRole('alertdialog')
    fireEvent.click(await findByRole('button', { name: 'Cancel' }))

    expect(queryByRole('alertdialog')).toBeNull()
    expect(replaceAssetSource).not.toHaveBeenCalled()
  })
})
