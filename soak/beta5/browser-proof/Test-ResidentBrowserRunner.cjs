// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { runProof } = require('./Run-ResidentBrowserProof.cjs')

const ORIGIN = 'http://127.0.0.1:8000'
const ASSET = 'approved-asset-1'
const MASTER_URL = `${ORIGIN}/media/vod/${ASSET}/playlist.m3u8`
const MASTER = [
  '#EXTM3U',
  '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="en",NAME="English",DEFAULT=YES,AUTOSELECT=YES,URI="captions/en/playlist.m3u8"',
  '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="es",NAME="Spanish",DEFAULT=NO,AUTOSELECT=YES,URI="captions/es/playlist.m3u8"',
  '#EXT-X-STREAM-INF:BANDWIDTH=414000,SUBTITLES="subtitles"',
  '240p/playlist.m3u8',
  '',
].join('\n')
const VARIANT = '#EXTM3U\n#EXTINF:4.000,\nseg000.ts\n#EXT-X-ENDLIST\n'

function subtitlePlaylist(language) {
  return '#EXTM3U\n#EXTINF:4.000,\nseg000.vtt\n#EXT-X-ENDLIST\n'
}

function vtt(language, wrongText = false) {
  const text = wrongText ? 'Unrelated cue' : (language === 'en' ? 'English cue' : 'Spanish cue')
  return `WEBVTT\n\ncue-${language}\n00:00:00.000 --> 00:00:04.000\n${text}\n`
}

class FakeRequest {
  constructor(url, method, headers = {}) { this._url = url; this._method = method; this._headers = headers }
  url() { return this._url }
  method() { return this._method }
  async allHeaders() { return this._headers }
  redirectedFrom() { return null }
}

class FakeResponse {
  constructor(request, status, body, contentType) {
    this._request = request
    this._status = status
    this._body = Buffer.from(body)
    this._contentType = contentType
  }
  url() { return this._request.url() }
  status() { return this._status }
  headers() { return { 'content-type': this._contentType } }
  request() { return this._request }
  async body() { return this._body }
}

class FakeVideo {
  constructor() {
    this.duration = 6
    this.currentTime = 0
    this.readyState = 4
    this.videoWidth = 640
    this.videoHeight = 360
    this.error = null
    this.paused = true
    this.ended = false
    const cue = (language) => ({
      id: `cue-${language}`,
      startTime: 0,
      endTime: 4,
      text: language === 'en' ? 'English cue' : 'Spanish cue',
    })
    this.textTracks = ['en', 'es'].map((language) => ({
      language,
      label: language === 'en' ? 'English' : 'Spanish',
      mode: 'disabled',
      cues: [cue(language)],
      activeCues: [],
    }))
  }
  pause() { this.paused = true }
  async play() { this.paused = false }
  addEventListener() {}
  removeEventListener() {}
}

