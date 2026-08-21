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

/**
 * Boots the player against `document.querySelector('[data-civiccast-app]')`.
 * Renders a channel list; selecting a channel fetches its LiveState and
 * plays `playback_url` in the `<video>` element.
 */
export async function bootPlayer({ platformLabel, configUrl = DEFAULT_CONFIG_URL } = {}) {
  const root = document.querySelector('[data-civiccast-app]')
  if (!root) return

  const params = new URLSearchParams(window.location.search)
  const resolvedConfigUrl = params.get('config') ?? configUrl

  const elements = renderShell(root, platformLabel)

  let config
  try {
    config = await loadStationConfig(resolvedConfigUrl)
  } catch (error) {
    elements.status.textContent = `Could not load station config: ${error.message}`
    return
  }

  elements.stationName.textContent = config.station_name
  renderChannelList(elements.channelList, config.channels, (channel) =>
    playChannel(resolvedConfigUrl, channel, elements),
  )

  const defaultChannel = selectDefaultChannel(config)
  if (defaultChannel) {
    await playChannel(resolvedConfigUrl, defaultChannel, elements)
  } else {
    elements.status.textContent = 'No channels are configured yet.'
  }
}

async function playChannel(configUrl, channel, elements) {
  elements.status.textContent = `${channel.branding.display_name}: loading stream…`
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
  elements.video.src = live.playback_url
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

  const video = document.createElement('video')
  video.setAttribute('controls', '')
  video.dataset.role = 'video'

  const channelList = document.createElement('ul')
  channelList.dataset.role = 'channel-list'

  root.append(header, platform, status, video, channelList)
  root.dataset.ready = 'true'

  return { stationName: header, status, video, channelList }
}

function renderChannelList(listElement, channels, onSelect) {
  listElement.innerHTML = ''
  channels.forEach((channel) => {
    const item = document.createElement('li')
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = channel.branding.display_name
    button.style.setProperty('--civiccast-brand', channel.branding.color ?? '#2458A6')
    button.addEventListener('click', () => onSelect(channel))
    item.append(button)
    listElement.append(item)
  })
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
