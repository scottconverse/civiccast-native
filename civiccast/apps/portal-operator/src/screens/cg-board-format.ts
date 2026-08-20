// Pure helpers for the CG bulletin-board designer screen (S6 V1, build step 7).
// Kept out of the screen module so the screen file only exports components
// (eslint react-refresh/only-export-components).
import type { CgBoardAuditEvent, CgFeedSource, CgZoneConfig } from '../types/api.generated'

// The built-in template set the GStreamer engine renders (S6 V1, no custom
// uploads). Mirrors civiccast.cg.service.build_template_library.
export const TEMPLATE_OPTIONS = [
  { id: 'standard-community-board', label: 'Standard community board' },
  { id: 'live-lower-banner', label: 'Live lower banner' },
  { id: 'schedule-forward-board', label: 'Schedule forward board' },
] as const

export const ZONE_KINDS = [
  'primary',
  'ticker',
  'schedule',
  'logo',
  'sponsor',
  'audio',
  'alert',
] as const
export const REGIONS = ['main', 'lower', 'side', 'bug', 'background'] as const
export const CONTENT_SOURCES = [
  'feed_adapter',
  'manual',
  'schedule',
  'emergency',
  'image',
  'clock',
] as const
export const FEED_KINDS = ['rss', 'ical', 'caldav', 'weather', 'social'] as const
export const TRUST_TIERS = ['operator_curated', 'partner_curated', 'public_permitted'] as const

/**
 * snake_case enum / event-kind -> readable label ("feed_adapter" -> "feed
 * adapter").
 *
 * Deliberately lowercase and NOT routed through `stateLabel` (F1): the output
 * is composed into sentences ("Ticker via feed adapter"), where sentence-case
 * reads as a typo.
 */
export function humanize(value: string): string {
  return value.replaceAll('_', ' ')
}

/** Parse a comma-separated tag input into a de-duplicated, trimmed list. */
export function parseTags(value: string): string[] {
  const seen = new Set<string>()
  for (const raw of value.split(',')) {
    const tag = raw.trim()
    if (tag) seen.add(tag)
  }
  return [...seen]
}

/** Render a tag list back into a comma-separated input value. */
export function formatTags(tags: string[] | null | undefined): string {
  return (tags ?? []).join(', ')
}

/** A zone whose content comes from a registered feed must name one. */
export function zoneNeedsFeed(contentSource: string): boolean {
  return contentSource === 'feed_adapter'
}

export function zoneSummary(zone: CgZoneConfig): string {
  const parts = [humanize(zone.zone_kind), `via ${humanize(zone.content_source)}`]
  if (zone.content_source === 'feed_adapter' && zone.feed_source_id) {
    parts.push(`(${zone.feed_source_id})`)
  }
  if (zone.approval_required) parts.push('· approval required')
  return parts.join(' ')
}

export function feedFetchStatus(feed: CgFeedSource): string {
  if (feed.last_fetch_error) return `Last fetch failed: ${feed.last_fetch_error}`
  if (feed.last_fetched_at) return `Last fetched ${formatTimestamp(feed.last_fetched_at)}`
  return 'Not fetched yet'
}

export function auditSummary(event: CgBoardAuditEvent): string {
  const who = event.operator_id ? ` by ${event.operator_id}` : ''
  return `${humanize(event.event_kind)}${who} · ${formatTimestamp(event.occurred_at)}`
}

/** Format an ISO timestamp for display; never throws on a bad value. */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : parsed.toLocaleString()
}