class FakePage {
  constructor(context, scenario) {
    this.context = context
    this.scenario = scenario
    this.responses = []
    this.video = new FakeVideo()
    this.buttons = { Off: 'true', English: 'false', Spanish: 'false' }
    this.waitCalls = 0
  }
  setDefaultTimeout() {}
  setDefaultNavigationTimeout() {}
  on(name, callback) { if (name === 'response') this.responses.push(callback) }
  async dispatch(url, method = 'GET', body = '', contentType = 'text/plain', headers = {}) {
    const request = new FakeRequest(url, method, headers)
    let continued = false
    const route = {
      request: () => request,
      continue: async () => { continued = true },
      abort: async () => { continued = false },
    }
    await this.context.routeHandler(route)
    if (continued && body !== null) {
      const response = new FakeResponse(request, 200, body, contentType)
      for (const callback of this.responses) callback(response)
    }
    return continued
  }
  async goto() {
    if (this.scenario.hangGoto) return new Promise(() => {})
    await this.dispatch(`${ORIGIN}/`, 'GET', '<html></html>', 'text/html')
    await this.dispatch(`${ORIGIN}/api/public/assets/${ASSET}`, 'GET', JSON.stringify({ asset_id: ASSET, manifest_url: `/media/vod/${ASSET}/playlist.m3u8` }), 'application/json')
    await this.dispatch(MASTER_URL, 'GET', MASTER, 'application/vnd.apple.mpegurl')
    await this.dispatch(`${ORIGIN}/media/vod/${ASSET}/240p/playlist.m3u8`, 'GET', VARIANT, 'application/vnd.apple.mpegurl')
    if (this.scenario.prefetchedCaptions) {
      await this.emitCaption('en')
      await this.emitCaption('es')
    }
    if (this.scenario.extraAuthorization) await this.dispatch(`${ORIGIN}/private-leak`, 'GET', null, 'text/plain', { Authorization: 'Bearer forbidden' })
    if (this.scenario.extraMutation) await this.dispatch(`${ORIGIN}/api/public/unexpected`, 'POST', null)
    if (this.scenario.extraOrigin) await this.dispatch('https://example.test/leak', 'GET', null)
  }
  async emitCaption(language) {
    const root = `${ORIGIN}/media/vod/${ASSET}/captions/${language}`
    await this.dispatch(`${root}/playlist.m3u8`, 'GET', subtitlePlaylist(language), 'application/vnd.apple.mpegurl')
    await this.dispatch(`${root}/seg000.vtt`, 'GET', vtt(language, this.scenario.wrongVtt), 'text/vtt')
  }
  locator(selector) {
    assert.equal(selector, 'video[aria-label="Meeting video player"]')
    return {
      waitFor: async () => {},
      evaluate: async (callback, argument) => callback(this.video, argument),
    }
  }
  getByRole(role, options) {
    assert.equal(role, 'button')
    const name = options.name
    return {
      waitFor: async () => {},
      click: async () => {
        for (const key of Object.keys(this.buttons)) this.buttons[key] = key === name ? 'true' : 'false'
        if (name === 'Off') {
          for (const track of this.video.textTracks) { track.mode = 'disabled'; track.activeCues = [] }
          return
        }
        const requested = name === 'English' ? 'en' : 'es'
        const actual = this.scenario.wrongTrack ? (requested === 'en' ? 'es' : 'en') : requested
        for (const track of this.video.textTracks) {
          track.mode = (!this.scenario.cosmeticButton && track.language === actual) ? 'showing' : 'disabled'
          track.activeCues = track.mode === 'showing' && !this.scenario.noCue ? [track.cues[0]] : []
          if (this.scenario.noCue && track.language === actual) track.cues = []
        }
        this.video.currentTime = 0.5
        if (!this.scenario.prefetchedCaptions) await this.emitCaption(requested)
      },
      getAttribute: async (attribute) => attribute === 'aria-pressed' ? this.buttons[name] : null,
    }
  }
  async waitForFunction() {
    this.waitCalls += 1
    if (this.waitCalls >= 2) this.video.currentTime = 3.2
  }
}

class FakeContext {
  constructor(scenario, userDataDir, options) {
    this.scenario = scenario
    this.userDataDir = userDataDir
    this.options = options
    this.page = new FakePage(this, scenario)
    this.routeHandler = null
  }
  async route(pattern, handler) { assert.equal(pattern, '**/*'); this.routeHandler = handler }
  pages() { return [this.page] }
  browser() { return { version: () => 'fake-browser-1' } }
  async close() { if (this.scenario.cleanupFailure) throw new Error('injected cleanup failure') }
}

function fakePlaywright(scenario, observation) {
  return {
    chromium: {
      launchPersistentContext: async (userDataDir, options) => {
        observation.userDataDir = userDataDir
        observation.options = options
        return new FakeContext(scenario, userDataDir, options)
      },
    },
  }
}

