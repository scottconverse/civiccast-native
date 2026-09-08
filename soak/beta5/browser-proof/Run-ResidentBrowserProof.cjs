// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const {
  LOOPBACK_ORIGIN,
  assertAssetId,
  assertLoopbackUrl,
  parseMasterPlaylist,
  parseMediaPlaylist,
  parseWebVttCues,
  assertWebVtt,
  sha256,
} = require('./BrowserProof.Contracts.cjs')

const SCHEMA = 'civiccast-native-beta5-resident-browser-proof-v1'

function invariant(condition, message) {
  if (!condition) throw new Error(message)
}

function parseArguments(argv) {
  const allowed = new Set([
    '--playwright-core', '--browser-executable', '--asset-id', '--candidate-source-sha',
    '--evidence-dir', '--timeout-seconds',
  ])
  const values = Object.create(null)
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index]
    invariant(allowed.has(name), `Unknown or misplaced argument '${name || '(missing)'}'.`)
    invariant(index + 1 < argv.length, `Argument '${name}' has no value.`)
    invariant(!(name in values), `Argument '${name}' was supplied more than once.`)
    values[name] = argv[index + 1]
  }
  for (const name of allowed) invariant(name in values, `Required argument '${name}' is absent.`)
  return values
}

function assertNoSymlinkPath(inputPath, label) {
  const absolute = path.resolve(inputPath)
  invariant(path.isAbsolute(inputPath), `${label} must be absolute.`)
  let cursor = absolute
  while (true) {
    if (fs.existsSync(cursor)) {
      invariant(!fs.lstatSync(cursor).isSymbolicLink(), `${label} crosses a symbolic link or junction.`)
    }
    const parent = path.dirname(cursor)
    if (parent === cursor) break
    cursor = parent
  }
  return absolute
}

function safeBrowserEnvironment(profileRoot) {
  const environment = Object.create(null)
  for (const name of ['SystemRoot', 'SYSTEMROOT', 'WINDIR', 'ComSpec', 'COMSPEC', 'PATH', 'PATHEXT']) {
    if (process.env[name]) environment[name] = process.env[name]
  }
  const roaming = path.join(profileRoot, 'roaming')
  const local = path.join(profileRoot, 'local')
  const home = path.join(profileRoot, 'home')
  const temp = path.join(profileRoot, 'temp')
  for (const directory of [roaming, local, home, temp]) fs.mkdirSync(directory, { recursive: true })
  environment.APPDATA = roaming
  environment.LOCALAPPDATA = local
  environment.USERPROFILE = home
  environment.HOME = home
  environment.TEMP = temp
  environment.TMP = temp
  environment.HOMEDRIVE = path.parse(home).root.replace(/[\\/]$/u, '')
  environment.HOMEPATH = home.slice(path.parse(home).root.length - 1)
  return environment
}

function responseEvidence(record) {
  return {
    url: record.url,
    status: record.status,
    content_type: record.contentType,
    bytes: record.body.length,
    sha256: sha256(record.body),
    redirected: record.redirected,
  }
}

async function withTimeout(promise, timeoutMs, label) {
  let timer
  try {
    return await Promise.race([
      promise,
      new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`Timed out while ${label}.`)), timeoutMs)
      }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

function remainingMs(deadline, label) {
  const remaining = deadline - Date.now()
  invariant(remaining > 0, `Global proof deadline expired while ${label}.`)
  return remaining
}

async function withDeadline(promise, deadline, label) {
  return withTimeout(promise, remainingMs(deadline, label), label)
}

async function waitForRecord(records, pending, url, deadline, label) {
  while (Date.now() < deadline) {
    await withDeadline(Promise.allSettled([...pending]), deadline, `waiting for ${label} response bodies`)
    const match = records.find((record) => record.url === url && record.status === 200 && record.body)
    if (match) return match
    await withDeadline(new Promise((resolve) => setTimeout(resolve, 50)), deadline, `waiting for ${label}`)
  }
  throw new Error(`Timed out waiting for a 200 ${label}: ${url}`)
}

