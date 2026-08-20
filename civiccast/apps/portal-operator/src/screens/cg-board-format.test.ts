import { describe, expect, it } from 'vitest'

import type { CgBoardAuditEvent, CgFeedSource, CgZoneConfig } from '../types/api.generated'
import {
  auditSummary,
  feedFetchStatus,
  formatTags,
  humanize,
  parseTags,
  zoneNeedsFeed,
  zoneSummary,
} from './cg-board-format'

const ZONE: CgZoneConfig = {
  zone_id: 'z1',
  board_id: 'b1',
  region: 'lower',
  zone_kind: 'ticker',
  content_source: 'feed_adapter',
  feed_source_id: 'feed_rss',
  approval_required: true,
  created_at: '2026-01-01T00:00:00Z',
}

const FEED: CgFeedSource = {
  feed_source_id: 'feed_rss',
  channel_id: 'public',
  kind: 'rss',
  label: 'City news',
  source_url: 'https://x.gov/news.rss',
  trust_tier: 'operator_curated',
  refresh_seconds: 900,
  enabled: true,
  created_by: 'op',
  created_at: '2026-01-01T00:00:00Z',
}

describe('cg-board-format', () => {
  it('humanize replaces underscores', () => {
    expect(humanize('feed_adapter')).toBe('feed adapter')
    expect(humanize('board_created')).toBe('board created')
  })

  it('zoneNeedsFeed only for feed_adapter', () => {
    expect(zoneNeedsFeed('feed_adapter')).toBe(true)
    expect(zoneNeedsFeed('manual')).toBe(false)
  })

  it('zoneSummary names the feed and approval requirement', () => {
    const summary = zoneSummary(ZONE)
    expect(summary).toContain('ticker')
    expect(summary).toContain('via feed adapter')
    expect(summary).toContain('feed_rss')
    expect(summary).toContain('approval required')
  })

  it('feedFetchStatus reflects error / fetched / never', () => {
    expect(feedFetchStatus({ ...FEED, last_fetch_error: 'timeout' })).toContain('Last fetch failed: timeout')
    expect(feedFetchStatus({ ...FEED, last_fetched_at: '2026-06-01T18:00:00Z' })).toContain('Last fetched')
    expect(feedFetchStatus(FEED)).toBe('Not fetched yet')
  })

  it('parseTags trims, drops blanks, and de-duplicates', () => {
    expect(parseTags(' events , , alerts, events ')).toEqual(['events', 'alerts'])
    expect(parseTags('')).toEqual([])
  })

  it('formatTags round-trips a list back to a comma-separated value', () => {
    expect(formatTags(['events', 'alerts'])).toBe('events, alerts')
    expect(formatTags(null)).toBe('')
    expect(parseTags(formatTags(['a', 'b']))).toEqual(['a', 'b'])
  })

  it('auditSummary humanizes the event and names the operator', () => {
    const event: CgBoardAuditEvent = {
      audit_id: 'a1',
      board_id: 'b1',
      channel_id: 'public',
      event_kind: 'zone_added',
      operator_id: 'dana',
      occurred_at: '2026-06-01T18:00:00Z',
      details: {},
    }
    const summary = auditSummary(event)
    expect(summary).toContain('zone added')
    expect(summary).toContain('by dana')
  })
})
