import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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
  getStaffAsset: vi.fn(),
  getStaffIdentity: vi.fn(),
  listStaffAssets: vi.fn(),
  unpublishStaffAsset: vi.fn(),
  updateStaffAsset: vi.fn(),
}))

// The detail editor also mounts MediaLifecyclePanel, OfflineCaptionJobsPanel
// and GenerateSummaryPanel, each with their own independent queries -- stub
// them out so this test stays focused on the unpublish confirm flow this
// finding is about.
vi.mock('./MediaLifecyclePanel', () => ({ MediaLifecyclePanel: () => null }))
vi.mock('./OfflineCaptionJobsPanel', () => ({ OfflineCaptionJobsPanel: () => null }))
vi.mock('./GenerateSummaryPanel', () => ({ GenerateSummaryPanel: () => null }))
vi.mock('./AssetCustomFieldsEditor', () => ({ AssetCustomFieldsEditor: () => null }))

import {
  getStaffAsset,
  getStaffIdentity,
  listStaffAssets,
  unpublishStaffAsset,
} from '../api/client'
import type { AssetRow } from '../types/asset'
import type { StaffIdentityResponse } from '../types/api.generated'
import { AssetDetailScreen } from './AssetDetailScreen'

afterEach(cleanup)

function assetFixture(overrides: Partial<AssetRow> = {}): AssetRow {
  return {
    asset_id: 'asset-1',
    title: 'City Council — Aug 30',
    description: null,
    meeting_body: 'City Council',
    state: 'validated',
    manifest_url: null,
    published_at: '2026-08-30T18:00:00Z',
    file_path: '/media/asset-1.mp4',
    file_size_bytes: 12_000_000,
    duration_seconds: 3600,
    codec_video: 'h264',
    codec_audio: 'aac',
    width_px: 1920,
    height_px: 1080,
    bitrate_bps: 4_000_000,
    format_name: 'mp4',
    trim_in_seconds: null,
    trim_out_seconds: null,
    chapters: [],
    retention_policy: 'default',
    retention_until: null,
    version: 1,
    source_live_session_id: null,
    ...overrides,
  }
}

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AssetDetailScreen assetId="asset-1" onClose={() => {}} onEditTrim={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
  vi.mocked(listStaffAssets).mockResolvedValue([])
})

describe('AssetDetailScreen unpublish uses the shared ConfirmDialog, not window.confirm', () => {
  it('does not unpublish on the first click, and does on confirm', async () => {
    vi.mocked(getStaffAsset).mockResolvedValue(assetFixture())
    vi.mocked(unpublishStaffAsset).mockResolvedValue(assetFixture({ published_at: null }))
    const confirmSpy = vi.spyOn(window, 'confirm')

    const { findByRole, queryByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Remove from portal' }))

    // window.confirm must never be invoked -- the shared, accessible
    // ConfirmDialog replaces it entirely.
    expect(confirmSpy).not.toHaveBeenCalled()
    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain('Remove "City Council — Aug 30" from the public portal?')
    expect(unpublishStaffAsset).not.toHaveBeenCalled()

    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove from portal' }))
    await waitFor(() => expect(unpublishStaffAsset).toHaveBeenCalledWith('asset-1'))
    await waitFor(() => expect(queryByRole('alertdialog')).toBeNull())
  })

  it('unpublishes nothing when the operator cancels', async () => {
    vi.mocked(getStaffAsset).mockResolvedValue(assetFixture())
    const { findByRole, queryByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Remove from portal' }))
    await findByRole('alertdialog')
    fireEvent.click(await findByRole('button', { name: 'Cancel' }))

    expect(queryByRole('alertdialog')).toBeNull()
    expect(unpublishStaffAsset).not.toHaveBeenCalled()
  })
})