async function waitForAnyRecord(records, pending, urls, deadline, label) {
  while (Date.now() < deadline) {
    await withDeadline(Promise.allSettled([...pending]), deadline, `waiting for ${label} response bodies`)
    const match = records.find((record) => urls.includes(record.url) && record.status === 200 && record.body)
    if (match) return match
    await withDeadline(new Promise((resolve) => setTimeout(resolve, 50)), deadline, `waiting for ${label}`)
  }
  throw new Error(`Timed out waiting for a 200 ${label}.`)
}

async function pollUntil(callback, deadline, label) {
  while (Date.now() < deadline) {
    const value = await withDeadline(Promise.resolve(callback()), deadline, label)
    if (value) return value
    await withDeadline(new Promise((resolve) => setTimeout(resolve, 50)), deadline, label)
  }
  throw new Error(`Global proof deadline expired while ${label}.`)
}

async function readTextTrackState(video, language, deadline) {
  return withDeadline(video.evaluate((element, expectedLanguage) => {
    const tracks = Array.from(element.textTracks || []).map((track, index) => {
      const cues = Array.from(track.cues || []).map((cue) => ({
        id: String(cue.id || ''),
        start_time: Number(cue.startTime),
        end_time: Number(cue.endTime),
        text: String(cue.text || ''),
      }))
      const activeCues = Array.from(track.activeCues || []).map((cue) => ({
        id: String(cue.id || ''),
        start_time: Number(cue.startTime),
        end_time: Number(cue.endTime),
        text: String(cue.text || ''),
      }))
      return {
        index,
        language: String(track.language || '').toLowerCase(),
        label: String(track.label || ''),
        mode: String(track.mode || ''),
        cues,
        active_cues: activeCues,
      }
    })
    return {
      current_time: Number(element.currentTime),
      paused: Boolean(element.paused),
      ended: Boolean(element.ended),
      tracks,
      expected: tracks.find((track) => track.language === expectedLanguage) || null,
      showing_languages: tracks.filter((track) => track.mode === 'showing').map((track) => track.language),
    }
  }, language), deadline, `reading the ${language} browser text track`)
}

async function selectOff(page, video, deadline) {
  const button = page.getByRole('button', { name: 'Off', exact: true })
  await button.waitFor({ state: 'visible', timeout: remainingMs(deadline, 'finding the Off caption button') })
  await button.click({ timeout: remainingMs(deadline, 'clicking the Off caption button') })
  return pollUntil(async () => {
    const ariaPressed = await button.getAttribute('aria-pressed')
    if (ariaPressed !== 'true') return null
    const state = await readTextTrackState(video, '', deadline)
    return state.tracks.length > 0 && state.tracks.every((track) => track.mode === 'disabled') ? state : null
  }, deadline, 'proving captions are actually off before selection')
}

async function restartMutedPlayback(video, deadline) {
  const inPageTimeout = Math.min(10000, remainingMs(deadline, 'restarting muted playback'))
  return withDeadline(video.evaluate(async (element, playTimeout) => {
    element.pause()
    element.muted = true
    if (!Number.isFinite(element.duration) || element.duration < 3) {
      throw new Error('Approved asset duration is too short for a three-second playback proof.')
    }
    await new Promise((resolve) => {
      const finish = () => {
        clearTimeout(timer)
        element.removeEventListener('seeked', finish)
        resolve()
      }
      const timer = setTimeout(finish, Math.min(2000, playTimeout))
      element.addEventListener('seeked', finish, { once: true })
      element.currentTime = 0
      if (element.currentTime <= 0.05) finish()
    })
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Timed out starting video playback.')), playTimeout)
      element.play().then(
        () => { clearTimeout(timer); resolve() },
        (error) => { clearTimeout(timer); reject(error) },
      )
    })
    return {
      current_time: element.currentTime,
      duration: element.duration,
      ready_state: element.readyState,
      media_error_code: element.error ? element.error.code : null,
    }
  }, inPageTimeout), deadline, 'restarting muted playback')
}

