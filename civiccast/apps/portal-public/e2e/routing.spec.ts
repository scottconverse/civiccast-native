// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Issue #107 proof: hash routing, browse/search/pagination, detail pages,
// canonical shareable URLs, and the preserved legacy `?manifest=` override.

import { test, expect } from '@playwright/test'

const liveOffline = {
  state: 'offline',
  live_session_id: null,
  channel_id: null,
  title: null,
  started_at: null,
  manifest_url: null,
}

function recording(index: number, year: number) {
  const id = `meeting-${String(index).padStart(3, '0')}`
  return {
    asset_id: id,
    title: `Council Meeting ${index}`,
    description: index % 2 === 0 ? 'Budget session.' : 'Planning session.',
    // #107 option b: every 5th recording is untagged; the rest alternate
    // between two meeting bodies so the facet has real data to derive.
    meeting_body:
      index % 5 === 0 ? null : index % 2 === 0 ? 'City Council' : 'School Board',
    manifest_url: `https://cdn.example/${id}/playlist.m3u8`,
    poster_url: null,
    duration_seconds: 3600,
    published_at: `${year}-05-${String((index % 27) + 1).padStart(2, '0')}T20:00:00Z`,
  }
}

// 30 recordings: 15 in 2026, 15 in 2025 -> 3 pages at 12/page unfiltered.
const recordings = [
  ...Array.from({ length: 15 }, (_, i) => recording(i + 1, 2026)),
  ...Array.from({ length: 15 }, (_, i) => recording(i + 16, 2025)),
]

async function mockPortal(page: import('@playwright/test').Page) {
  await page.route('**/api/public/live/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(liveOffline),
    })
  })
  await page.route('**/api/public/schedule/coming-up', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/public/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(recordings),
    })
  })
  await page.route('**/api/public/search**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(recordings),
    })
  })
  await page.route('**/api/public/assets/*', async (route) => {
    const url = new URL(route.request().url())
    const assetId = decodeURIComponent(url.pathname.split('/').pop() ?? '')
    const found = recordings.find((asset) => asset.asset_id === assetId)
    if (found) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(found),
      })
      return
    }
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: `Asset not found: ${assetId}` }),
    })
  })
}

