// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// civiccast-player.js — the SINGLE canonical playback client shared by the
// Tizen and webOS OTT apps (Codebase 4 in the S12 platform build matrix:
// "Web/HTML — Samsung Tizen + LG webOS", see ../README.md §Platform build
// matrix). Both ../tizen/ and ../webos/ reference this exact file rather
// than each keeping their own copy — the CI build step
// (.github/workflows/ci-ott-apps.yml) copies it into each platform's
// packaging directory before running `tizen package` / `ares-package`.
//
// This talks to the REAL CivicCast app-platform contract
// (civiccast/app_platform/models.py / router.py), the same one consumed by
// civiccast/apps/app-platform-shells/src/shell.mjs:
//
//   1. GET <configUrl> -> StationAppConfig
//      { station_name, default_channel_id, channels: [ { channel_id,
//        branding: { display_name, color }, live_state_url } ] }
//   2. GET <channel.live_state_url> -> LiveState
//      { state, playback_url, title, fallback_reason }
//
// `live_state_url` is a path relative to the API host — resolve it against
// the config URL's origin before fetching. `playback_url` is the HLS
// manifest handed directly to the platform's <video> element. Both Tizen
// and LG webOS TV browsers (Chromium-based, recent versions) play HLS
// natively via Media Source Extensions; no third-party HLS.js dependency
// is required for this starter.

const DEFAULT_CONFIG_URL = '/api/public/app/config'

export async function loadStationConfig(configUrl = DEFAULT_CONFIG_URL) {
  return getJson(configUrl)
}

export function selectDefaultChannel(config) {
  return (
    config.channels.find((channel) => channel.channel_id === config.default_channel_id) ??
    config.channels[0] ??
    null
  )
}

export async function fetchLiveState(configUrl, channel) {
  const url = resolveUrl(configUrl, channel.live_state_url)
  return getJson(url)
}

export async function fetchCatalog(configUrl) {
  // The app-platform catalog currently contains demonstration entries. The
  // public asset library contains the station's actual published HLS assets.
  const assets = await getJson(resolveUrl(configUrl, '/api/public/assets'))
  return assets.map((asset) => ({
    item_id: asset.asset_id,
    title: asset.title,
    description: asset.description,
    playback_url: asset.manifest_url,
    poster_url: asset.poster_url,
    publish_state: 'published',
  }))
}

/**
 * Boots the player against `document.querySelector('[data-civiccast-app]')`.
 * Renders a channel list; selecting a channel fetches its LiveState and
 * plays `playback_url` in the `<video>` element.
 */
