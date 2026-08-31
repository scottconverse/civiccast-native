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

/**
 * Human labels for the review-queue language dimension. English is
 * transcription; Spanish is the recorded-Spanish translation pass, reviewed
 * separately (a published recording carries both tracks). A row with no
 * language predates the dimension and is English.
 */
export const CAPTION_LANGUAGE_META: Record<string, { code: string; label: string }> = {
  en: { code: 'EN', label: 'English' },
  es: { code: 'ES', label: 'Spanish' },
}

export function captionLanguageOf(item: CaptionReviewItemResponse): string {
  return item.language ?? 'en'
}

export function captionLanguageMeta(language: string): { code: string; label: string } {
  return CAPTION_LANGUAGE_META[language] ?? { code: language.toUpperCase(), label: language }
}

export const CAPTION_STATUS_META: Record<
  CaptionReviewStatus,
  { label: string; tone: 'neutral' | 'ok' | 'warn' | 'err' }
> = {
  pending: { label: 'Pending', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  edited: { label: 'Edited', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'err' },
}
