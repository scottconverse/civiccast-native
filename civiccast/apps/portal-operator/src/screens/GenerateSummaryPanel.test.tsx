// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

import type {
  CaptionReviewItemResponse,
  StaffIdentityResponse,
  SummaryGenerationJobRecord,
} from '../types/api.generated'

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
  listCaptionReviewItems: vi.fn(),
  listSummaryJobs: vi.fn(),
  createSummaryJob: vi.fn(),
  retrySummaryJob: vi.fn(),
}))

import {
  createSummaryJob,
  getStaffIdentity,
  listCaptionReviewItems,
  listSummaryJobs,
  retrySummaryJob,
} from '../api/client'
import { GenerateSummaryPanel, GenerateSummaryView } from './GenerateSummaryPanel'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function reviewItem(
  overrides: Partial<CaptionReviewItemResponse> = {},
): CaptionReviewItemResponse {
  return {
    review_item_id: 'ri-1',
    asset_id: 'asset-1',
    cue: {
      cue_id: 'cue-1',
      start_seconds: 0,
      end_seconds: 6,
      text: 'Motion passes 2-1.',
      confidence: 0.95,
      low_confidence: false,
    },
    status: 'approved',
    original_text: 'Motion passes 2-1.',
    low_confidence: false,
    audio_evidence_available: false,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  } as CaptionReviewItemResponse
}

function job(overrides: Partial<SummaryGenerationJobRecord> = {}): SummaryGenerationJobRecord {
  return {
    job_id: 'sgj-1',
    meeting_id: 'asset-1',
    cues: [],
    state: 'pending',
    attempts: 0,
    last_error: '',
    created_at: '2026-08-29T00:00:00Z',
    updated_at: '2026-08-29T00:00:00Z',
    ...overrides,
  }
}

function renderPanel(assetId = 'asset-1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <GenerateSummaryPanel assetId={assetId} />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('GenerateSummaryView (presentational)', () => {
  it('shows a no-cues message when nothing has been committed yet', () => {
    const { getByText } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={0}
          latestJob={undefined}
          canGenerate
          canRetry
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(getByText(/No committed transcript cues yet/i)).toBeTruthy()
  })

  it('offers a Generate summary button when cues exist and the role allows it', () => {
    const onGenerate = vi.fn()
    const { getByRole } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={undefined}
          canGenerate
          canRetry
          generating={false}
          retrying={false}
          onGenerate={onGenerate}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    const button = getByRole('button', { name: /generate summary/i })
    fireEvent.click(button)
    expect(onGenerate).toHaveBeenCalledOnce()
  })

  it('disables the Generate button and explains why without the role', () => {
    const { getByRole, getByText } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={undefined}
          canGenerate={false}
          canRetry={false}
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect((getByRole('button', { name: /generate summary/i }) as HTMLButtonElement).disabled).toBe(true)
    expect(getByText(/records clerk or support admin role/i)).toBeTruthy()
  })

  it('shows honest progress copy while a job is running', () => {
    const { getByText } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={job({ state: 'running' })}
          canGenerate
          canRetry
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(getByText(/generating…/i)).toBeTruthy()
    expect(getByText(/local model is generating this summary now/i)).toBeTruthy()
    expect(getByText(/1-6 minutes/i)).toBeTruthy()
  })

  it('links to Summary review once a job completes', () => {
    const { getByRole } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={job({ state: 'complete', summary_id: 'summary-9' })}
          canGenerate
          canRetry
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    const link = getByRole('link', { name: /review it in summary review/i })
    expect(link.getAttribute('href')).toBe('/summary')
  })

  it('shows a readable failure message with the real last_error and a Retry action', () => {
    const onRetry = vi.fn()
    const { getByRole, getByText } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={job({
            state: 'failed',
            attempts: 3,
            last_error: 'llama-server process has terminated: exit status 1',
          })}
          canGenerate
          canRetry
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={onRetry}
        />
      </MemoryRouter>,
    )
    expect(getByText(/llama-server process has terminated/i)).toBeTruthy()
    expect(getByText(/failed after 3 attempts/i)).toBeTruthy()
    fireEvent.click(getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledWith('sgj-1')
  })

  it('disables Retry and explains why without the records_clerk role', () => {
    const { getByRole, getByText } = render(
      <MemoryRouter>
        <GenerateSummaryView
          committedCueCount={12}
          latestJob={job({ state: 'failed', attempts: 1, last_error: 'boom' })}
          canGenerate
          canRetry={false}
          generating={false}
          retrying={false}
          onGenerate={vi.fn()}
          onRetry={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect((getByRole('button', { name: /retry/i }) as HTMLButtonElement).disabled).toBe(true)
    expect(getByText(/records clerk role/i)).toBeTruthy()
  })
})

describe('GenerateSummaryPanel (data-fetching)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('queues a job using the committed, operator-edited cue text', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listCaptionReviewItems).mockResolvedValue([
      reviewItem({ reviewed_text: 'Motion passes unanimously.' }),
    ])
    vi.mocked(listSummaryJobs).mockResolvedValue([])
    vi.mocked(createSummaryJob).mockResolvedValue(job())

    const { getByRole } = renderPanel()

    await waitFor(() => expect((getByRole('button', { name: /generate summary/i }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByRole('button', { name: /generate summary/i }))

    await waitFor(() => expect(createSummaryJob).toHaveBeenCalledOnce())
    const payload = vi.mocked(createSummaryJob).mock.calls[0][0]
    expect(payload.meeting_id).toBe('asset-1')
    // The reviewed (operator-corrected) text wins over the raw model hypothesis.
    expect(payload.cues?.[0].text).toBe('Motion passes unanimously.')
    expect(payload.cues?.[0].cue_id).toBe('cue-1')
  })

  it('falls back to the original cue text when nothing was edited', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listCaptionReviewItems).mockResolvedValue([reviewItem()])
    vi.mocked(listSummaryJobs).mockResolvedValue([])
    vi.mocked(createSummaryJob).mockResolvedValue(job())

    const { getByRole } = renderPanel()

    await waitFor(() => expect((getByRole('button', { name: /generate summary/i }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByRole('button', { name: /generate summary/i }))

    await waitFor(() => expect(createSummaryJob).toHaveBeenCalledOnce())
    expect(vi.mocked(createSummaryJob).mock.calls[0][0].cues?.[0].text).toBe(
      'Motion passes 2-1.',
    )
  })

  it('shows the failed job returned by the API with its real error', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listCaptionReviewItems).mockResolvedValue([reviewItem()])
    vi.mocked(listSummaryJobs).mockResolvedValue([
      job({ state: 'failed', attempts: 3, last_error: 'Ollama unreachable' }),
    ])

    const { getByText } = renderPanel()

    await waitFor(() => expect(getByText(/Ollama unreachable/i)).toBeTruthy())
  })

  it('retries a failed job through the API', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listCaptionReviewItems).mockResolvedValue([reviewItem()])
    vi.mocked(listSummaryJobs).mockResolvedValue([
      job({ state: 'failed', attempts: 3, last_error: 'boom' }),
    ])
    vi.mocked(retrySummaryJob).mockResolvedValue(job({ state: 'pending' }))

    const { getByRole } = renderPanel()

    await waitFor(() => expect((getByRole('button', { name: /retry/i }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(retrySummaryJob).toHaveBeenCalledWith('sgj-1'))
  })
})