test('home shows the newest recordings and navigates to browse', async ({ page }) => {
  await mockPortal(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Latest recordings' })).toBeVisible()
  // Home is capped to the 6 newest, with a browse link for the rest.
  await expect(page.getByRole('article')).toHaveCount(6)
  await page.getByRole('link', { name: 'Browse all recordings' }).click()

  await expect(page).toHaveURL(/#\/recordings$/)
  await expect(page.getByRole('heading', { name: 'Browse recordings' })).toBeVisible()
})

test('browse paginates with shareable page URLs', async ({ page }) => {
  await mockPortal(page)
  await page.goto('/#/recordings')

  await expect(page.getByText('30 recordings published / page 1 of 3')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(12)

  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page).toHaveURL(/#\/recordings\?page=2$/)
  await expect(page.getByText('page 2 of 3')).toBeVisible()

  // Deep link directly to page 3 — URL state restores.
  await page.goto('/#/recordings?page=3')
  await expect(page.getByText('page 3 of 3')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(6)
})

test('search and year facet filter the archive', async ({ page }) => {
  await mockPortal(page)
  await page.goto('/#/recordings')

  await page.getByLabel('Search recordings').fill('budget')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page).toHaveURL(/#\/recordings\?q=budget$/)
  await expect(page.getByText(/15 recordings match this filter/)).toBeVisible()

  await page.getByLabel('Year').selectOption('2025')
  await expect(page).toHaveURL(/#\/recordings\?q=budget&year=2025$/)
  await expect(page.getByText(/recordings? match this filter/)).toBeVisible()

  // Zero-result empty state.
  await page.getByLabel('Search recordings').fill('no-such-meeting-zz')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(
    page.getByText('No recordings match this filter. Clear the search or facets to browse everything.'),
  ).toBeVisible()
})

test('meeting-body facet filters the archive with shareable URLs (#107 option b)', async ({
  page,
}) => {
  await mockPortal(page)
  await page.goto('/#/recordings')

  // Facet options derive from the data actually in use (plus All bodies).
  const facet = page.getByLabel('Meeting body')
  await expect(facet.locator('option')).toHaveText([
    'All bodies',
    'City Council',
    'School Board',
  ])

  // 30 recordings: 6 untagged (5,10,15,20,25,30), 12 City Council (even,
  // not %5), 12 School Board (odd, not %5).
  await facet.selectOption('School Board')
  await expect(page).toHaveURL(/#\/recordings\?body=School\+Board$/)
  await expect(page.getByText(/12 recordings match this filter/)).toBeVisible()

  // Deep link restores the facet from the URL.
  await page.goto('/#/recordings?body=City+Council')
  await expect(page.getByText(/12 recordings match this filter/)).toBeVisible()
  await expect(page.getByLabel('Meeting body')).toHaveValue('City Council')

  // Facets compose: body + search. Audit TEST-006: the old assertion used
  // "budget" whose 12 matches equal the body-only count (fixtures tie
  // description and body to the same parity), so a search-ignoring
  // mutation shipped green. "planning" matches ZERO City Council mocks -
  // the empty state proves the search term is genuinely applied.
  await page.getByLabel('Search recordings').fill('planning')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page).toHaveURL(/#\/recordings\?q=planning&body=City\+Council$/)
  await expect(
    page.getByText('No recordings match this filter. Clear the search or facets to browse everything.'),
  ).toBeVisible()

  // Audit TEST-006: facet x pagination deep link - an out-of-range page
  // clamps while the facet stays applied.
  await page.goto('/#/recordings?body=City+Council&page=9')
  await expect(page.getByLabel('Meeting body')).toHaveValue('City Council')
  await expect(page.getByText(/12 recordings match this filter \/ page 1 of 1/)).toBeVisible()
})

test('recording cards open a canonical watch URL', async ({ page }) => {
  await mockPortal(page)
  await page.goto('/#/recordings')

  await page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Council Meeting 1', exact: true }) })
    .first()
    .getByRole('link', { name: 'Watch recording' })
    .click()

  await expect(page).toHaveURL(/#\/watch\/meeting-001$/)
  await expect(page.getByRole('heading', { name: 'Council Meeting 1', exact: true })).toBeVisible()
  await expect(page.getByText('Planning session.').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copy share link' })).toBeVisible()
})

test('watch deep link works directly and unknown ids show not-found', async ({ page }) => {
  await mockPortal(page)

  await page.goto('/#/watch/meeting-007')
  await expect(page.getByRole('heading', { name: 'Council Meeting 7', exact: true })).toBeVisible()

  await page.goto('/#/watch/never-published')
  await expect(page.getByRole('heading', { name: 'Recording not found' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Back to all recordings' })).toBeVisible()
})

// Cable automation CA-5: resident channel guide at #/schedule.
const guideEntries = [
  {
    channel_id: 'public',
    title: 'City Council (Replay)',
    starts_at: '2026-06-12T19:00:00Z',
    duration_seconds: 3600,
  },
  {
    channel_id: 'public',
    title: 'Planning Commission',
    starts_at: '2026-06-13T01:00:00Z',
    duration_seconds: 5400,
  },
]

async function mockGuide(
  page: import('@playwright/test').Page,
  options: { entries?: typeof guideEntries } = {},
) {
  await page.route('**/api/public/app/config', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        channels: [
          { channel_id: 'public', branding: { display_name: 'Public Channel' } },
          { channel_id: 'gov-ch12', branding: { display_name: 'Government 12' } },
        ],
      }),
    })
  })
  await page.route('**/api/public/programlog/channels/*/guide**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(options.entries ?? guideEntries),
    })
  })
}

test('schedule view lists airings with channel tabs', async ({ page }) => {
  await mockPortal(page)
  await mockGuide(page)
  await page.goto('/')

  await page.getByRole('link', { name: 'Schedule', exact: true }).click()
  await expect(page).toHaveURL(/#\/schedule$/)
  await expect(page.getByRole('heading', { name: 'Channel schedule' })).toBeVisible()

  // Sanitized airable entries only: title, time, duration.
  await expect(page.getByText('City Council (Replay)')).toBeVisible()
  await expect(page.getByText('Planning Commission')).toBeVisible()
  await expect(page.getByText('60 min')).toBeVisible()

  // Channel tabs come from the public app config; switching is a shareable URL.
  const tabs = page.getByRole('navigation', { name: 'Channels' })
  await expect(tabs.getByRole('link', { name: 'Public Channel' })).toBeVisible()
  await tabs.getByRole('link', { name: 'Government 12' }).click()
  await expect(page).toHaveURL(/#\/schedule\?channel=gov-ch12$/)
})

test('schedule deep link and empty state work', async ({ page }) => {
  await mockPortal(page)
  await mockGuide(page, { entries: [] })

  await page.goto('/#/schedule?channel=gov-ch12')
  await expect(page.getByRole('heading', { name: 'Channel schedule' })).toBeVisible()
  await expect(
    page.getByText('Nothing is on the schedule for this channel yet. Check back soon.'),
  ).toBeVisible()
})

test('schedule guide failure shows a resident-friendly error', async ({ page }) => {
  await mockPortal(page)
  await page.route('**/api/public/app/config', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"channels": []}' })
  })
  await page.route('**/api/public/programlog/channels/*/guide**', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'The program guide is temporarily unavailable.' }),
    })
  })

  await page.goto('/#/schedule')
  await expect(page.getByRole('alert')).toContainText('The schedule could not be loaded.')
})

test('manifest override keeps portal navigation and uses truthful direct-preview copy', async ({ page }) => {
  await mockPortal(page)
  await page.goto('/?manifest=https%3A%2F%2Fcdn.example%2Foverride%2Fplaylist.m3u8')

  await expect(page.getByRole('heading', { name: 'Direct video preview' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Portal sections' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Home' })).toBeVisible()
  await expect(page.getByText('This link may show a live feed or a recording.')).toBeVisible()
  await expect(page.getByText('No live broadcast is on air.')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Latest recordings' })).toHaveCount(0)
})
