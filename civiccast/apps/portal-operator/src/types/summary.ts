import type { SummaryDraft } from './api.generated'

export const SUMMARY_STATUS_META: Record<
  SummaryDraft['status'],
  { label: string; tone: 'neutral' | 'ok' | 'warn' | 'err' }
> = {
  pending_review: { label: 'Pending review', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'err' },
  refused: { label: 'Needs evidence', tone: 'err' },
}

export type SummaryReviewItem = SummaryDraft