async function runScenario(scenario, timeoutMs = 700) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'civiccast-browser-runner-test-'))
  try {
    const playwrightRoot = path.join(root, 'playwright-core')
    const browser = path.join(root, 'msedge.exe')
    const evidence = path.join(root, 'evidence')
    fs.mkdirSync(playwrightRoot)
    fs.writeFileSync(path.join(playwrightRoot, 'package.json'), '{"name":"playwright-core","version":"test"}')
    fs.writeFileSync(browser, 'fake browser, never executed')
    const observation = {}
    const before = Date.now()
    const report = await runProof({
      playwrightCore: playwrightRoot,
      browserExecutable: browser,
      assetId: ASSET,
      candidateSourceSha: 'a'.repeat(40),
      evidenceDir: evidence,
      timeoutMs,
    }, { playwright: fakePlaywright(scenario, observation) })
    const elapsed = Date.now() - before
    const persisted = JSON.parse(fs.readFileSync(path.join(evidence, 'resident-browser-proof.json'), 'utf8'))
    assert.equal(persisted.verdict, report.verdict)
    assert.ok(observation.userDataDir.startsWith(evidence + path.sep))
    assert.equal(observation.options.headless, true)
    assert.equal(observation.options.serviceWorkers, 'block')
    assert.ok(observation.options.env.USERPROFILE.startsWith(evidence + path.sep))
    return { report, elapsed }
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
}

;(async () => {
  const success = await runScenario({ prefetchedCaptions: true }, 1500)
  assert.equal(success.report.verdict, 'PASS')
  assert.deepEqual(success.report.caption_buttons.map((entry) => entry.selected_track.language), ['en', 'es'])
  assert.ok(success.report.caption_buttons.every((entry) => entry.selected_track.mode === 'showing'))
  assert.ok(success.report.caption_buttons.every((entry) => entry.selected_track.active_cue.text_sha256.length === 64))
  assert.ok(success.report.caption_buttons.every((entry) => entry.fetched_same_language_vtt_cue_match))

  const cosmetic = (await runScenario({ cosmeticButton: true })).report
  assert.equal(cosmetic.verdict, 'FAIL')
  assert.match(cosmetic.error, /browser text track is showing an active cue/u)
  const wrong = (await runScenario({ wrongTrack: true })).report
  assert.equal(wrong.verdict, 'FAIL')
  assert.match(wrong.error, /browser text track is showing an active cue/u)
  const noCue = (await runScenario({ noCue: true })).report
  assert.equal(noCue.verdict, 'FAIL')
  assert.match(noCue.error, /browser text track is showing an active cue/u)
  const wrongVtt = (await runScenario({ wrongVtt: true })).report
  assert.equal(wrongVtt.verdict, 'FAIL')
  assert.match(wrongVtt.error, /binding the active English browser cue to fetched WebVTT/u)
  const authorization = (await runScenario({ extraAuthorization: true })).report
  assert.equal(authorization.verdict, 'FAIL')
  assert.ok(authorization.anonymous_boundary.non_loopback_or_unexpected_requests.some((entry) => entry.kind === 'authorization_header'))
  const mutation = (await runScenario({ extraMutation: true })).report
  assert.equal(mutation.verdict, 'FAIL')
  assert.ok(mutation.anonymous_boundary.non_loopback_or_unexpected_requests.some((entry) => entry.kind === 'mutation_request'))
  const origin = (await runScenario({ extraOrigin: true })).report
  assert.equal(origin.verdict, 'FAIL')
  assert.ok(origin.anonymous_boundary.non_loopback_or_unexpected_requests.some((entry) => entry.kind === 'non_loopback_request'))
  const cleanup = await runScenario({ cleanupFailure: true }, 1500)
  assert.equal(cleanup.report.verdict, 'FAIL')
  assert.match(cleanup.report.cleanup_error, /injected cleanup failure/u)
  const deadline = await runScenario({ hangGoto: true }, 350)
  assert.equal(deadline.report.verdict, 'FAIL')
  assert.ok(deadline.elapsed < 1000, `global deadline took ${deadline.elapsed}ms`)

  process.stdout.write('PASS: full fake-browser runner rejects cosmetic/wrong/empty tracks, request-boundary violations, cleanup failure, and global-deadline expiry; cached real-response evidence remains valid.\n')
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`)
  process.exitCode = 1
})
