import { readFile, writeFile } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildTargets } from './build-targets.mjs'

const packageRoot = fileURLToPath(new URL('..', import.meta.url))
const defaultSmokeTargets = ['roku', 'android-mobile']

export async function smokeTargets({ targets = defaultSmokeTargets } = {}) {
  const buildReport = await buildTargets()
  const fixture = JSON.parse(
    await readFile(join(packageRoot, 'fixtures', 'station-app-config.sample.json'), 'utf8'),
  )
  const shell = await import('../src/shell.mjs')
  const results = []
  globalThis.fetch = mockedFetch

  for (const targetDir of targets) {
    const manifest = JSON.parse(
      await readFile(join(packageRoot, 'dist', 'targets', targetDir, 'manifest.json'), 'utf8'),
    )
    const root = createRoot()
    const experience = await shell.loadChannelExperience('/api/public/app/config')
    shell.renderShell(root, experience, manifest.target)
    const renderedValues = root.children.map((section) => section.children[1].textContent)
    results.push({
      target: manifest.target,
      appTarget: manifest.appTarget,
      proofClass: proofClassForTarget(manifest.appTarget),
      ready: root.dataset.ready === 'true',
      renderedSections: root.children.length,
      renderedValues,
    })
  }

  const report = {
    generatedAt: 'deterministic-smoke-report',
    buildTargets: buildReport.targets.length,
    results,
  }
  await writeFile(
    join(packageRoot, 'dist', 'smoke-report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
  )
  return report

  async function mockedFetch(url) {
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
    return {
      ok: responses.has(url),
      status: responses.has(url) ? 200 : 404,
      statusText: responses.has(url) ? 'OK' : 'Not Found',
      async json() {
        return responses.get(url)
      },
    }
  }
}

function createRoot() {
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
  return {
    innerHTML: '',
    dataset: {},
    children: [],
    style: { setProperty() {} },
    append(...children) {
      this.children.push(...children)
    },
  }
}

function proofClassForTarget(appTarget) {
  if (appTarget === 'roku') return 'living-room-local'
  if (appTarget === 'android_mobile') return 'mobile-local'
  return 'local'
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const report = await smokeTargets()
  const reportPath = join(packageRoot, 'dist', 'smoke-report.json')
  console.log(`Smoked ${report.results.length} targets; report ${relative(process.cwd(), reportPath)}`)
}