export async function bootPlayer({ platformLabel, configUrl = DEFAULT_CONFIG_URL } = {}) {
  const root = document.querySelector('[data-civiccast-app]')
  if (!root) return

  const elements = renderShell(root, platformLabel)
  const params = new URLSearchParams(window.location.search)
  let savedConfig = null
  try { savedConfig = window.localStorage.getItem('civiccast-config-url') } catch { /* storage disabled */ }
  const resolvedConfigUrl = params.get('config') ?? savedConfig
    ?? (window.location.protocol === 'http:' || window.location.protocol === 'https:' ? configUrl : null)
  elements.settings.addEventListener('click', () => {
    elements.setup.hidden = false
    elements.setupInput.focus()
  })
  elements.setup.addEventListener('submit', (event) => {
    event.preventDefault()
    try {
      const entered = new URL(elements.setupInput.value.trim())
      if (entered.protocol !== 'https:' && entered.protocol !== 'http:') {
        throw new Error('Use an HTTP or HTTPS station address.')
      }
      const endpoint = entered.pathname.endsWith('/api/public/app/config')
        ? entered.toString() : new URL('/api/public/app/config', entered).toString()
      window.localStorage.setItem('civiccast-config-url', endpoint)
      window.location.reload()
    } catch (error) {
      elements.status.textContent = `Station address: ${error.message}`
    }
  })
  if (!resolvedConfigUrl) {
    elements.status.textContent = 'Enter your station address to connect this TV.'
    elements.setup.hidden = false
    return
  }
  elements.setupInput.value = resolvedConfigUrl

  let config
  try {
    config = await loadStationConfig(resolvedConfigUrl)
  } catch (error) {
    elements.status.textContent = `Could not load station config: ${error.message}`
    return
  }

  elements.stationName.textContent = config.station_name
  if (config.build_profile?.icon_url) {
    elements.stationLogo.src = resolveUrl(resolvedConfigUrl, config.build_profile.icon_url)
    elements.stationLogo.alt = `${config.station_name} logo`
    elements.stationLogo.hidden = false
  }
  let selectedChannel = null
  let catalogItems = []

  async function selectChannel(channel, { updateUrl = true } = {}) {
    selectedChannel = channel
    renderChannelList(elements.channelList, config.channels, channel.channel_id, (choice) => {
      void selectChannel(choice)
    }, resolvedConfigUrl)
    elements.search.value = ''
    catalogItems = []
    elements.catalogList.replaceChildren()
    if (updateUrl) setLocation({ channel: channel.channel_id })
    await playChannel(resolvedConfigUrl, channel, elements)
    try {
      const catalog = await fetchCatalog(resolvedConfigUrl)
      if (selectedChannel !== channel) return
      catalogItems = catalog.filter((item) => item.playback_url)
      renderCatalog(elements.catalogList, catalogItems, resolvedConfigUrl, (item) => {
        playVod(resolvedConfigUrl, channel, item, elements)
      })
      elements.catalogStatus.textContent = catalogItems.length
        ? 'Published station replays' : 'No replay programmes are available.'
    } catch (error) {
      elements.catalogStatus.textContent = `Could not load replays: ${error.message}`
    }
  }

  elements.search.addEventListener('input', () => {
    const query = elements.search.value.trim().toLocaleLowerCase()
    renderCatalog(
      elements.catalogList,
      catalogItems.filter((item) => [item.title, item.description, item.series]
        .some((value) => value?.toLocaleLowerCase().includes(query))),
      resolvedConfigUrl,
      (item) => playVod(resolvedConfigUrl, selectedChannel, item, elements),
    )
  })
  elements.captions.addEventListener('change', () => {
    Array.from(elements.video.textTracks).forEach((track, index) => {
      track.mode = String(index) === elements.captions.value ? 'showing' : 'disabled'
    })
  })
  elements.audio.addEventListener('change', () => {
    Array.from(elements.video.audioTracks ?? []).forEach((track, index) => {
      track.enabled = String(index) === elements.audio.value
    })
  })
  elements.video.addEventListener('loadedmetadata', () => updateTrackControls(elements))
  elements.video.textTracks?.addEventListener?.('addtrack', () => updateTrackControls(elements))
  elements.video.audioTracks?.addEventListener?.('addtrack', () => updateTrackControls(elements))

  const deepLink = new URLSearchParams(window.location.search)
  const defaultChannel = config.channels.find((channel) => channel.channel_id === deepLink.get('channel'))
    ?? selectDefaultChannel(config)
  if (defaultChannel) {
    await selectChannel(defaultChannel, { updateUrl: false })
    const itemId = deepLink.get('item')
    if (itemId) {
      const item = catalogItems.find((entry) => entry.item_id === itemId)
      if (item) playVod(resolvedConfigUrl, defaultChannel, item, elements, { updateUrl: false })
    }
  } else {
    elements.status.textContent = 'No channels are configured yet.'
  }
}

async function playChannel(configUrl, channel, elements) {
  elements.status.textContent = `${channel.branding.display_name}: loading stream…`
  elements.video.pause()
  elements.video.removeAttribute('src')

  let live
  try {
    live = await fetchLiveState(configUrl, channel)
  } catch (error) {
    elements.status.textContent = `${channel.branding.display_name}: ${error.message}`
    return
  }

  if (!live.playback_url) {
    const label = live.state === 'fallback' ? live.fallback_reason : live.title
    elements.status.textContent = `${channel.branding.display_name}: ${live.state}${label ? ` (${label})` : ''}`
    return
  }

  elements.status.textContent = ''
  elements.video.replaceChildren()
  elements.video.poster = ''
  elements.video.src = resolveUrl(configUrl, live.playback_url)
  updateTrackControls(elements)
  const playResult = elements.video.play()
  if (playResult?.catch) playResult.catch(() => {})
}

function playVod(configUrl, channel, item, elements, { updateUrl = true } = {}) {
  if (!channel || !item.playback_url) return
  elements.status.textContent = `Replay: ${item.title}`
  elements.video.pause()
  elements.video.removeAttribute('src')
  elements.video.replaceChildren()
  elements.video.poster = item.poster_url ? resolveUrl(configUrl, item.poster_url) : ''
  for (const caption of item.captions ?? []) {
    if (!caption.url) continue
    const track = document.createElement('track')
    track.kind = 'captions'
    track.label = caption.label
    track.srclang = caption.language
    track.src = resolveUrl(configUrl, caption.url)
    track.default = Boolean(caption.default)
    elements.video.append(track)
  }
  elements.video.src = resolveUrl(configUrl, item.playback_url)
  if (updateUrl) setLocation({ channel: channel.channel_id, item: item.item_id })
  updateTrackControls(elements)
  const playResult = elements.video.play()
  if (playResult?.catch) playResult.catch(() => {})
}

