// Pure helpers for the OTT App Admin screen (S12 / build step 8).
// Kept out of the screen module (eslint react-refresh/only-export-components).
import type { StoreSubmissionMetadata } from '../types/api.generated'

// The buildable app-shell targets (cg/epg are config feeds, not app shells).
export const APP_TARGETS = [
  'web_pwa',
  'roku',
  'tvos',
  'fire_tv',
  'android_tv',
  'android_mobile',
  'ios_ipados',
] as const

export const BUILD_TIERS = ['unbranded', 'branded'] as const

export const SUBMISSION_STATUSES = [
  'draft',
  'pending_review',
  'approved',
  'rejected',
  'published',
  'withdrawn',
] as const

/**
 * snake_case -> readable label ("android_tv" -> "android tv").
 *
 * Deliberately lowercase and NOT routed through `stateLabel` (F1): this value
 * is composed into mid-sentence prose ("via feed adapter", "Tier: standard"),
 * where sentence-casing reads as a typo. It is already free of raw enums,
 * which is what F1 was about.
 */
export function humanize(value: string): string {
  return value.replaceAll('_', ' ')
}

/** First 12 chars of a SHA-256 for compact display. */
export function shortSha(sha: string): string {
  return sha.slice(0, 12)
}

/** Format an ISO timestamp for display; never throws on a bad value. */
export function formatBuiltAt(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString()
}

/** A short status line for a store submission row. */
export function submissionSummary(submission: StoreSubmissionMetadata): string {
  const parts: string[] = [humanize(submission.submission_status ?? 'draft')]
  const version = submission.version_name
  if (version) parts.push(`v${version}`)
  const packageId = submission.package_id
  if (packageId) parts.push(packageId)
  return parts.join(' · ')
}
