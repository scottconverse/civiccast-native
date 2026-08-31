// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { OfflineCaptionJobRecord, StaffIdentityResponse } from '../types/api.generated'

afterEach(cleanup)

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
  getStaffIdentity: vi.fn(),
  listOfflineCaptionJobs: vi.fn(),
  retryOfflineCaptionJob: vi.fn(),
}))

import { ApiError, getStaffIdentity, listOfflineCaptionJobs, retryOfflineCaptionJob } from '../api/client'
import { OfflineCaptionJobsPanel, OfflineCaptionJobsView } from './OfflineCaptionJobsPanel'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function job(overrides: Partial<OfflineCaptionJobRecord> = {}): OfflineCaptionJobRecord {
  return {
    job_id: 'job-1',
    asset_id: 'asset-1',
    source_path: 'C:/media/asset-1.mp4',
    package_dir: 'C:/media/asset-1-captions',
    state: 'failed',
    attempts: 3,
    last_error: 'faster-whisper crashed: out of memory',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:05:00Z',
    ...overrides,
  }
}

function renderScreen(assetId = 'asset-1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OfflineCaptionJobsPanel assetId={assetId} />
    </QueryClientProvider>,
  )
}

describe('OfflineCaptionJobsView (presentational)', () => {
  it('shows an empty state when there are no jobs', () => {
    const { getByText } = render(
      <OfflineCaptionJobsView jobs={[]} canRetry onRetry={vi.fn()} />,
    )
    expect(getByText(/No offline caption jobs for this recording yet/i)).toBeTruthy()
  })

  it('renders a failed row with a Retry button and last_error', () => {
    const { getByRole, getByText } = render(
      <OfflineCaptionJobsView jobs={[job()]} canRetry onRetry={vi.fn()} />,
    )
    expect(getByText(/faster-whisper crashed: out of memory/i)).toBeTruthy()
    expect(getByRole('button', { name: /Retry offline caption job job-1/i })).toBeTruthy()
  })

  it('does not offer a Retry button for a non-failed job', () => {
    const { queryByRole } = render(
      <OfflineCaptionJobsView jobs={[job({ state: 'complete' })]} canRetry onRetry={vi.fn()} />,
    )
    expect(queryByRole('button', { name: /Retry offline caption job/i })).toBeNull()
  })

  it('disables Retry and explains the role gate when the operator cannot retry', () => {
    const { getByRole, getByText } = render(
      <OfflineCaptionJobsView jobs={[job()]} canRetry={false} onRetry={vi.fn()} />,
    )
    expect((getByRole('button', { name: /Retry offline caption job job-1/i }) as HTMLButtonElement).disabled).toBe(true)
    expect(getByText(/requires the records clerk role/i)).toBeTruthy()
  })

  it('shows a loading label while retrying and a success note after', () => {
    const { getByRole, rerender, getByText } = render(
      <OfflineCaptionJobsView jobs={[job()]} canRetry onRetry={vi.fn()} retryingJobId="job-1" />,
    )
    // The button's accessible name is its aria-label (job id), not its
    // visible text — query by that, then assert the loading label/state.
    const button = getByRole('button', {
      name: /Retry offline caption job job-1/i,
    }) as HTMLButtonElement
    expect(button.textContent).toContain('Retrying…')
    expect(button.disabled).toBe(true)

    rerender(
      <OfflineCaptionJobsView jobs={[job()]} canRetry onRetry={vi.fn()} retriedJobId="job-1" />,
    )
    expect(getByText(/Queued for retry\./i)).toBeTruthy()
  })

  it('shows a per-row retry error', () => {
    const { getByRole } = render(
      <OfflineCaptionJobsView
        jobs={[job()]}
        canRetry
        onRetry={vi.fn()}
        retryError={{ jobId: 'job-1', error: new ApiError('Request failed: 409', 409, 'Another job is active.') }}
      />,
    )
    expect(getByRole('alert').textContent).toContain('Another job is active.')
  })

  it('surfaces a list-load error', () => {
    const { getByRole } = render(
      <OfflineCaptionJobsView jobs={undefined} canRetry onRetry={vi.fn()} error={new Error('boom')} />,
    )
    expect(getByRole('alert').textContent).toContain('boom')
  })

  it('states plainly, up front, that approving publish is what starts this job (candidate #17 finding 5)', () => {
    const { getByText } = render(
      <OfflineCaptionJobsView jobs={[]} canRetry onRetry={vi.fn()} />,
    )
    expect(
      getByText("Approving this recording's portal surface on the Publish dashboard is what starts it"),
    ).toBeTruthy()
  })

  it('shows a running job as "Transcribing..." with elapsed time and a wait-time expectation, not a bare Pending label', () => {
    const twoMinutesAgo = new Date(Date.now() - 2 * 60 * 1000).toISOString()
    const { getByText } = render(
      <OfflineCaptionJobsView
        jobs={[job({ state: 'pending', updated_at: twoMinutesAgo, last_error: '' })]}
        canRetry
        onRetry={vi.fn()}
      />,
    )
    expect(getByText('Transcribing… (2m)', { selector: 'span' })).toBeTruthy()
    expect(
      getByText(/several minutes for a full meeting recording, not seconds/),
    ).toBeTruthy()
  })

  it('explains an awaiting-review job points to the review queue, not a stall', () => {
    const { getByText } = render(
      <OfflineCaptionJobsView jobs={[job({ state: 'awaiting_review' })]} canRetry onRetry={vi.fn()} />,
    )
    expect(getByText(/waiting in the caption review queue/)).toBeTruthy()
  })
})

describe('OfflineCaptionJobsPanel (container)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listOfflineCaptionJobs).mockResolvedValue([job()])
    vi.mocked(retryOfflineCaptionJob).mockResolvedValue(job({ state: 'pending', attempts: 0 }))
  })

  it('lists jobs scoped to the asset id', async () => {
    renderScreen('asset-42')
    await waitFor(() =>
      expect(vi.mocked(listOfflineCaptionJobs)).toHaveBeenCalledWith({ assetId: 'asset-42' }),
    )
  })

  it('confirms, retries, and shows the success state', async () => {
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /Retry offline caption job job-1/i }))
    fireEvent.click(await findByRole('button', { name: /^Retry job$/i }))
    await waitFor(() => expect(vi.mocked(retryOfflineCaptionJob)).toHaveBeenCalledWith('job-1'))
    expect(await findByText(/Queued for retry\./i)).toBeTruthy()
  })

  it('does not call retry when the operator cancels the confirm dialog', async () => {
    const { findByRole, queryByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /Retry offline caption job job-1/i }))
    fireEvent.click(await findByRole('button', { name: /^Cancel$/i }))
    expect(vi.mocked(retryOfflineCaptionJob)).not.toHaveBeenCalled()
    expect(queryByRole('alertdialog')).toBeNull()
  })

  it('shows the retry error inline on 409', async () => {
    vi.mocked(retryOfflineCaptionJob).mockRejectedValue(
      new ApiError('Request failed: 409', 409, 'Another job is already active for this asset.'),
    )
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /Retry offline caption job job-1/i }))
    fireEvent.click(await findByRole('button', { name: /^Retry job$/i }))
    expect(await findByText(/Another job is already active for this asset\./i)).toBeTruthy()
  })

  it('does not offer Retry for a records-clerk-less operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByText, queryByRole } = renderScreen()
    await findByText(/requires the records clerk role/i)
    expect((queryByRole('button', { name: /Retry offline caption job job-1/i }) as HTMLButtonElement).disabled).toBe(true)
  })
})