async function selectActualTextTrack(page, video, name, language, deadline) {
  const button = page.getByRole('button', { name, exact: true })
  await button.waitFor({ state: 'visible', timeout: remainingMs(deadline, `finding the ${name} caption button`) })
  await button.click({ timeout: remainingMs(deadline, `clicking the ${name} caption button`) })
  return pollUntil(async () => {
    const ariaPressed = await button.getAttribute('aria-pressed')
    if (ariaPressed !== 'true') return null
    const state = await readTextTrackState(video, language, deadline)
    if (!state.expected || state.expected.mode !== 'showing') return null
    if (state.showing_languages.length !== 1 || state.showing_languages[0] !== language) return null
    if (state.expected.cues.length === 0 || state.expected.active_cues.length === 0 || state.paused || state.ended) return null
    const active = state.expected.active_cues.find((cue) => (
      Number.isFinite(cue.start_time) && Number.isFinite(cue.end_time) && cue.text.trim() &&
      cue.start_time <= state.current_time && cue.end_time >= state.current_time
    ))
    return active ? { state, active, aria_pressed: ariaPressed } : null
  }, deadline, `proving the ${name} browser text track is showing an active cue`)
}

async function bindActiveCueToFetchedVtt(records, pending, vttUrls, selection, deadline, label) {
  return pollUntil(async () => {
    await withDeadline(Promise.allSettled([...pending]), deadline, `waiting for ${label} WebVTT response bodies`)
    for (const record of records.filter((item) => vttUrls.includes(item.url) && item.status === 200 && item.body)) {
      const cues = parseWebVttCues(record.body.toString('utf8'), `${label} WebVTT`)
      const match = cues.find((cue) => (
        Math.abs(cue.start_time - selection.active.start_time) <= 0.05 &&
        Math.abs(cue.end_time - selection.active.end_time) <= 0.05 &&
        cue.text.trim() === selection.active.text.trim()
      ))
      if (match) return { record, cue: match }
    }
    return null
  }, deadline, `binding the active ${label} browser cue to fetched WebVTT`)
}

