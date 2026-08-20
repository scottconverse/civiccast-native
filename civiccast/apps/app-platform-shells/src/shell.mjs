const DEFAULT_CONFIG_URL = '/api/public/app/config'

export async function loadStationConfig(configUrl = DEFAULT_CONFIG_URL) {
  return loadJson(configUrl)
}

export function selectDefaultChannel(config) {
  return (
    config.channels.find((channel) => channel.channel_id === config.default_channel_id) ??
    config.channels[0] ??
    null
  )
}

export async function loadChannelExperience(configUrl = DEFAULT_CONFIG_URL) {
  const config = await loadStationConfig(configUrl)
  const channel = selectDefaultChannel(config)
  if (!channel) {
    return { config, channel: null, live: null, schedule: [], catalog: null, errors: {} }
  }
  const [liveResult, scheduleResult, catalogResult] = await Promise.allSettled([
    loadJson(channel.live_state_url),
    loadJson(channel.schedule_feed_url),
    loadJson(channel.vod_catalog_url),
  ])
  const schedule = valueOrNull(scheduleResult)
  return {
    config,
    channel,
    live: valueOrNull(liveResult),
    schedule: Array.isArray(schedule) ? schedule : [],
    catalog: valueOrNull(catalogResult),
    errors: {
      live: errorMessage(liveResult),
      schedule: errorMessage(scheduleResult),
      catalog: errorMessage(catalogResult),
    },
  }
}

export function renderShell(root, experience, platformLabel) {
  const config = experience.config ?? experience
  const channel = experience.channel ?? selectDefaultChannel(config)
  const live = experience.live ?? null
  const schedule = Array.isArray(experience.schedule) ? experience.schedule : []
  const catalog = experience.catalog ?? null
  const errors = experience.errors ?? {}
  const firstCatalogItem = catalog?.items?.[0] ?? null
  const channelName = channel?.branding?.display_name ?? 'No channel configured'
  const brandColor = channel?.branding?.color ?? '#2458A6'

  root.innerHTML = ''
  root.style?.setProperty?.('--civiccast-brand', brandColor)
  root.append(
    section('Station', config.station_name),
    section('Platform', platformLabel),
    section('Channel', channelName),
    section('Brand', `${channel?.branding?.logo_text ?? 'CC'} ${brandColor}`),
    section('Live', errors.live ?? (live ? liveSummary(live) : channel?.live_state_url ?? 'No live state URL')),
    section('Captions', trackSummary(live?.caption_tracks, firstCatalogItem?.captions)),
    section('Audio', trackSummary(live?.audio_tracks, firstCatalogItem?.audio_tracks)),
    section('Schedule', errors.schedule ?? scheduleSummary(schedule)),
    section('VOD', errors.catalog ?? catalogSummary(catalog)),
    section('Chapters', chapterSummary(firstCatalogItem?.chapters)),
    section('Build Tier', config.build_profile?.tier ?? 'unbranded'),
  )
  root.dataset.ready = 'true'
}

function valueOrNull(result) {
  return result.status === 'fulfilled' ? result.value : null
}

function errorMessage(result) {
  if (result.status === 'fulfilled') return null
  return `Feed unavailable: ${result.reason?.message ?? String(result.reason)}`
}

export async function bootShell({ platformLabel, configUrl = DEFAULT_CONFIG_URL } = {}) {
  const root = document.querySelector('[data-civiccast-shell]')
  if (!root) return
  const params = new URLSearchParams(window.location.search)
  const resolvedConfigUrl = params.get('config') ?? configUrl
  try {
    const experience = await loadChannelExperience(resolvedConfigUrl)
    renderShell(experienceRoot(root), experience, platformLabel ?? root.dataset.appTarget ?? 'CivicCast app')
  } catch (error) {
    root.innerHTML = ''
    root.append(section('Station', 'CivicCast'), section('Status', error.message))
    root.dataset.ready = 'error'
  }
}

async function loadJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`.trim())
  }
  return response.json()
}

function experienceRoot(root) {
  return root
}

function liveSummary(live) {
  const label = live.state === 'fallback' ? live.fallback_reason : live.title
  return `${live.state}: ${label ?? live.playback_url ?? 'no active program'}`
}

function trackSummary(primaryTracks = [], secondaryTracks = []) {
  const tracks = primaryTracks.length ? primaryTracks : secondaryTracks
  if (!tracks?.length) return 'None advertised'
  return tracks.map((track) => `${track.label} (${track.language})`).join(', ')
}

function scheduleSummary(schedule) {
  if (!schedule.length) return 'No scheduled programs'
  return schedule
    .slice(0, 2)
    .map((item) => `${item.title} - ${item.kind}`)
    .join(' | ')
}

function catalogSummary(catalog) {
  if (!catalog?.items?.length) return 'No published VOD'
  const item = catalog.items[0]
  const playlistCount = catalog.playlists?.length ?? 0
  return `${item.title} (${item.publish_state}); ${playlistCount} playlists`
}

function chapterSummary(chapters = []) {
  if (!chapters?.length) return 'No chapters advertised'
  return chapters.map((chapter) => chapter.title).join(' | ')
}

function section(label, value) {
  const element = document.createElement('section')
  const heading = document.createElement('h2')
  const body = document.createElement('p')
  heading.textContent = label
  body.textContent = value
  element.append(heading, body)
  return element
}
