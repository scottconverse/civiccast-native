import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, readFileSync } from 'node:fs'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const evidenceDir = process.env.CIVICCAST_EVIDENCE_DIR ?? 'test-results/evidence'
mkdirSync(evidenceDir, { recursive: true })

const liveOnAir = {
  state: 'on_air',
  live_session_id: 'council-2026-05-15',
  channel_id: 'gov-ch12',
  title: 'City Council Meeting',
  started_at: '2026-05-15T18:00:00Z',
  manifest_url: 'https://cdn.example/live/playlist.m3u8',
}

const liveOffline = {
  state: 'offline',
  live_session_id: null,
  channel_id: null,
  title: null,
  started_at: null,
  manifest_url: null,
}

const comingUp = [
  {
    id: 'ad8f4d91-5d43-4c1f-9ed2-b4e7e2fdd100',
    asset_id: 'budget-hearing',
    asset_title: 'Budget Hearing',
    channel_id: 'gov-ch12',
    mode: 'premiere',
    state: 'scheduled',
    scheduled_at: '2026-05-16T19:00:00Z',
    duration_seconds: 5400,
  },
]

const recordings = [
  {
    asset_id: 'planning-board',
    title: 'Planning Board',
    description: 'May planning board meeting.',
    manifest_url: 'https://cdn.example/planning/playlist.m3u8',
    poster_url: null,
    duration_seconds: 3600,
    published_at: '2026-05-12T20:00:00Z',
  },
]

async function mockPortal(
  page: import('@playwright/test').Page,
  options: {
    live?: unknown
    schedule?: unknown
    assets?: unknown
    failSchedule?: boolean
    delayAssets?: boolean
  } = {},
) {
  await page.route('**/api/public/live/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(options.live ?? liveOnAir),
    })
  })
  await page.route('**/api/public/schedule/coming-up', async (route) => {
    if (options.failSchedule) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(options.schedule ?? comingUp),
    })
  })
  await page.route('**/api/public/assets', async (route) => {
    if (options.delayAssets) await new Promise((resolve) => setTimeout(resolve, 1000))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(options.assets ?? recordings),
    })
  })
  await page.route('**/api/public/contribute/agreements/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        agreement_id: 'community-media-submission',
        version: '2026-05-31',
        title: 'Community media submission agreement',
        summary: 'Submitter confirms they have permission to share this media.',
        effective_at: '2026-05-31T00:00:00Z',
      }),
    })
  })
  await page.route('**/api/public/subscribe/email', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        subscription_id: 'sub-test',
        channel: 'email',
        target_type: 'channel',
        target_id: 'gov-ch12',
        status: 'pending_confirmation',
        message: 'Subscription is waiting for confirmation.',
        next_step: 'Open the confirmation link sent to this address.',
        confirmation_token: 'confirm-token',
        unsubscribe_token: 'unsubscribe-token',
      }),
    })
  })
  await page.route('**/api/public/subscribe/confirm?**', async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('token') === 'bad-token') {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Confirmation link is invalid. Request a new signup link.',
        }),
      })
      return
    }
    if (url.searchParams.get('token') === 'already-token') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          subscription_id: 'sub-test',
          status: 'confirmed',
          message: 'This subscription was already confirmed.',
          next_step: 'No action is needed. Future matching recordings will send a notice.',
        }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        subscription_id: 'sub-test',
        status: 'confirmed',
        message: 'Subscription confirmed.',
        next_step: 'You will receive a notice when a matching recording publishes.',
      }),
    })
  })
  await page.route('**/api/public/subscribe/unsubscribe?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        subscription_id: 'sub-test',
        status: 'unsubscribed',
        message: 'Subscription unsubscribed.',
        next_step: 'You will not receive future notices for this subscription.',
      }),
    })
  })
  await page.route('**/api/public/cg/idle', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        channel_id: 'gov-ch12',
        title: 'CivicCast is ready',
        message: 'No meeting is live right now. The next scheduled broadcast will start here.',
        next_broadcast_label: 'Next broadcast: Public Meetings test broadcast',
        action_label: 'View published recordings',
        action_url: '/',
      }),
    })
  })
  await page.route('**/api/public/cg/emergency-overlay', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        overlay_id: 'test-emergency-overlay',
        severity: 'warning',
        title: 'Emergency notice',
        message: 'An emergency notice is active for this broadcast area.',
        instructions: 'Follow local emergency guidance and check official updates.',
        cellular_fallback_enabled: true,
        aria_live: 'assertive',
      }),
    })
  })
  // The Stage G analytics emitter fires on every view load; vite preview has
  // no backend, so an unmocked ingest 404s and pollutes the zero-console-error
  // assertion (this made the success-state test fail on main before #107).
  await page.route('**/api/public/app/analytics/events', async (route) => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        event_id: 'pub-mock',
        retained_fields: [],
        proof_boundary: 'privacy-safe-contract-no-direct-viewer-identifiers',
      }),
    })
  })
}

