import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import * as api from '../api/client'
import type { CaptionReviewItemResponse } from '../types/captions'
import { ReviewCard } from './ReviewQueueScreen'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function item(
  overrides: Partial<CaptionReviewItemResponse> = {},
): CaptionReviewItemResponse {
  return {
    review_item_id: 'review-1',
    asset_id: 'gov-ch12',
    cue: {
      cue_id: 'cue-1',
      start_seconds: 12,
      end_seconds: 14,
      text: 'motion carries',
      confidence: 0.42,
      low_confidence: true,
    },
    status: 'pending',
    original_text: 'motion carries',
    reviewed_text: null,
    low_confidence: true,
    audio_evidence_available: true,
    reviewer_note: null,
    created_at: '2026-07-25T18:00:00Z',
    updated_at: '2026-07-25T18:00:00Z',
    ...overrides,
  }
}

describe('ReviewCard low-confidence policy', () => {
  it('requires successfully playable audio before acknowledgement and approve', async () => {
    const onApprove = vi.fn()
    const { getByRole, getByLabelText } = render(
      <ReviewCard
        item={item()}
        busy={false}
        onApprove={onApprove}
        onEdit={vi.fn()}
        onReject={vi.fn()}
        canReview
      />,
    )

    const approve = getByRole('button', { name: 'Approve' }) as HTMLButtonElement
    const acknowledgement = getByLabelText(
      'I compared review-1 with its audio evidence',
    ) as HTMLInputElement
    expect(approve.disabled).toBe(true)
    expect(acknowledgement.disabled).toBe(true)

    vi.spyOn(api, 'getCaptionReviewAudioClip').mockResolvedValue(
      new Blob(['review audio'], { type: 'audio/wav' }),
    )
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:caption-review'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    fireEvent.click(getByRole('button', { name: 'Load review audio' }))
    const audio = await waitFor(() =>
      getByLabelText('Review audio for review-1'),
    )
    expect(acknowledgement.disabled).toBe(true)
    fireEvent.canPlay(audio)
    expect(acknowledgement.disabled).toBe(false)

    fireEvent.click(acknowledgement)
    expect(approve.disabled).toBe(false)
    fireEvent.click(approve)

    expect(onApprove).toHaveBeenCalledWith(item(), true)
  })

  it('keeps low-confidence approval blocked when evidence is unavailable', () => {
    const { getByRole, getByLabelText } = render(
      <ReviewCard
        item={item({ audio_evidence_available: false })}
        busy={false}
        onApprove={vi.fn()}
        onEdit={vi.fn()}
        onReject={vi.fn()}
        canReview
      />,
    )

    expect(
      (
        getByLabelText(
          'I compared review-1 with its audio evidence',
        ) as HTMLInputElement
      ).disabled,
    ).toBe(true)
    expect(
      (getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(getByRole('alert').textContent).toContain(
      'Audio evidence is unavailable',
    )
  })

  it('does not require the acknowledgement for a high-confidence cue', () => {
    const onApprove = vi.fn()
    const highConfidence = item({
      low_confidence: false,
      audio_evidence_available: false,
      cue: {
        cue_id: 'cue-1',
        start_seconds: 12,
        end_seconds: 14,
        text: 'motion carries',
        confidence: 0.95,
        low_confidence: false,
      },
    })
    const { getByRole, queryByLabelText } = render(
      <ReviewCard
        item={highConfidence}
        busy={false}
        onApprove={onApprove}
        onEdit={vi.fn()}
        onReject={vi.fn()}
        canReview
      />,
    )

    expect(
      queryByLabelText('I compared review-1 with its audio evidence'),
    ).toBeNull()
    fireEvent.click(getByRole('button', { name: 'Approve' }))
    expect(onApprove).toHaveBeenCalledWith(highConfidence, false)
  })
})
