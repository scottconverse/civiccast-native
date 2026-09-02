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
  uploadAssetFileWithProgress: vi.fn(),
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
    retention_term_unit: null,
    retention_term_value: null,
    retention_anchor_at: null,
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

describe('AssetsScreen status badges (S7 / candidate #17 second report)', () => {
  it('surfaces in-flight transcodes from the readiness dashboard on an unpackaged asset', async () => {
    vi.mocked(getReadinessDashboard).mockResolvedValue({
      total_assets: 2,
      ready_count: 0,
      transcoding_count: 1,
      missing_count: 0,
      rejected_count: 0,
      by_asset: [
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

    expect(await findByText(/Transcoding \(2\)/)).toBeTruthy()
  })

  it('still shows an honest derived status when the dashboard has no row for an asset', async () => {
    // The lifecycle worker not having run must not blank or falsify the
    // status column -- the asset row itself carries the truth.
    vi.mocked(getReadinessDashboard).mockResolvedValue({
      total_assets: 0,
      ready_count: 0,
      transcoding_count: 0,
      missing_count: 0,
      rejected_count: 0,
      by_asset: [],
    })
    const { findAllByText } = renderScreen()

    // Both fixture assets are recorded with no manifest: not servable yet.
    const badges = await findAllByText('Not servable yet')
    expect(badges.length).toBe(2)
  })

  it('does not break the asset list when the readiness dashboard request fails', async () => {
    vi.mocked(getReadinessDashboard).mockRejectedValue(new Error('boom'))
    const { findByRole, findAllByText } = renderScreen()

    // The primary asset list still renders even though the secondary
    // readiness signal failed -- readiness is best-effort, not a hard
    // dependency of the library screen.
    expect(
      await findByRole('button', {
        name: /Open detail for Scheduled recording 2026-06-28 15:44 UTC \(asset-public\)/,
      }),
    ).toBeTruthy()
    expect((await findAllByText('Not servable yet')).length).toBe(2)
  })

  it('shows Packaged for a validated+packaged asset even when the worker never computed readiness', async () => {
    // Candidate #17 field finding, second report: "an asset that is
    // ingest-Validated AND Packaged still shows 'Not ready'."
    const row = {
      ...asset('asset-public'),
      state: 'validated' as const,
      manifest_url: 'http://127.0.0.1:8000/media/vod/asset-public/playlist.m3u8',
    }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    vi.mocked(getReadinessDashboard).mockResolvedValue({
      total_assets: 1,
      ready_count: 0,
      transcoding_count: 0,
      missing_count: 0,
      rejected_count: 0,
      by_asset: [
        {
          asset_id: 'asset-public',
          title: 'x',
          readiness_state: 'not_ready',
          readiness_reason: 'Readiness has not been computed yet.',
          in_flight_jobs_count: 0,
        },
      ],
    })
    const { findByText, queryByText } = renderScreen()

    expect(await findByText('Packaged')).toBeTruthy()
    expect(queryByText('Not ready')).toBeNull()
  })

  it('shows Published for a published asset regardless of the readiness row', async () => {
    const row = {
      ...asset('asset-public'),
      state: 'validated' as const,
      manifest_url: 'http://127.0.0.1:8000/media/vod/asset-public/playlist.m3u8',
      published_at: '2026-08-01T12:00:00Z',
    }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    const { findByTitle, queryByText } = renderScreen()

    // findByText('Published') would collide with the table's "Published"
    // column header; the badge is uniquely identified by its detail tooltip.
    expect(await findByTitle('Live on the resident portal.')).toBeTruthy()
    expect(queryByText('Not ready')).toBeNull()
  })

  it('flags a missing backing file as an error state even on a published asset', async () => {
    const row = {
      ...asset('asset-public'),
      state: 'validated' as const,
      manifest_url: 'http://127.0.0.1:8000/media/vod/asset-public/playlist.m3u8',
      published_at: '2026-08-01T12:00:00Z',
      file_status: 'missing' as const,
    }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    const { findByText } = renderScreen()

    expect(await findByText('Missing file')).toBeTruthy()
  })

  it('labels an asset still in ingest validation as Validating, not "Not ready"', async () => {
    const row = { ...asset('asset-public'), state: 'pending_ingest' as const }
    vi.mocked(listStaffAssets).mockResolvedValue([row])
    const { findAllByText, queryByText } = renderScreen()

    // Badge label (the state filter tab also says "Analyzing"; the status
    // badge says "Validating").
    expect((await findAllByText('Validating')).length).toBeGreaterThan(0)
    expect(queryByText('Not ready')).toBeNull()
  })
})

describe('AssetsScreen upload control (S7 candidate #17 finding 1/2)', () => {
  it('offers an Upload video control -- the tester\'s exact "no upload button" complaint', async () => {
    const { findByRole } = renderScreen()
    expect(await findByRole('button', { name: 'Upload video' })).toBeTruthy()
  })

  it('points the empty state at the upload control that now actually exists on this screen', async () => {
    vi.mocked(listStaffAssets).mockResolvedValue([])
    const { findByText } = renderScreen()
    expect(await findByText(/Use Upload video above/)).toBeTruthy()
  })

  it('disables the upload form and explains why for an operator without an upload role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'dana',
      operator_display_name: 'Dana',
      roles: ['publish_operator'],
    })
    const { findByRole, findByText } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Upload video' }))

    expect(
      await findByText(
        'A records clerk, meeting operator, or support administrator role is required to upload video.',
      ),
    ).toBeTruthy()
  })
})