async function mockCaptionedHls(page: import('@playwright/test').Page) {
  await page.route('**/captioned/playlist.m3u8', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.apple.mpegurl',
      body: [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="en",NAME="English",DEFAULT=YES,AUTOSELECT=YES,URI="/captioned/captions/en/playlist.m3u8"',
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="es",NAME="Spanish",DEFAULT=NO,AUTOSELECT=YES,URI="/captioned/captions/es/playlist.m3u8"',
        '#EXT-X-STREAM-INF:BANDWIDTH=414000,RESOLUTION=426x240,CODECS="avc1.42001e,mp4a.40.2",SUBTITLES="subtitles"',
        '/captioned/240p/playlist.m3u8',
        '',
      ].join('\n'),
    })
  })
  await page.route('**/captioned/240p/playlist.m3u8', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.apple.mpegurl',
      body: [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-TARGETDURATION:2',
        '#EXT-X-PLAYLIST-TYPE:VOD',
        '#EXTINF:2.000,',
        '/captioned/240p/seg000.ts',
        '#EXT-X-ENDLIST',
        '',
      ].join('\n'),
    })
  })
  await page.route('**/captioned/captions/en/playlist.m3u8', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.apple.mpegurl',
      body: [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-TARGETDURATION:2',
        '#EXT-X-MEDIA-SEQUENCE:0',
        '#EXT-X-PLAYLIST-TYPE:VOD',
        '#EXTINF:2.000,',
        '/captioned/captions/en/seg000.vtt',
        '#EXT-X-ENDLIST',
        '',
      ].join('\n'),
    })
  })
  await page.route('**/captioned/captions/en/seg000.vtt', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/vtt',
      body: 'WEBVTT\n\ncue-1\n00:00:00.000 --> 00:00:01.000\nMotion carries.\n',
    })
  })
  await page.route('**/captioned/captions/es/playlist.m3u8', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/vnd.apple.mpegurl',
      body: [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-TARGETDURATION:2',
        '#EXT-X-MEDIA-SEQUENCE:0',
        '#EXT-X-PLAYLIST-TYPE:VOD',
        '#EXTINF:2.000,',
        '/captioned/captions/es/seg000.vtt',
        '#EXT-X-ENDLIST',
        '',
      ].join('\n'),
    })
  })
  await page.route('**/captioned/captions/es/seg000.vtt', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/vtt',
      body: 'WEBVTT\n\ncue-1:es\n00:00:00.000 --> 00:00:01.000\nLa mocion se aprueba.\n',
    })
  })
  await page.route('**/captioned/240p/seg000.ts', async (route) => {
    const segment = Buffer.from(
      readFileSync('e2e/fixtures/seg000.ts.b64', 'utf8'),
      'base64',
    )
    await route.fulfill({ status: 200, contentType: 'video/mp2t', body: segment })
  })
}

async function expectNoWcagAxeViolations(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  if (results.violations.length > 0) {
    const summary = results.violations
      .map(
        (v) =>
          `[${v.impact}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n    nodes: ${v.nodes
            .map((n) => n.target.join(' '))
            .join('; ')}`,
      )
      .join('\n\n')
    throw new Error(
      `axe-core found ${results.violations.length} WCAG violation(s):\n\n${summary}`,
    )
  }
}

