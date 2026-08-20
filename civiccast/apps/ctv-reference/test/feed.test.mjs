import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'

import { groupFeedItems, normalizeFeed, selectInitialItem } from '../src/feed.js'

const here = dirname(fileURLToPath(import.meta.url))

const rawFeed = {
  generated_at: '2026-05-31T18:00:00Z',
  station_name: 'CivicCast Lab',
  proof_boundary: 'reference-feed-api-not-channel-store-publication',
  browse_facets: ['channel', 'meeting-body', 'series', 'date', 'topic'],
  items: [
    {
      id: 'live-government',
      type: 'live',
      title: 'Government Channel',
      channel_id: 'government',
      stream_url: '/api/public/channels/government/live.m3u8',
      captions_url: '/api/public/channels/government/captions.vtt',
      content_id: 'civiccast-live-government',
      description: 'Live and scheduled programming for Government Channel.',
    },
    {
      id: 'vod-recent-meetings',
      type: 'vod',
      title: 'Recent meetings',
      stream_url: '/api/public/assets',
      content_id: 'civiccast-vod-recent-meetings',
      description: 'Reference VOD collection for meetings published through CivicCast.',
    },
  ],
}

describe('reference CTV feed handling', () => {
  it('normalizes the public feed into stable CTV item fields', () => {
    const feed = normalizeFeed(rawFeed)

    assert.equal(feed.stationName, 'CivicCast Lab')
    assert.equal(feed.items[0].contentId, 'civiccast-live-government')
    assert.equal(feed.items[0].captionsUrl, '/api/public/channels/government/captions.vtt')
    assert.deepEqual(feed.browseFacets, ['channel', 'meeting-body', 'series', 'date', 'topic'])
  })

  it('groups live and VOD rails separately', () => {
    const grouped = groupFeedItems(normalizeFeed(rawFeed))

    assert.equal(grouped.live.length, 1)
    assert.equal(grouped.vod.length, 1)
    assert.equal(grouped.live[0].id, 'live-government')
    assert.equal(grouped.vod[0].id, 'vod-recent-meetings')
  })

  it('selects a live item before VOD for first focus', () => {
    const selected = selectInitialItem(normalizeFeed(rawFeed))

    assert.equal(selected?.id, 'live-government')
  })

  it('rejects feed items without stable playback identifiers', () => {
    assert.throws(
      () => normalizeFeed({ items: [{ id: 'broken', title: 'Broken' }] }),
      /missing an id, type, title, stream_url, or content_id/,
    )
  })

  it('keeps a visible focus state and initial program-card focus path', async () => {
    const styles = await readFile(join(here, '..', 'src', 'styles.css'), 'utf8')
    const app = await readFile(join(here, '..', 'src', 'app.js'), 'utf8')

    assert.match(styles, /\.program-card:focus-visible/)
    assert.match(styles, /outline: 4px solid/)
    assert.match(app, /selectedButton\.focus\(\)/)
  })
})
