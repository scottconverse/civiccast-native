import type {
  CaptionCue,
  CaptionReviewDecision,
  CaptionReviewEdit,
  CaptionReviewItemRequest,
  CaptionReviewItemResponse,
} from './api.generated'

export type {
  CaptionCue,
  CaptionReviewDecision,
  CaptionReviewEdit,
  CaptionReviewItemRequest,
  CaptionReviewItemResponse,
}

export type CaptionReviewStatus = CaptionReviewItemResponse['status']

export const CAPTION_STATUS_META: Record<
  CaptionReviewStatus,
  { label: string; tone: 'neutral' | 'ok' | 'warn' | 'err' }
> = {
  pending: { label: 'Pending', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  edited: { label: 'Edited', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'err' },
}
