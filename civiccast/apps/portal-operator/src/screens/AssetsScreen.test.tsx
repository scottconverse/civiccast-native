import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { AssetRow } from '../types/asset'

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
  listStaffAssets: vi.fn(),
  packageStaffAsset: vi.fn(),
  getStaffIdentity: vi.fn(),
  getReadinessDashboard: vi.fn(),
}))

import {
  getReadinessDashboard,
  getStaffIdentity,
  listStaffAssets,
  packageStaffAsset,
} from '../api/client'
import { AssetsScreen } from './AssetsScreen'

afterEach(cleanup)

function asset(assetId: string): AssetRow {
  return {
    asset_id: assetId,
    title: 'Scheduled recording 2026-06-28 15:44 UTC',
    description: null,
    meeting_body: null,
    state: 'recorded',
    manifest_url: null,
    published_at: null,
    file_path: `/recordings/${assetId}.ts`,
    file_size_bytes: 45_000_000,
    duration_seconds: 45,
    codec_video: 'h264',
    codec_audio: 'aac',
    width_px: 1280,
    height_px: 720,
    bitrate_bps: null,
    format_name: 'mpegts',
    trim_in_seconds: null,
    trim_out_seconds: null,
    chapters: [],
    retention_policy: 'default',
    retention_until: null,
    version: 1,
    source_live_session_id: null,
  }
}

function renderScreen(onOpenAsset = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <AssetsScreen onOpenAsset={onOpenAsset} />
      </QueryClientProvider>,
    ),
    onOpenAsset,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listStaffAssets).mockResolvedValue([
    asset('asset-public'),
    asset('asset-education'),
  ])
  vi.mocked(getStaffIdentity).mockResolvedValue({
    operator_id: 'publisher',
    operator_display_name: 'Publisher',
    roles: ['publish_operator'],
  })
  vi.mocked(getReadinessDashboard).mockResolvedValue({
    total_assets: 0,
    ready_count: 0,
    transcoding_count: 0,
    missing_count: 0,
    rejected_count: 0,
    by_asset: [],
  })
})

describe('AssetsScreen action labels', () => {
  it('keeps same-title recording detail buttons distinguishable by asset id', async () => {
    const { findByRole, onOpenAsset } = renderScreen()

    const publicButton = await findByRole('button', {
      name: /Open detail for Scheduled recording 2026-06-28 15:44 UTC \(asset-public\)/,
    })
    const educationButton = await findByRole('button', {
      name: /Open detail for Scheduled recording 2026-06-28 15:44 UTC \(asset-education\)/,
    })

    fireEvent.click(educationButton)

    expect(publicButton).toBeTruthy()
    expect(onOpenAsset).toHaveBeenCalledWith('asset-education')
  })

  it('lets an operator package validated media for resident playback', async () => {
    const row = { ...asset('sample-asset'), state: 'validated' as const }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    vi.mocked(packageStaffAsset).mockResolvedValue({
      ...row,
      manifest_url: 'http://127.0.0.1:8000/media/vod/sample-asset/playlist.m3u8',
    })
    const { findByRole } = renderScreen()

    fireEvent.click(
      await findByRole('button', {
        name: /Package Scheduled recording .*sample-asset.* for resident playback/,
      }),
    )

    await waitFor(() => expect(packageStaffAsset).toHaveBeenCalledWith('sample-asset'))
  })

  it('shows but disables packaging when the signed-in role cannot package media', async () => {
    const row = { ...asset('sample-asset'), state: 'validated' as const }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'clerk',
      operator_display_name: 'Records clerk',
      roles: ['records_clerk'],
    })
    const { findByRole, findByText } = renderScreen()

    const action = await findByRole('button', {
      name: /Package Scheduled recording .*sample-asset.* for resident playback/,
    })

    expect(action.hasAttribute('disabled')).toBe(true)
    expect(await findByText(/publish operator or setup administrator must package/i)).toBeTruthy()
  })
})

describe('AssetsScreen readiness badges (S7)', () => {
  it('shows a readiness badge for an asset the dashboard reports', async () => {
    vi.mocked(getReadinessDashboard).mockResolvedValue({
      total_assets: 2,
      ready_count: 1,
      transcoding_count: 1,
      missing_count: 0,
      rejected_count: 0,
      by_asset: [
        {
          asset_id: 'asset-public',
          title: 'x',
          readiness_state: 'ready',
          readiness_reason: null,
          in_flight_jobs_count: 0,
        },
        {
          asset_id: 'asset-education',
          title: 'x',
          readiness_state: 'transcoding',
          readiness_reason: null,
          in_flight_jobs_count: 2,
        },
      ],
    })
    const { findByText } = renderScreen()

    expect(await findByText('Ready')).toBeTruthy()
    expect(await findByText(/Transcoding \(2\)/)).toBeTruthy()
  })

  it('falls back to a dash when the dashboard has no row for an asset', async () => {
    vi.mocked(getReadinessDashboard).mockResolvedValue({
      total_assets: 0,
      ready_count: 0,
      transcoding_count: 0,
      missing_count: 0,
      rejected_count: 0,
      by_asset: [],
    })
    const { findAllByText } = renderScreen()

    const dashes = await findAllByText('—')
    expect(dashes.length).toBeGreaterThan(0)
  })

  it('does not break the asset list when the readiness dashboard request fails', async () => {
    vi.mocked(getReadinessDashboard).mockRejectedValue(new Error('boom'))
    const { findByRole } = renderScreen()

    // The primary asset list still renders even though the secondary
    // readiness signal failed -- readiness is best-effort, not a hard
    // dependency of the library screen.
    expect(
      await findByRole('button', {
        name: /Open detail for Scheduled recording 2026-06-28 15:44 UTC \(asset-public\)/,
      }),
    ).toBeTruthy()
  })
})
