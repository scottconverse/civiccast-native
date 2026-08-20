import assert from 'node:assert/strict'
import { mkdtemp, readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { test } from 'node:test'

const root = fileURLToPath(new URL('..', import.meta.url))
const targetsRoot = join(root, 'targets')
const expectedTargets = [
  ['android-mobile', 'android_mobile'],
  ['android-tv', 'android_tv'],
  ['fire-tv', 'fire_tv'],
  ['ios-ipados', 'ios_ipados'],
  ['roku', 'roku'],
  ['tvos', 'tvos'],
  ['web-pwa', 'web_pwa'],
]

test('all v1.8.2 app targets have a shell manifest and shared loader', async () => {
  const dirs = (await readdir(targetsRoot, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()

  assert.deepEqual(
    dirs,
    expectedTargets.map(([dir]) => dir).sort(),
  )

  for (const [dir, appTarget] of expectedTargets) {
    const manifest = JSON.parse(await readFile(join(targetsRoot, dir, 'manifest.json'), 'utf8'))
    const index = await readFile(join(targetsRoot, dir, 'index.html'), 'utf8')

    assert.equal(manifest.appTarget, appTarget)
    assert.equal(manifest.configUrl, '/api/public/app/config')
    assert.equal(manifest.status, 'v1.8.2 shared reference runtime')
    assert.deepEqual(manifest.capabilities, [
      'station-branding',
      'live-playback-metadata',
      'vod-smart-playlists',
      'schedule-browse',
      'captions',
      'audio-tracks',
      'chapters',
    ])
    assert.match(index, /data-civiccast-shell/)
    assert.match(index, /..\/..\/src\/shell.mjs/)
    assert.match(index, new RegExp(`data-app-target="${appTarget}"`))
  }
})

test('sample station config covers every public shell target', async () => {
  const fixture = JSON.parse(
    await readFile(join(root, 'fixtures', 'station-app-config.sample.json'), 'utf8'),
  )
  const targets = fixture.build_profile.platform_targets.slice().sort()
  const expected = expectedTargets.map(([, appTarget]) => appTarget).sort()

  assert.deepEqual(targets, expected)
  assert.equal(fixture.channels[0].channel_id, fixture.default_channel_id)
  assert.ok(fixture.channels[0].live_state_url)
  assert.ok(fixture.channels[0].schedule_feed_url)
  assert.ok(fixture.channels[0].vod_catalog_url)
})

test('shared shell runtime renders required app experience calls from one config', async () => {
  const shell = await readFile(join(root, 'src', 'shell.mjs'), 'utf8')

  assert.match(shell, /loadStationConfig/)
  assert.match(shell, /loadChannelExperience/)
  assert.match(shell, /live_state_url/)
  assert.match(shell, /schedule_feed_url/)
  assert.match(shell, /vod_catalog_url/)
  assert.match(shell, /caption_tracks/)
  assert.match(shell, /audio_tracks/)
  assert.match(shell, /chapters/)
})

test('shared shell runtime loads live schedule and vod from station contract', async () => {
  const { loadChannelExperience } = await import('../src/shell.mjs')
  const fixture = JSON.parse(
    await readFile(join(root, 'fixtures', 'station-app-config.sample.json'), 'utf8'),
  )
  const responses = new Map([
    ['/api/public/app/config', fixture],
    [
      '/api/public/app/channels/public/live',
      {
        state: 'on_air',
        channel_id: 'public',
        title: 'Public live programming',
        playback_url: '/api/public/channels/public/live.m3u8',
        source_ref: 'live-source-public',
        caption_tracks: [{ label: 'Live captions', language: 'en' }],
        audio_tracks: [{ label: 'Program audio', language: 'en' }],
      },
    ],
    [
      '/api/public/app/channels/public/schedule',
      [{ title: 'Public live programming', kind: 'live' }],
    ],
    [
      '/api/public/app/channels/public/catalog',
      {
        items: [
          {
            title: 'Public sample meeting',
            publish_state: 'published',
            captions: [{ label: 'English captions', language: 'en' }],
            audio_tracks: [{ label: 'Program audio', language: 'en' }],
            chapters: [{ title: 'Call to order' }, { title: 'Public comment' }],
          },
        ],
        playlists: [{ playlist_id: 'public-recent' }],
      },
    ],
  ])
  globalThis.fetch = async (url) => ({
    ok: responses.has(url),
    status: responses.has(url) ? 200 : 404,
    statusText: responses.has(url) ? 'OK' : 'Not Found',
    async json() {
      return responses.get(url)
    },
  })

  const experience = await loadChannelExperience()

  assert.equal(experience.channel.channel_id, 'public')
  assert.equal(experience.live.playback_url, '/api/public/channels/public/live.m3u8')
  assert.equal(experience.schedule[0].kind, 'live')
  assert.equal(experience.catalog.items[0].chapters.length, 2)
})

test('shared shell runtime preserves available feeds when one feed fails', async () => {
  const { loadChannelExperience, renderShell } = await import('../src/shell.mjs')
  const fixture = JSON.parse(
    await readFile(join(root, 'fixtures', 'station-app-config.sample.json'), 'utf8'),
  )
  const responses = new Map([
    ['/api/public/app/config', fixture],
    [
      '/api/public/app/channels/public/live',
      {
        state: 'on_air',
        channel_id: 'public',
        title: 'Public live programming',
        playback_url: '/api/public/channels/public/live.m3u8',
        source_ref: 'live-source-public',
        caption_tracks: [],
        audio_tracks: [],
      },
    ],
    [
      '/api/public/app/channels/public/catalog',
      {
        items: [{ title: 'Public sample meeting', publish_state: 'published' }],
        playlists: [],
      },
    ],
  ])
  globalThis.fetch = async (url) => ({
    ok: responses.has(url),
    status: responses.has(url) ? 200 : 503,
    statusText: responses.has(url) ? 'OK' : 'Unavailable',
    async json() {
      return responses.get(url)
    },
  })

  const experience = await loadChannelExperience()

  assert.equal(experience.live.title, 'Public live programming')
  assert.equal(experience.catalog.items[0].title, 'Public sample meeting')
  assert.match(experience.errors.schedule, /Feed unavailable/)

  const rootElement = {
    innerHTML: 'stale',
    dataset: {},
    children: [],
    style: { setProperty() {} },
    append(...children) {
      this.children.push(...children)
    },
  }
  globalThis.document = {
    createElement(tagName) {
      return {
        tagName,
        children: [],
        textContent: '',
        append(...children) {
          this.children.push(...children)
        },
      }
    },
  }

  renderShell(rootElement, experience, 'Roku')

  const renderedValues = rootElement.children.map((section) => section.children[1].textContent)
  assert.ok(renderedValues.includes('on_air: Public live programming'))
  assert.ok(renderedValues.some((value) => value.startsWith('Feed unavailable:')))
  assert.ok(renderedValues.includes('Public sample meeting (published); 0 playlists'))
  assert.equal(rootElement.dataset.ready, 'true')
})

test('shared shell runtime renders station channel and media fields', async () => {
  const { renderShell } = await import('../src/shell.mjs')
  const fixture = JSON.parse(
    await readFile(join(root, 'fixtures', 'station-app-config.sample.json'), 'utf8'),
  )
  const experience = {
    config: fixture,
    channel: fixture.channels[0],
    live: {
      state: 'on_air',
      title: 'Public live programming',
      playback_url: '/api/public/channels/public/live.m3u8',
      caption_tracks: [{ label: 'Live captions', language: 'en' }],
      audio_tracks: [{ label: 'Program audio', language: 'en' }],
    },
    schedule: [{ title: 'Public live programming', kind: 'live' }],
    catalog: {
      items: [
        {
          title: 'Public sample meeting',
          publish_state: 'published',
          captions: [{ label: 'English captions', language: 'en' }],
          audio_tracks: [{ label: 'Program audio', language: 'en' }],
          chapters: [{ title: 'Call to order' }, { title: 'Public comment' }],
        },
      ],
      playlists: [{ playlist_id: 'public-recent' }],
    },
  }
  const rootElement = {
    innerHTML: 'stale',
    dataset: {},
    children: [],
    style: {
      values: {},
      setProperty(name, value) {
        this.values[name] = value
      },
    },
    append(...children) {
      this.children.push(...children)
    },
  }
  globalThis.document = {
    createElement(tagName) {
      return {
        tagName,
        children: [],
        textContent: '',
        append(...children) {
          this.children.push(...children)
        },
      }
    },
  }

  renderShell(rootElement, experience, 'Roku')

  assert.equal(rootElement.dataset.ready, 'true')
  assert.equal(rootElement.innerHTML, '')
  assert.equal(rootElement.style.values['--civiccast-brand'], '#2458A6')
  assert.equal(rootElement.children.length, 11)
  assert.deepEqual(
    rootElement.children.map((section) => section.children[1].textContent),
    [
      'CivicCast station',
      'Roku',
      'Public Channel',
      'PUBLIC #2458A6',
      'on_air: Public live programming',
      'Live captions (en)',
      'Program audio (en)',
      'Public live programming - live',
      'Public sample meeting (published); 1 playlists',
      'Call to order | Public comment',
      'unbranded',
    ],
  )
})

test('build script creates deterministic artifacts for every app target', async () => {
  const { buildTargets } = await import('../scripts/build-targets.mjs')
  const outDir = await mkdtemp(join(tmpdir(), 'civiccast-shells-'))

  const report = await buildTargets({ outDir })

  assert.equal(report.source, 'shared-app-platform-shell-runtime')
  assert.deepEqual(
    report.targets.map((target) => target.appTarget).sort(),
    expectedTargets.map(([, appTarget]) => appTarget).sort(),
  )
  for (const target of report.targets) {
    assert.ok(target.files.includes(`targets/${target.appTarget.replaceAll('_', '-')}/manifest.json`))
    assert.ok(target.capabilities.includes('live-playback-metadata'))
  }
  assert.match(await readFile(join(outDir, 'src', 'shell.mjs'), 'utf8'), /loadChannelExperience/)
  assert.match(await readFile(join(outDir, 'build-report.json'), 'utf8'), /shared-app-platform/)
})

test('store readiness matrix covers every target and monitoring requirement', async () => {
  const readiness = JSON.parse(await readFile(join(root, 'store-readiness.json'), 'utf8'))
  const targetIds = readiness.targets.map((target) => target.appTarget).sort()

  assert.equal(readiness.version, '1.8.2')
  assert.deepEqual(targetIds, expectedTargets.map(([, appTarget]) => appTarget).sort())
  assert.ok(readiness.certifiedIntegratorGuidance.length >= 4)
  assert.deepEqual(readiness.monitoringChecklist, [
    'station-config-fetch',
    'live-state-fetch',
    'live-playback-url-present',
    'vod-catalog-fetch',
    'schedule-feed-fetch',
    'caption-track-present-when-advertised',
    'app-branding-applied',
  ])
  for (const target of readiness.targets) {
    assert.ok(target.proofClass)
    assert.ok(target.inputModel)
    assert.ok(target.packaging)
    assert.ok(target.externalRequirements.length >= 2)
  }
})

test('local smoke executes one living-room and one mobile shell target', async () => {
  const { smokeTargets } = await import('../scripts/smoke-targets.mjs')

  const report = await smokeTargets({ targets: ['roku', 'android-mobile'] })

  assert.equal(report.buildTargets, expectedTargets.length)
  assert.deepEqual(
    report.results.map((result) => result.proofClass),
    ['living-room-local', 'mobile-local'],
  )
  for (const result of report.results) {
    assert.equal(result.ready, true)
    assert.equal(result.renderedSections, 11)
    assert.ok(result.renderedValues.includes('Public sample meeting (published); 1 playlists'))
  }
})
