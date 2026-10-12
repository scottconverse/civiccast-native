import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const hlsHarness = vi.hoisted(() => ({
  instances: [] as Array<{ sourceUrl: string; fail: () => void }>,
}))

vi.mock('hls.js', () => ({
  default: class HlsStub {
    static Events = { ERROR: 'error', MANIFEST_PARSED: 'manifestParsed' }
    static isSupported() {
      return true
    }

    private handlers = new Map<string, (...args: unknown[]) => void>()
    private destroyed = false
    private harnessItem!: { sourceUrl: string; fail: () => void }

    constructor() {
      this.harnessItem = {
        sourceUrl: '',
        fail: () => this.handlers.get('error')?.('error', { fatal: true }),
      }
      hlsHarness.instances.push(this.harnessItem)
    }

    on(event: string, handler: (...args: unknown[]) => void) {
      this.handlers.set(event, handler)
    }

    attachMedia(video: HTMLVideoElement) {
      let currentTime = 0
      Object.defineProperties(video, {
        readyState: { configurable: true, value: 1 },
        duration: { configurable: true, value: 20 },
        currentTime: {
          configurable: true,
          get: () => currentTime,
          set: (value: number) => { currentTime = value },
        },
      })
      queueMicrotask(() => {
        if (this.destroyed) return
        video.dispatchEvent(new Event('loadedmetadata'))
        this.handlers.get('manifestParsed')?.('manifestParsed', {})
      })
    }

    loadSource(sourceUrl: string) {
      this.harnessItem.sourceUrl = sourceUrl
    }

    destroy() {
      this.destroyed = true
    }
  },
}))

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
  approveSummary: vi.fn(),
  downloadSignedRecord: vi.fn(),
  editSummary: vi.fn(),
  exportSignedRecord: vi.fn(),
  getStaffAssetPlaybackGrant: vi.fn(),
  getStaffIdentity: vi.fn(),
  listSignedRecords: vi.fn(),
  listSummaryReviewItems: vi.fn(),
  verifySignedRecord: vi.fn(),
}))

import {
  getStaffAssetPlaybackGrant,
  getStaffIdentity,
  listSummaryReviewItems,
} from '../api/client'
import type { SummaryDraft, StaffIdentityResponse } from '../types/api.generated'
import { SummaryReviewScreen } from './SummaryReviewScreen'

const summary: SummaryDraft = {
  summary_id: 'summary-17',
  meeting_id: 'asset-17',
  status: 'pending_review',
  narrative: 'The council approved the cited budget.',
  sourced_claims: [
    {
      claim_id: 'claim-17',
      text: 'The budget passed.',
      claim_type: 'narrative',
      transcript_ranges: [
        { cue_id: 'cue-17', start_seconds: 42.5, end_seconds: 52.5 },
      ],
    },
  ],
  provenance: {
    model_tag: 'test-model',
    prompt_version: 'test-prompt',
    extraction_version: 'test-extraction',
    generated_at: '2026-10-12T00:00:00Z',
  },
  audit_fingerprint: 'fingerprint-17',
}

const playbackGrant = {
  url: '/media/staff-source/asset-17/source',
  packaged_url: '/media/staff-source/asset-17/hls/playlist.m3u8',
  playback_kind: 'hls' as const,
  source_content_type: 'video/mp2t',
  source_offset_seconds: 30,
  expires_at: '2026-10-12T00:15:00Z',
}

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SummaryReviewScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  hlsHarness.instances.length = 0
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined)
  vi.mocked(getStaffIdentity).mockResolvedValue({
    operator_id: 'records-clerk',
    operator_display_name: 'Records Clerk',
    roles: ['records_clerk'],
  } as StaffIdentityResponse)
  vi.mocked(listSummaryReviewItems).mockResolvedValue({ items: [summary] })
  vi.mocked(getStaffAssetPlaybackGrant).mockResolvedValue(playbackGrant)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SummaryReviewScreen source citations', () => {
  it('loads the scoped HLS preview and seeks an absolute citation into its packaged timeline', async () => {
    renderScreen()

    fireEvent.click(await screen.findByRole('button', { name: 'cue-17 0:42-0:52' }))

    const video = await screen.findByLabelText('Summary source recording') as HTMLVideoElement
    await waitFor(() => expect(video.currentTime).toBe(12.5))
    expect(getStaffAssetPlaybackGrant).toHaveBeenCalledWith('asset-17')
    expect(hlsHarness.instances[0]?.sourceUrl).toBe(playbackGrant.packaged_url)
    expect(video.currentTime).toBe(42.5 - playbackGrant.source_offset_seconds)
    expect(screen.getByRole('button', { name: 'cue-17 0:42-0:52' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('status').textContent).toMatch(/preview ends before the citation at 0:52/i)
  })

  it('renews playback after a fatal media error when the refreshed grant keeps the same URL', async () => {
    renderScreen()

    fireEvent.click(await screen.findByRole('button', { name: 'cue-17 0:42-0:52' }))
    const video = await screen.findByLabelText('Summary source recording') as HTMLVideoElement
    await waitFor(() => expect(hlsHarness.instances).toHaveLength(1))
    await waitFor(() => expect(video.currentTime).toBe(12.5))

    hlsHarness.instances[0]?.fail()
    fireEvent.click(await screen.findByRole('button', { name: 'Renew playback' }))

    await waitFor(() => expect(getStaffAssetPlaybackGrant).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(hlsHarness.instances).toHaveLength(2))
    expect(hlsHarness.instances[1]?.sourceUrl).toBe(hlsHarness.instances[0]?.sourceUrl)
    expect(document.body.contains(video)).toBe(true)
    await waitFor(() => expect(video.currentTime).toBe(12.5))
  })
})