test.describe('public portal accessibility', () => {
  test('success state has zero WCAG axe violations', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    await mockPortal(page, { live: liveOffline })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Live now' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Coming up' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Latest recordings' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Follow new recordings' })).toBeVisible()

    await expectNoWcagAxeViolations(page)
    expect(consoleErrors).toEqual([])
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-success-desktop.png`, fullPage: true })
  })

  test('skip link is the first focusable element and jumps past the header nav (W-3)', async ({ page }) => {
    await mockPortal(page, { live: liveOffline })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    const skipLink = page.getByRole('link', { name: 'Skip to main content' })
    // Hidden until focused (Tailwind's sr-only / focus:not-sr-only pair).
    await expect(skipLink).toHaveCSS('position', 'absolute')

    // The very first Tab press on a fresh page must land on the skip link,
    // before the "Report a beta issue" link, the "Home"/"Recordings"/
    // "Schedule" nav, or anything else in the header.
    await page.keyboard.press('Tab')
    await expect(skipLink).toBeFocused()
    await expect(skipLink).toBeVisible()

    // Activating it moves focus to the main landmark, past the header/nav.
    await page.keyboard.press('Enter')
    const main = page.locator('main#main-content')
    await expect(main).toBeFocused()
  })

  test('focus moves to the new view on in-app navigation (UX-MAJOR-2)', async ({ page }) => {
    await mockPortal(page, { live: liveOffline })
    // RecordingsScreen and ChannelGuideScreen call endpoints mockPortal
    // doesn't cover (mockPortal mirrors the home screen's own API surface).
    await page.route('**/api/public/search', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(recordings) })
    })
    await page.route('**/api/public/app/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ channels: [{ channel_id: 'gov-ch12', branding: { display_name: 'Channel 12' } }] }),
      })
    })
    await page.route('**/api/public/programlog/channels/**/guide**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    })

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    await page.getByRole('navigation', { name: 'Portal sections' }).getByRole('link', { name: 'Recordings' }).click()
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeFocused()

    await page.getByRole('navigation', { name: 'Portal sections' }).getByRole('link', { name: 'Schedule' }).click()
    await expect(page.getByRole('heading', { name: 'Channel schedule' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Channel schedule' })).toBeFocused()
  })

  test('deep link does not steal initial focus from the skip link (regression)', async ({ page }) => {
    // A resident landing straight on a deep link (a shared #/recordings URL,
    // a bookmark, a search result) must still get the skip link as their
    // first Tab target -- the route-change focus effect must not fire on
    // the render that establishes the page, only on a later in-app
    // navigation. RecordingsScreen's heading carries the same
    // `tabindex="-1"` the focus effect targets, so this is the state where
    // the regression is observable (the home screen's headings don't).
    await mockPortal(page, { live: liveOffline })
    await page.route('**/api/public/search', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(recordings) })
    })

    await page.goto('/#/recordings')
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeVisible()
    // The initial-load focus effect must not have already claimed focus.
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).not.toBeFocused()

    const skipLink = page.getByRole('link', { name: 'Skip to main content' })
    await page.keyboard.press('Tab')
    await expect(skipLink).toBeFocused()
  })

  test('skip link preserves the active route when activated from a deep link (regression)', async ({ page }) => {
    // The skip link's href is "#main-content"; both portals parse
    // `window.location.hash` for routing, so a plain hash navigation would
    // overwrite the active route hash instead of only moving focus.
    await mockPortal(page, { live: liveOffline })
    await page.route('**/api/public/search', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(recordings) })
    })

    await page.goto('/#/recordings')
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeVisible()

    const skipLink = page.getByRole('link', { name: 'Skip to main content' })
    await skipLink.focus()
    await page.keyboard.press('Enter')

    const main = page.locator('main#main-content')
    await expect(main).toBeFocused()
    expect(await page.evaluate(() => window.location.hash)).toBe('#/recordings')
    await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeVisible()
  })

  test('empty state explains what residents should do next', async ({ page }) => {
    await mockPortal(page, {
      live: liveOffline,
      schedule: [],
      assets: [],
    })
    await page.goto('/')

    await expect(page.getByText('Nothing is posted yet.')).toBeVisible()
    await expect(page.getByText('No premieres are scheduled.')).toBeVisible()
    await expect(page.getByText('No published recordings are available.')).toBeVisible()
    await expect(page.getByText('CivicCast is ready')).toBeVisible()
    await expect(page.getByText('No meeting is live right now.')).toBeVisible()
  })

  test('idle page and emergency overlay are actionable and accessible', async ({ page }) => {
    await mockPortal(page, {
      live: liveOffline,
      schedule: [],
      assets: [],
    })
    await page.goto('/?emergency=1')

    await expect(page.getByRole('alert')).toContainText('Emergency notice')
    await expect(page.getByText('Cellular fallback is enabled')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Between-streams idle page' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'View published recordings' })).toBeVisible()
    await expectNoWcagAxeViolations(page)
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-idle-emergency-desktop.png`, fullPage: true })
  })

  test('partial state keeps available sections visible', async ({ page }) => {
    await mockPortal(page, { failSchedule: true })
    await page.goto('/')

    await expect(page.getByText('Some portal sections need attention')).toBeVisible()
    await expect(page.getByText('Coming up:')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Planning Board' })).toBeVisible()
  })

  test('loading state is announced before delayed data resolves', async ({ page }) => {
    await mockPortal(page, { delayAssets: true })
    await page.goto('/')

    await expect(
      page.getByText('Loading the live stream, schedule, and recordings.'),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Planning Board' })).toBeVisible()
  })

  test('player has an accessible name when manifest override is supplied', async ({ page }) => {
    await mockPortal(page, {
      live: liveOffline,
      schedule: [],
      assets: [],
    })
    await page.goto('/?manifest=https%3A%2F%2Fcdn.example%2Foverride%2Fplaylist.m3u8')
    await expect(page.getByRole('link', { name: 'Report a beta issue' })).toBeVisible()

    await expect(page.getByLabel('Meeting video player')).toBeVisible()
  })

  test('caption controls expose English and Spanish subtitle tracks and toggle by keyboard', async ({
    page,
    browserName,
  }) => {
    if (browserName === 'webkit') {
      // This override only takes effect on a WebKit build that genuinely
      // lacks MediaSource (real Safari/iOS; Playwright's Windows/macOS
      // WebKit builds) -- there, HlsPlayer falls back to native HLS and
      // this supplies the browser APIs Safari exposes for it. On
      // Playwright's LINUX WebKit build (what this project's CI runs:
      // ubuntu-latest), MediaSource IS present, so HlsPlayer takes the
      // same hls.js/MediaSource branch as Chromium and this override is
      // inert -- confirmed via HlsPlayer's own isSupported() branch, not
      // assumed. Kept for macOS/iOS coverage on machines that do exercise
      // the native branch; do not read this block as proof the native
      // branch runs in CI.
      await page.addInitScript(() => {
        const originalCanPlayType = HTMLMediaElement.prototype.canPlayType
        HTMLMediaElement.prototype.canPlayType = function canPlayType(type) {
          if (type === 'application/vnd.apple.mpegurl') return 'probably'
          return originalCanPlayType.call(this, type)
        }

        const nativeTracks = new EventTarget()
        // Real Safari fires a 'change' event on the TextTrackList when a
        // track's `.mode` is mutated (spec: queue a task to fire `change`
        // on the list) -- HlsPlayer's native-HLS branch relies on that
        // event to notice a track change that did not come from its own
        // click handler (e.g. the browser's own native captions menu).
        // Give each fake track a real mode accessor that dispatches the
        // same event, instead of a plain data property nothing observes,
        // so this fake models that contract rather than silently omitting
        // it.
        function makeFakeTrack(label: string, language: string, initialMode: string) {
          let mode = initialMode
          return {
            label,
            language,
            get mode() {
              return mode
            },
            set mode(next: string) {
              if (mode === next) return
              mode = next
              nativeTracks.dispatchEvent(new Event('change'))
            },
          }
        }
        Object.defineProperties(nativeTracks, {
          0: { value: makeFakeTrack('English', 'en', 'showing') },
          1: { value: makeFakeTrack('Spanish', 'es', 'disabled') },
          length: { value: 2 },
        })
        Object.defineProperty(HTMLMediaElement.prototype, 'textTracks', {
          configurable: true,
          get: () => nativeTracks,
        })
      })
    }

    await mockPortal(page, {
      live: liveOffline,
      schedule: [],
      assets: [],
    })
    await mockCaptionedHls(page)
    await page.goto('/?manifest=%2Fcaptioned%2Fplaylist.m3u8')

    await expect(page.getByRole('button', { name: 'English' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Spanish' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')

    // This used to retry the press-then-assert (commit 624863b) because
    // aria-pressed would sometimes never flip to 'true' on webkit --
    // including on the very first assertion above, before any press had
    // happened. Root-caused as a genuine hls.js bug, not a webkit timing
    // fluke of this test: hls.js's SubtitleTrackController polls the
    // video's native <track> elements (WebKit lacks TextTrackList#onchange,
    // so hls.js falls back to a 500ms poll instead of a real 'change'
    // listener) and, if it samples before the native <track> DOM element
    // for the just-selected subtitle actually exists -- which requires an
    // async network fetch of the subtitle sub-playlist, so it lags the
    // near-instant manifest-driven selection -- it force-resets
    // hls.subtitleTrack to -1 (video-dev/hls.js#1948, #4345 track this
    // class of bug). Fixed at the root in HlsPlayer.tsx: the component now
    // tracks what its own UI asked for independently of hls.js's internal
    // trackId and reasserts it whenever hls.js's SUBTITLE_TRACK_SWITCH
    // disagrees, so the selection converges durably instead of racing.
    // Proven with 700+ repeat-each runs on Linux/webkit (this project's CI
    // browser+OS combination) with no retry at all and zero failures;
    // retrying here would only mask a regression of that fix.
    const pressUntilPressed = async (name: string) => {
      await page.getByRole('button', { name }).press('Enter')
      await expect(page.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
    }

    await pressUntilPressed('Spanish')
    await pressUntilPressed('Off')
    await pressUntilPressed('English')

    await expectNoWcagAxeViolations(page)
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-spanish-captions-desktop.png`, fullPage: true })
  })

  test('resident can request email double opt-in and see actionable next step', async ({ page }) => {
    await mockPortal(page)
    await page.goto('/')

    await page.getByLabel('Email address').fill('resident@example.org')
    await page.getByRole('button', { name: 'Subscribe' }).press('Enter')

    await expect(page.getByText('Subscription is waiting for confirmation.')).toBeVisible()
    await expect(page.getByText('Open the confirmation link sent to this address.')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Test one-click unsubscribe' })).toBeVisible()
  })

  test('resident confirmation link reports confirmed state', async ({ page }) => {
    await mockPortal(page)
    await page.goto('/?subscription=confirm&token=confirm-token')

    await expect(page.getByText('Subscription confirmed.')).toBeVisible()
    await expect(page.getByText('You will receive a notice')).toBeVisible()
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-confirmed-desktop.png`, fullPage: true })
  })

  test('resident already-confirmed link stays actionable', async ({ page }) => {
    await mockPortal(page)
    await page.goto('/?subscription=confirm&token=already-token')

    await expect(page.getByText('This subscription was already confirmed.')).toBeVisible()
    await expect(page.getByText('No action is needed.')).toBeVisible()
  })

  test('resident invalid-token link explains how to recover', async ({ page }) => {
    await mockPortal(page)
    await page.goto('/?subscription=confirm&token=bad-token')

    await expect(page.getByText('Confirmation link is invalid. Request a new signup link.')).toBeVisible()
    await expect(page.getByText('Use the signup form to request a fresh confirmation link.')).toBeVisible()
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-invalid-token-desktop.png`, fullPage: true })
  })

  test('resident unsubscribe link reports stopped notices', async ({ page }) => {
    await mockPortal(page)
    await page.goto('/?subscription=unsubscribe&token=unsubscribe-token')

    await expect(page.getByText('Subscription unsubscribed.')).toBeVisible()
    await expect(page.getByText('You will not receive future notices')).toBeVisible()
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-unsubscribed-desktop.png`, fullPage: true })
  })

  test('subscription and podcast links remain reachable on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await mockPortal(page, {
      live: liveOffline,
      schedule: [],
      assets: [],
    })
    await page.goto('/')

    await expect(page.getByRole('link', { name: 'Channel RSS feed' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Podcast RSS feed' })).toBeVisible()
    await expectNoWcagAxeViolations(page)
    await page.screenshot({ path: `${evidenceDir}/v0.10-public-portal-feeds-mobile.png`, fullPage: true })
  })
})
