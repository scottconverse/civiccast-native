// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Routing/playback analytics instrumentation (audit sprint Stage G).
// Locks: the portal emits privacy-safe `schedule_browse` events on load and
// on in-page section navigation, the payload never carries viewer/session
// identifiers, and the emitter self-disables when ingest is not configured
// (403) so an unconfigured station sees exactly one rejected request.
//
// Real playback (`playback_*`) events are exercised manually: Playwright's
// bundled Chromium lacks licensed media codecs for HLS playback, so this
// spec covers the routing half plus the payload contract.

import { test, expect, type Page, type Route } from '@playwright/test'

const liveOffline = {
  state: 'offline',
  live_session_id: null,
  channel_id: null,
  title: null,
  started_at: null,
  manifest_url: null,
}

async function mockPortalData(page: Page) {
  await page.route('**/api/public/live/current', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveOffline) }),
  )
  await page.route('**/api/public/schedule/coming-up', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
  await page.route('**/api/public/assets', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
  await page.route('**/api/public/contribute/agreements/current', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        agreement_id: 'community-media-submission',
        version: '2026-05-31',
        title: 'Community media submission agreement',
        summary: 'Submitter confirms they have permission to share this media.',
        effective_at: '2026-05-31T00:00:00Z',
      }),
    }),
  )
  await page.route('**/api/public/cg/idle', (route: Route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: '{}' }),
  )
}

function collectAnalytics(page: Page, status = 202): Promise<unknown[]> {
  const events: unknown[] = []
  return page
    .route('**/api/public/app/analytics/events', (route: Route) => {
      events.push(route.request().postDataJSON())
      return route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({
          event_id: 'pub-mock',
          retained_fields: [],
          proof_boundary: 'privacy-safe-contract-no-direct-viewer-identifiers',
        }),
      })
    })
    .then(() => events)
}

test('portal load emits a privacy-safe schedule_browse event', async ({ page }) => {
  await mockPortalData(page)
  const events = await collectAnalytics(page)

  await page.goto('/')
  await expect
    .poll(() => events.length, { message: 'expected a schedule_browse event on load' })
    .toBeGreaterThanOrEqual(1)

  const event = events[0] as Record<string, unknown>
  expect(event.event_name).toBe('schedule_browse')
  expect(event.app_target).toBe('web_pwa')
  expect(String(event.event_id)).toMatch(/^pub-/)
  expect((event.properties as Record<string, unknown>).section).toBe('portal_home')
  // Privacy contract: no identifiers, ever.
  expect(event).not.toHaveProperty('anonymous_session_id')
  expect(event).not.toHaveProperty('hashed_viewer_id')
})

test('route navigation emits schedule_browse per view', async ({ page }) => {
  await mockPortalData(page)
  const events = await collectAnalytics(page)

  await page.goto('/')
  await expect.poll(() => events.length).toBeGreaterThanOrEqual(1)

  await page.evaluate(() => {
    window.location.hash = '#/recordings'
  })
  await expect
    .poll(
      () =>
        events.filter(
          (event) =>
            (event as { properties?: { section?: string } }).properties?.section ===
            'recordings_browse',
        ).length,
      { message: 'expected a schedule_browse event for the browse view' },
    )
    .toBeGreaterThanOrEqual(1)
})

test('emitter self-disables after ingest rejects the origin', async ({ page }) => {
  await mockPortalData(page)
  const events = await collectAnalytics(page, 403)

  await page.goto('/')
  await expect.poll(() => events.length).toBeGreaterThanOrEqual(1)
  const countAfterRejection = events.length

  await page.evaluate(() => {
    window.location.hash = '#/recordings'
  })
  // Give a would-be second event time to (incorrectly) fire.
  await page.waitForTimeout(500)
  expect(events.length).toBe(countAfterRejection)
})