async function runProof(configuration, dependencies = {}) {
  const totalDeadline = Date.now() + configuration.timeoutMs
  const cleanupReserveMs = Math.min(15000, Math.max(100, Math.floor(configuration.timeoutMs / 3)))
  const proofDeadline = totalDeadline - cleanupReserveMs
  const playwrightRoot = assertNoSymlinkPath(configuration.playwrightCore, 'Playwright Core path')
  const browserExecutable = assertNoSymlinkPath(configuration.browserExecutable, 'Browser executable path')
  invariant(fs.statSync(playwrightRoot).isDirectory(), 'Playwright Core path is not a directory.')
  invariant(fs.statSync(browserExecutable).isFile(), 'Browser executable path is not a file.')
  const packageMetadata = JSON.parse(fs.readFileSync(path.join(playwrightRoot, 'package.json'), 'utf8'))
  invariant(packageMetadata.name === 'playwright-core', 'Explicit module path is not the playwright-core package.')
  // Loading is deliberately by the operator-supplied absolute path. No Node
  // search path, npm command, install, or download is used.
  const playwright = dependencies.playwright || require(playwrightRoot)
  invariant(playwright && playwright.chromium, 'Explicit playwright-core package does not export Chromium support.')

  const evidenceDir = assertNoSymlinkPath(configuration.evidenceDir, 'Evidence directory')
  invariant(!fs.existsSync(evidenceDir), 'Evidence directory already exists.')
  fs.mkdirSync(evidenceDir)
  const privateRoot = fs.mkdtempSync(path.join(evidenceDir, '.browser-private-'))
  const userDataDir = path.join(privateRoot, 'user-data')
  fs.mkdirSync(userDataDir)

  const watchUrl = `${LOOPBACK_ORIGIN}/#/watch/${encodeURIComponent(configuration.assetId)}`
  const assetApiUrl = `${LOOPBACK_ORIGIN}/api/public/assets/${encodeURIComponent(configuration.assetId)}`
  const records = []
  const pendingBodies = new Set()
  const blockedAnalytics = []
  const boundaryViolations = []
  let context = null
  let report
  const startedUtc = new Date().toISOString()
  try {
    context = await withDeadline(playwright.chromium.launchPersistentContext(userDataDir, {
      executablePath: browserExecutable,
      headless: true,
      acceptDownloads: false,
      serviceWorkers: 'block',
      timeout: remainingMs(proofDeadline, 'launching the isolated browser'),
      env: safeBrowserEnvironment(privateRoot),
      args: [
        '--autoplay-policy=no-user-gesture-required',
        '--disable-background-networking',
        '--disable-component-update',
        '--disable-sync',
        '--metrics-recording-only',
        '--no-default-browser-check',
        '--no-first-run',
      ],
    }), proofDeadline, 'launching the isolated browser')
    await withDeadline(context.route('**/*', async (route) => {
      const request = route.request()
      const method = request.method().toUpperCase()
      let parsed
      try {
        parsed = new URL(request.url())
      } catch {
        boundaryViolations.push({ kind: 'invalid_url', method })
        await route.abort('blockedbyclient')
        return
      }
      if (parsed.origin !== LOOPBACK_ORIGIN || parsed.username || parsed.password) {
        boundaryViolations.push({ kind: 'non_loopback_request', method, origin: parsed.origin })
        await route.abort('blockedbyclient')
        return
      }
      const headers = await request.allHeaders()
      if (Object.keys(headers).some((name) => name.toLowerCase() === 'authorization')) {
        boundaryViolations.push({ kind: 'authorization_header', method, path: parsed.pathname })
        await route.abort('blockedbyclient')
        return
      }
      if (method !== 'GET' && method !== 'HEAD') {
        if (method === 'POST' && parsed.pathname === '/api/public/app/analytics/events') {
          blockedAnalytics.push({ method, path: parsed.pathname })
        } else {
          boundaryViolations.push({ kind: 'mutation_request', method, path: parsed.pathname })
        }
        await route.abort('blockedbyclient')
        return
      }
      await route.continue()
    }), proofDeadline, 'installing the browser network guard')

    const pages = context.pages()
    const page = pages.length > 0 ? pages[0] : await context.newPage()
    page.setDefaultTimeout(remainingMs(proofDeadline, 'configuring the page'))
    page.setDefaultNavigationTimeout(remainingMs(proofDeadline, 'configuring navigation'))
    page.on('response', (response) => {
      const parsed = new URL(response.url())
      if (parsed.origin !== LOOPBACK_ORIGIN) return
      const shouldRead = parsed.pathname.endsWith('.m3u8') || parsed.pathname.endsWith('.vtt') || response.url() === assetApiUrl
      if (!shouldRead) return
      const task = (async () => {
        const body = await withDeadline(response.body(), proofDeadline, `reading ${response.url()}`)
        records.push({
          url: response.url(),
          status: response.status(),
          contentType: response.headers()['content-type'] || null,
          redirected: response.request().redirectedFrom() !== null,
          body,
        })
      })().catch((error) => {
        records.push({
          url: response.url(),
          status: response.status(),
          contentType: response.headers()['content-type'] || null,
          redirected: response.request().redirectedFrom() !== null,
          body: null,
          bodyError: error instanceof Error ? error.message : String(error),
        })
      }).finally(() => pendingBodies.delete(task))
      pendingBodies.add(task)
    })

    await withDeadline(
      page.goto(watchUrl, { waitUntil: 'domcontentloaded', timeout: remainingMs(proofDeadline, 'opening the watch route') }),
      proofDeadline,
      'opening the watch route',
    )
    const assetRecord = await waitForRecord(records, pendingBodies, assetApiUrl, proofDeadline, 'public asset response')
    invariant(!assetRecord.redirected, 'Public asset response was redirected.')
    const asset = JSON.parse(assetRecord.body.toString('utf8'))
    invariant(asset.asset_id === configuration.assetId, 'Public asset response does not match the exact approved asset ID.')
    invariant(typeof asset.manifest_url === 'string' && asset.manifest_url.length > 0, 'Public asset response has no manifest URL.')
    const masterUrl = assertLoopbackUrl(new URL(asset.manifest_url, LOOPBACK_ORIGIN).href, 'Published manifest URL').href

    const video = page.locator('video[aria-label="Meeting video player"]')
    await video.waitFor({ state: 'visible', timeout: remainingMs(proofDeadline, 'finding the video element') })
    const masterRecord = await waitForRecord(records, pendingBodies, masterUrl, proofDeadline, 'master playlist')
    invariant(!masterRecord.redirected, 'Master playlist response was redirected.')
    const master = parseMasterPlaylist(masterRecord.body.toString('utf8'), masterUrl)

    await page.waitForFunction(() => {
      const element = document.querySelector('video[aria-label="Meeting video player"]')
      return Boolean(element && !element.error && Number.isFinite(element.duration) && element.duration >= 3)
    }, undefined, { timeout: remainingMs(proofDeadline, 'waiting for video metadata') })
    const buttonProof = []
    const subtitleEvidence = Object.create(null)
    let playbackStart = null
    for (const { name, language } of [{ name: 'English', language: 'en' }, { name: 'Spanish', language: 'es' }]) {
      const before = await selectOff(page, video, proofDeadline)
      const start = await restartMutedPlayback(video, proofDeadline)
      if (language === 'es') playbackStart = start
      const selection = await selectActualTextTrack(page, video, name, language, proofDeadline)
      const subtitleUrl = master.subtitles[language].url
      const subtitleRecord = await waitForRecord(records, pendingBodies, subtitleUrl, proofDeadline, `${name} subtitle playlist`)
      invariant(!subtitleRecord.redirected, `${name} subtitle playlist was redirected.`)
      const subtitle = parseMediaPlaylist(subtitleRecord.body.toString('utf8'), subtitleUrl, 'subtitle')
      const vttUrls = subtitle.references.filter((url) => new URL(url).pathname.toLowerCase().endsWith('.vtt'))
      const binding = await bindActiveCueToFetchedVtt(records, pendingBodies, vttUrls, selection, proofDeadline, name)
      invariant(!binding.record.redirected, `${name} WebVTT response was redirected.`)
      assertWebVtt(binding.record.body.toString('utf8'), `${name} WebVTT`)
      const activeText = Buffer.from(selection.active.text, 'utf8')
      buttonProof.push({
        label: name,
        language,
        aria_pressed: selection.aria_pressed,
        before_showing_languages: before.showing_languages,
        selected_track: {
          index: selection.state.expected.index,
          language: selection.state.expected.language,
          label: selection.state.expected.label,
          mode: selection.state.expected.mode,
          cue_count: selection.state.expected.cues.length,
          active_cue: {
            id: selection.active.id,
            start_time: selection.active.start_time,
            end_time: selection.active.end_time,
            observed_at: selection.state.current_time,
            text_bytes: activeText.length,
            text_sha256: sha256(activeText),
          },
        },
        fetched_same_language_vtt_cue_match: true,
      })
      subtitleEvidence[language] = {
        playlist: responseEvidence(subtitleRecord),
        matched_fetched_vtt: responseEvidence(binding.record),
      }
    }

    await page.waitForFunction(() => {
      const element = document.querySelector('video[aria-label="Meeting video player"]')
      return Boolean(element && !element.error && element.currentTime >= 3)
    }, undefined, { timeout: remainingMs(proofDeadline, 'waiting for three seconds of playback') })
    const playbackEnd = await withDeadline(video.evaluate((element) => ({
      current_time: element.currentTime,
      duration: element.duration,
      ready_state: element.readyState,
      video_width: element.videoWidth,
      video_height: element.videoHeight,
      ended: element.ended,
      media_error_code: element.error ? element.error.code : null,
    })), proofDeadline, 'reading final playback state')
    invariant(playbackStart !== null, 'Spanish playback start was not recorded.')
    invariant(playbackEnd.current_time >= 3, 'Video currentTime did not reach three seconds.')
    invariant(playbackEnd.current_time > playbackStart.current_time, 'Video currentTime did not advance.')
    invariant(playbackEnd.media_error_code === null, 'Video element reported a media error.')
    invariant(playbackEnd.ready_state >= 2, 'Video element never reached current-data readiness.')
    invariant(playbackEnd.video_width > 0 && playbackEnd.video_height > 0, 'Video element has no decoded dimensions.')

    const selectedVariant = await waitForAnyRecord(
      records,
      pendingBodies,
      master.variants,
      proofDeadline,
      'declared HLS variant playlist',
    )
    invariant(!selectedVariant.redirected, 'Variant playlist response was redirected.')
    parseMediaPlaylist(selectedVariant.body.toString('utf8'), selectedVariant.url, 'variant')

    invariant(boundaryViolations.length === 0, `Browser boundary violations occurred: ${JSON.stringify(boundaryViolations)}`)
    report = {
      schema: SCHEMA,
      verdict: 'PASS',
      started_utc: startedUtc,
      completed_utc: new Date().toISOString(),
      timeout_seconds: configuration.timeoutMs / 1000,
      candidate_source_sha: configuration.candidateSourceSha,
      asset_id: configuration.assetId,
      watch_url: watchUrl,
      tooling: {
        node_executable: process.execPath,
        node_version: process.version,
        playwright_core_path: playwrightRoot,
        playwright_core_version: String(packageMetadata.version || ''),
        browser_executable: browserExecutable,
        browser_version: context.browser() ? context.browser().version() : null,
      },
      anonymous_boundary: {
        authorization_headers_sent: 0,
        non_read_requests_sent: 0,
        analytics_posts_blocked_before_network: blockedAnalytics.length,
        non_loopback_or_unexpected_requests: boundaryViolations,
      },
      public_asset: responseEvidence(assetRecord),
      hls: {
        master: responseEvidence(masterRecord),
        declared_variants: master.variants,
        selected_variant: responseEvidence(selectedVariant),
        subtitles: subtitleEvidence,
      },
      playback: { initial: playbackStart, final: playbackEnd, minimum_current_time_seconds: 3 },
      caption_buttons: buttonProof,
      qualification: 'Actual anonymous resident browser playback and caption-control proof; not transcript editorial-accuracy certification.',
    }
  } catch (error) {
    report = {
      schema: SCHEMA,
      verdict: 'FAIL',
      started_utc: startedUtc,
      completed_utc: new Date().toISOString(),
      timeout_seconds: configuration.timeoutMs / 1000,
      candidate_source_sha: configuration.candidateSourceSha,
      asset_id: configuration.assetId,
      error: error instanceof Error ? error.message : String(error),
      anonymous_boundary: {
        authorization_headers_sent: 0,
        non_read_requests_sent: 0,
        analytics_posts_blocked_before_network: blockedAnalytics.length,
        non_loopback_or_unexpected_requests: boundaryViolations,
      },
    }
  } finally {
    let cleanupError = null
    if (context) {
      try {
        await withDeadline(context.close(), totalDeadline, 'closing the isolated browser context')
      } catch (error) {
        cleanupError = error instanceof Error ? error.message : String(error)
      }
    }
    try {
      fs.rmSync(privateRoot, { recursive: true, force: true })
    } catch (error) {
      cleanupError = cleanupError || (error instanceof Error ? error.message : String(error))
    }
    report.isolated_browser_profile_removed = !fs.existsSync(privateRoot)
    if (cleanupError || !report.isolated_browser_profile_removed) {
      report.verdict = 'FAIL'
      report.cleanup_error = cleanupError || 'Temporary browser profile remains after cleanup.'
    }
    const reportPath = path.join(evidenceDir, 'resident-browser-proof.json')
    const temporaryPath = `${reportPath}.${process.pid}.tmp`
    fs.writeFileSync(temporaryPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' })
    fs.renameSync(temporaryPath, reportPath)
  }
  return report
}

async function main() {
  const args = parseArguments(process.argv.slice(2))
  const assetId = assertAssetId(args['--asset-id'])
  invariant(/^[0-9a-f]{40}$/u.test(args['--candidate-source-sha']), 'Candidate source SHA must be lowercase 40hex.')
  const timeoutSeconds = Number(args['--timeout-seconds'])
  invariant(Number.isInteger(timeoutSeconds) && timeoutSeconds >= 30 && timeoutSeconds <= 120, 'Timeout must be an integer from 30 through 120 seconds.')
  const report = await runProof({
    playwrightCore: args['--playwright-core'],
    browserExecutable: args['--browser-executable'],
    assetId,
    candidateSourceSha: args['--candidate-source-sha'],
    evidenceDir: args['--evidence-dir'],
    timeoutMs: timeoutSeconds * 1000,
  })
  process.stdout.write(`${JSON.stringify({ schema: report.schema, verdict: report.verdict, asset_id: report.asset_id })}\n`)
  if (report.verdict !== 'PASS') process.exitCode = 1
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`Resident browser proof could not start: ${error instanceof Error ? error.message : String(error)}\n`)
    process.exitCode = 1
  })
}

module.exports = { parseArguments, runProof }
