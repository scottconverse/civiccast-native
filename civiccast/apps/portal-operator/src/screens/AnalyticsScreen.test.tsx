// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { AnalyticsReport, RollupsResponse } from '../types/api.generated'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  vi.stubGlobal(
    'URL',
    Object.assign(URL, {
      createObjectURL: vi.fn(() => 'blob:mock'),
      revokeObjectURL: vi.fn(),
    }),
  )
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

vi.mock('../api/client', () => ({
  getAnalyticsReport: vi.fn(),
  getAnalyticsRollups: vi.fn(),
  downloadAnalyticsRollupsCsv: vi.fn(),
  generateAnalyticsBoardPdf: vi.fn(),
}))

import {
  downloadAnalyticsRollupsCsv,
  generateAnalyticsBoardPdf,
  getAnalyticsReport,
  getAnalyticsRollups,
} from '../api/client'
import { AnalyticsScreen } from './AnalyticsScreen'

function baseReport(overrides: Partial<AnalyticsReport> = {}): AnalyticsReport {
  return {
    generated_at: '2026-06-15T00:00:00Z',
    range_days: 30,
    asset_views: [],
    live_concurrent_viewers: [],
    geography: [],
    device_breakdown: [],
    platform_breakdown: [],
    caption_usage: [],
    audio_usage: [],
    subscription_growth: [],
    podcast_downloads: [],
    retained_fields: ['event_id'],
    privacy_boundary: 'aggregate-only-no-session-ip-or-viewer-identity',
    vod_rollups: [],
    live_rollups: [],
    year_over_year: [],
    ingest_configured: true,
    ...overrides,
  }
}

function emptyRollups(): RollupsResponse {
  return {
    rollups: [],
    stats: { total_viewer_count: 0, total_time_viewed_seconds: 0, peak_concurrent: null },
  }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AnalyticsScreen />
    </QueryClientProvider>,
  )
}

describe('AnalyticsScreen', () => {
  it('shows a loading state before the report resolves', () => {
    vi.mocked(getAnalyticsReport).mockReturnValue(new Promise(() => {}))
    vi.mocked(getAnalyticsRollups).mockReturnValue(new Promise(() => {}))
    const { getByText } = renderScreen()
    expect(getByText(/loading report/i)).toBeTruthy()
  })

  it('shows an error state when the report request fails', async () => {
    vi.mocked(getAnalyticsReport).mockRejectedValue(new Error('boom'))
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const { findByText } = renderScreen()
    expect(await findByText(/report unavailable/i)).toBeTruthy()
  })

  it('shows the honest telemetry-off banner when ingest is not configured', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport({ ingest_configured: false }))
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const { findByText } = renderScreen()
    expect(await findByText(/audience telemetry is off/i)).toBeTruthy()
  })

  it('does not show the telemetry-off banner when ingest is configured', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport({ ingest_configured: true }))
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const { findByText, queryByText } = renderScreen()
    await findByText(/privacy boundary/i)
    expect(queryByText(/audience telemetry is off/i)).toBeNull()
  })

  it('renders seeded rollup stats once loaded', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport())
    vi.mocked(getAnalyticsRollups).mockResolvedValue({
      rollups: [
        {
          stream_type: 'vod',
          bucket_kind: 'day',
          bucket_start: '2026-06-10T00:00:00Z',
          subject_id: 'asset-1',
          viewer_count: 5,
          time_viewed_seconds: 3600,
          peak_concurrent: null,
          avg_concurrent: null,
          samples: 0,
        },
      ],
      stats: { total_viewer_count: 5, total_time_viewed_seconds: 3600, peak_concurrent: null },
    })
    const { findAllByText } = renderScreen()
    const matches = await findAllByText((_, element) =>
      /5\s*views/i.test(element?.textContent ?? ''),
    )
    expect(matches.length).toBeGreaterThan(0)
  })

  it('expands the rollup data table on click', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport())
    vi.mocked(getAnalyticsRollups).mockResolvedValue({
      rollups: [
        {
          stream_type: 'vod',
          bucket_kind: 'day',
          bucket_start: '2026-06-10T00:00:00Z',
          subject_id: 'asset-1',
          viewer_count: 5,
          time_viewed_seconds: 3600,
          peak_concurrent: null,
          avg_concurrent: null,
          samples: 0,
        },
      ],
      stats: { total_viewer_count: 5, total_time_viewed_seconds: 3600, peak_concurrent: null },
    })
    const { findByRole, findAllByText } = renderScreen()
    const toggle = await findByRole('button', { name: /show rollup data table/i })
    fireEvent.click(toggle)
    await waitFor(async () => {
      expect((await findAllByText('asset-1')).length).toBeGreaterThan(0)
    })
  })

  it('downloads a CSV when Export CSV is clicked', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport())
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const blob = new Blob(['stream_type,bucket_kind'], { type: 'text/csv' })
    vi.mocked(downloadAnalyticsRollupsCsv).mockResolvedValue(blob)
    const { findByRole } = renderScreen()
    const button = await findByRole('button', { name: /export csv/i })
    fireEvent.click(button)

    await waitFor(() => {
      expect(vi.mocked(downloadAnalyticsRollupsCsv)).toHaveBeenCalled()
    })
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })

  it('opens the board-PDF checklist and generates on demand', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport())
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const blob = new Blob(['%PDF'], { type: 'application/pdf' })
    vi.mocked(generateAnalyticsBoardPdf).mockResolvedValue(blob)
    const { findByRole } = renderScreen()
    const openButton = await findByRole('button', { name: /generate board pdf/i })
    fireEvent.click(openButton)

    const downloadButton = await findByRole('button', { name: /download pdf/i })
    fireEvent.click(downloadButton)

    await waitFor(() => {
      expect(vi.mocked(generateAnalyticsBoardPdf)).toHaveBeenCalledWith(
        expect.objectContaining({
          include: { totals: true, top_content: true, yoy: true, live_peaks: true },
        }),
      )
    })
  })

  it('re-queries rollups when the stream-type toggle changes', async () => {
    vi.mocked(getAnalyticsReport).mockResolvedValue(baseReport())
    vi.mocked(getAnalyticsRollups).mockResolvedValue(emptyRollups())
    const { findByRole } = renderScreen()

    const liveButton = await findByRole('button', { name: 'live' })
    fireEvent.click(liveButton)

    await waitFor(() => {
      expect(vi.mocked(getAnalyticsRollups)).toHaveBeenCalledWith(
        expect.objectContaining({ streamType: 'live' }),
      )
    })
  })
})