function renderShell(root, platformLabel) {
  root.innerHTML = ''

  const header = document.createElement('h1')
  header.dataset.role = 'station-name'
  header.textContent = 'CivicCast'

  const platform = document.createElement('p')
  platform.dataset.role = 'platform-label'
  platform.textContent = platformLabel ?? root.dataset.platformLabel ?? 'CivicCast app'

  const status = document.createElement('p')
  status.dataset.role = 'status'
  status.setAttribute('role', 'status')
  status.setAttribute('aria-live', 'polite')

  const stationLogo = document.createElement('img')
  stationLogo.dataset.role = 'station-logo'
  stationLogo.hidden = true
  const settings = document.createElement('button')
  settings.type = 'button'
  settings.textContent = 'Station settings'
  const setup = document.createElement('form')
  setup.hidden = true
  const setupInput = document.createElement('input')
  setupInput.type = 'url'
  setupInput.placeholder = 'https://station.example.org'
  setupInput.setAttribute('aria-label', 'Station API address')
  setupInput.required = true
  const setupSave = document.createElement('button')
  setupSave.type = 'submit'
  setupSave.textContent = 'Connect station'
  setup.append(setupInput, setupSave)

  const video = document.createElement('video')
  video.setAttribute('controls', '')
  video.dataset.role = 'video'
  video.setAttribute('aria-label', 'CivicCast programme video')

  const channelList = document.createElement('ul')
  channelList.dataset.role = 'channel-list'

  const search = document.createElement('input')
  search.type = 'search'
  search.placeholder = 'Search replay programmes'
  search.setAttribute('aria-label', 'Search replay programmes')
  search.dataset.role = 'catalog-search'
  const catalogStatus = document.createElement('p')
  catalogStatus.setAttribute('role', 'status')
  const catalogList = document.createElement('ul')
  catalogList.dataset.role = 'catalog-list'
  const captions = document.createElement('select')
  captions.setAttribute('aria-label', 'Captions')
  captions.dataset.role = 'caption-tracks'
  const audio = document.createElement('select')
  audio.setAttribute('aria-label', 'Audio track')
  audio.dataset.role = 'audio-tracks'

  root.append(stationLogo, header, platform, settings, setup, status, video, captions, audio, channelList,
    search, catalogStatus, catalogList)
  root.dataset.ready = 'true'

  return { stationName: header, stationLogo, settings, setup, setupInput, status, video,
    channelList, search, catalogStatus, catalogList, captions, audio }
}

function renderChannelList(listElement, channels, selectedId, onSelect, configUrl) {
  listElement.innerHTML = ''
  channels.forEach((channel) => {
    const item = document.createElement('li')
    const button = document.createElement('button')
    button.type = 'button'
    button.setAttribute('aria-pressed', String(channel.channel_id === selectedId))
    if (channel.branding.logo_url) {
      const logo = document.createElement('img')
      logo.src = resolveUrl(configUrl, channel.branding.logo_url)
      logo.alt = ''
      button.append(logo)
    }
    button.append(document.createTextNode(channel.branding.display_name))
    button.style.setProperty('--civiccast-brand', channel.branding.color ?? '#2458A6')
    button.addEventListener('click', () => onSelect(channel))
    item.append(button)
    listElement.append(item)
  })
}

function renderCatalog(listElement, items, configUrl, onSelect) {
  listElement.replaceChildren()
  for (const item of items) {
    const row = document.createElement('li')
    const button = document.createElement('button')
    button.type = 'button'
    if (item.thumbnail_url || item.poster_url) {
      const image = document.createElement('img')
      image.src = resolveUrl(configUrl, item.thumbnail_url ?? item.poster_url)
      image.alt = ''
      button.append(image)
    }
    button.append(document.createTextNode(item.title))
    button.addEventListener('click', () => onSelect(item))
    row.append(button)
    listElement.append(row)
  }
}

function updateTrackControls(elements) {
  const textTracks = Array.from(elements.video.textTracks ?? [])
  elements.captions.replaceChildren(new Option('Captions off', '-1'), ...textTracks.map(
    (track, index) => new Option(track.label || track.language || `Captions ${index + 1}`, String(index)),
  ))
  elements.captions.value = String(textTracks.findIndex((track) => track.mode === 'showing'))
  elements.captions.hidden = textTracks.length === 0
  const audioTracks = Array.from(elements.video.audioTracks ?? [])
  elements.audio.replaceChildren(...audioTracks.map(
    (track, index) => new Option(track.label || track.language || `Audio ${index + 1}`, String(index)),
  ))
  elements.audio.hidden = audioTracks.length < 2
  elements.audio.value = String(audioTracks.findIndex((track) => track.enabled))
}

function setLocation(params) {
  const next = new URL(window.location.href)
  next.searchParams.delete('channel')
  next.searchParams.delete('item')
  for (const [key, value] of Object.entries(params)) next.searchParams.set(key, value)
  window.history.replaceState(null, '', next)
}

function resolveUrl(configUrl, path) {
  return new URL(path, new URL(configUrl, window.location.href)).toString()
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`.trim())
  }
  return response.json()
}
