import { groupFeedItems, normalizeFeed, selectInitialItem } from './feed.js'

const DEFAULT_FEED_URL = '/api/public/channels/ctv/feed'

const statusEl = document.querySelector('#feed-status')
const titleEl = document.querySelector('#selected-title')
const typeEl = document.querySelector('#selected-type')
const descriptionEl = document.querySelector('#selected-description')
const contentIdEl = document.querySelector('#selected-content-id')
const streamEl = document.querySelector('#selected-stream')
const captionsEl = document.querySelector('#selected-captions')
const liveRailEl = document.querySelector('#live-rail')
const vodRailEl = document.querySelector('#vod-rail')

function feedUrl() {
  const params = new URLSearchParams(window.location.search)
  return params.get('feed') || DEFAULT_FEED_URL
}

function setStatus(message, tone = 'neutral') {
  statusEl.textContent = message
  statusEl.dataset.tone = tone
}

function selectItem(item) {
  if (!item) return
  typeEl.textContent = item.type === 'live' ? 'Live channel' : 'Video on demand'
  titleEl.textContent = item.title
  descriptionEl.textContent = item.description
  contentIdEl.textContent = item.contentId
  streamEl.textContent = item.streamUrl
  captionsEl.textContent = item.captionsUrl ?? 'Not attached'
  let selectedButton = null
  for (const button of document.querySelectorAll('.program-card')) {
    const selected = button.dataset.itemId === item.id
    button.setAttribute('aria-pressed', String(selected))
    if (selected) selectedButton = button
  }
  if (
    selectedButton &&
    (document.activeElement === null || document.activeElement === document.body)
  ) {
    selectedButton.focus()
  }
}

function renderRail(container, items) {
  container.replaceChildren()
  if (items.length === 0) {
    const empty = document.createElement('p')
    empty.className = 'empty'
    empty.textContent = 'No items in this rail.'
    container.append(empty)
    return
  }
  for (const item of items) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'program-card'
    button.dataset.itemId = item.id
    button.innerHTML = `
      <span class="program-kind">${item.type}</span>
      <strong></strong>
      <span class="program-id"></span>
      <span class="program-description"></span>
    `
    button.querySelector('strong').textContent = item.title
    button.querySelector('.program-id').textContent = item.contentId
    button.querySelector('.program-description').textContent = item.description
    button.addEventListener('click', () => selectItem(item))
    container.append(button)
  }
}

async function loadFeed() {
  try {
    setStatus('Loading feed')
    const response = await fetch(feedUrl(), { headers: { Accept: 'application/json' } })
    if (!response.ok) throw new Error(`Feed request failed: ${response.status}`)
    const feed = normalizeFeed(await response.json())
    document.title = `${feed.stationName} - CivicCast CTV`
    const grouped = groupFeedItems(feed)
    renderRail(liveRailEl, grouped.live)
    renderRail(vodRailEl, grouped.vod)
    selectItem(selectInitialItem(feed))
    setStatus(`${feed.items.length} items / ${feed.proofBoundary}`, 'ok')
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Feed failed to load', 'error')
  }
}

void loadFeed()
