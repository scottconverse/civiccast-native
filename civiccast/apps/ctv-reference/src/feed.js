export function normalizeFeed(rawFeed) {
  if (!rawFeed || !Array.isArray(rawFeed.items)) {
    throw new Error('CTV feed must include an items array.')
  }
  const items = rawFeed.items.map((item) => {
    if (!item.id || !item.type || !item.title || !item.stream_url || !item.content_id) {
      throw new Error('CTV feed item is missing an id, type, title, stream_url, or content_id.')
    }
    return {
      id: String(item.id),
      type: item.type === 'vod' ? 'vod' : 'live',
      title: String(item.title),
      channelId: item.channel_id ?? null,
      streamUrl: String(item.stream_url),
      captionsUrl: item.captions_url ?? null,
      contentId: String(item.content_id),
      description: item.description ? String(item.description) : 'CivicCast programming.',
    }
  })
  return {
    generatedAt: rawFeed.generated_at ?? null,
    stationName: rawFeed.station_name ? String(rawFeed.station_name) : 'CivicCast station',
    proofBoundary: rawFeed.proof_boundary ?? 'reference-feed-api-not-channel-store-publication',
    browseFacets: Array.isArray(rawFeed.browse_facets) ? rawFeed.browse_facets.map(String) : [],
    items,
  }
}

export function groupFeedItems(feed) {
  return {
    live: feed.items.filter((item) => item.type === 'live'),
    vod: feed.items.filter((item) => item.type === 'vod'),
  }
}

export function selectInitialItem(feed) {
  return feed.items.find((item) => item.type === 'live') ?? feed.items[0] ?? null
}
