import { expect, test } from '@playwright/test'

/**
 * Cable automation CA-5: program guide editor, channel automation config,
 * and community bulletin moderation — mock-routed interaction gates.
 */

const now = '2026-06-11T20:00:00Z'

const MOCK_ASSET = {
  asset_id: 'council-meeting',
  title: 'Council Meeting',
  description: 'Regular council session',
  state: 'validated',
  manifest_url: null,
  published_at: null,
  file_path: '/srv/civiccast/council-meeting.mp4',
  file_size_bytes: 5_000_000,
  duration_seconds: 3600,
  codec_video: 'h264',
  codec_audio: 'aac',
  width_px: 1920,
  height_px: 1080,
  bitrate_bps: 5_000_000,
  format_name: 'mov,mp4,m4a,3gp,3g2,mj2',
  trim_in_seconds: null,
  trim_out_seconds: null,
  chapters: [],
  retention_policy: 'meeting',
  retention_until: null,
  retention_term_unit: null,
  retention_term_value: null,
  retention_anchor_at: null,
  version: 1,
  source_live_session_id: null,
  meeting_body: null,
  content_hash: null,
  thumbnail_path: null,
  file_status: 'ok',
  file_status_checked_at: null,
}

const MOCK_SLOT = {
  slot_id: 'cps_weeklycouncil',
  channel_id: 'public',
  asset_id: 'council-meeting',
  title_override: 'City Council (Replay)',
  recurrence: 'weekly',
  first_start_at: '2026-06-12T19:00:00Z',
  duration_seconds: 3600,
  repeat_until: null,
  enabled: true,
  created_at: now,
  updated_at: now,
}

const MOCK_LOG = [
  {
    occurrence_id: 'occ-1',
    slot_id: 'cps_weeklycouncil',
    channel_id: 'public',
    asset_id: 'council-meeting',
    title_override: 'City Council (Replay)',
    occurrence_start: '2026-06-12T19:00:00Z',
    duration_seconds: 3600,
    schedule_item_id: 'sched-1',
    status: 'scheduled',
    detail: '',
  },
  {
    occurrence_id: 'occ-2',
    slot_id: 'cps_weeklycouncil',
    channel_id: 'public',
    asset_id: 'council-meeting',
    title_override: 'City Council (Replay)',
    occurrence_start: '2026-06-13T19:00:00Z',
    duration_seconds: 3600,
    schedule_item_id: null,
    status: 'skipped_conflict',
    detail: 'Conflicts with an existing premiere on this channel.',
  },
]

const CABLE_PROFILE = {
  channel_id: 'public',
  slug: 'public',
  kind: 'public',
  branding: {
    display_name: 'Public Channel',
    short_name: 'Public',
    color: '#2458A6',
    logo_text: 'PUBLIC',
  },
  programming_rules: [],
  fallback_behavior: 'Use the channel slate when playback is unavailable.',
  default_slate_asset_id: null,
  outputs: [],
}

async function mockGuide(page: import('@playwright/test').Page) {
  const requests = {
    slotCreates: [] as Array<Record<string, unknown>>,
    materializeCalls: 0,
    disableCalls: 0,
  }
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_ASSET]),
    })
  })
  await page.route('**/api/staff/cable/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([CABLE_PROFILE]),
    })
  })
  await page.route('**/api/staff/programlog/slots?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_SLOT]),
    })
  })
  await page.route('**/api/staff/programlog/slots', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>
      requests.slotCreates.push(payload)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_SLOT, slot_id: 'cps_created' }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_SLOT]),
    })
  })
  await page.route('**/api/staff/programlog/slots/*/disable', async (route) => {
    requests.disableCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          occurrence_id: 'occ-1',
          slot_id: 'cps_weeklycouncil',
          occurrence_start: '2026-06-12T19:00:00Z',
          schedule_item_id: 'sched-1',
          status: 'cancelled',
          detail: 'slot disabled',
          created_at: now,
        },
      ]),
    })
  })
  await page.route('**/api/staff/programlog/materialize', async (route) => {
    requests.materializeCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ scheduled: 3, skipped_conflict: 1, skipped_asset: 0 }),
    })
  })
  await page.route('**/api/staff/programlog/channels/*/log?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_LOG),
    })
  })
  return requests
}

async function navigateToGuide(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page
    .locator('aside[aria-label="Primary navigation"]')
    .getByRole('button', { name: 'Program Guide', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Program guide' })).toBeVisible()
}

test.describe('program guide screen', () => {
  test('renders slots and the 7-day log including skip warnings', async ({ page }) => {
    await mockGuide(page)
    await navigateToGuide(page)

    // Recurring slot row with its recurrence chip and disable affordance.
    await expect(page.getByText('City Council (Replay)').first()).toBeVisible()
    await expect(page.getByText('Weekly').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Disable' })).toBeVisible()

    // Log: the scheduled airing and the honestly-recorded skip with reason.
    await expect(page.getByText('Scheduled').first()).toBeVisible()
    await expect(page.getByText('Skipped · conflict')).toBeVisible()
    await expect(
      page.getByText('Conflicts with an existing premiere on this channel.'),
    ).toBeVisible()
  })

  test('refresh guide triggers materialization and reports counts', async ({ page }) => {
    const requests = await mockGuide(page)
    await navigateToGuide(page)

    await page.getByRole('button', { name: 'Refresh guide' }).click()
    await expect.poll(() => requests.materializeCalls).toBe(1)
    await expect(page.getByText('Guide refreshed.')).toBeVisible()
    await expect(page.getByText('3 scheduled · 1 conflicts · 0 not playable')).toBeVisible()
  })

  test('add-to-guide drawer creates a recurring slot', async ({ page }) => {
    const requests = await mockGuide(page)
    await navigateToGuide(page)

    await page.getByRole('button', { name: 'Add to guide' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add to guide' })
    await expect(dialog).toBeVisible()

    // Recurrence radio cards.
    await expect(dialog.getByRole('radio', { name: /Once/ })).toBeVisible()
    await dialog.getByRole('radio', { name: /Weekdays/ }).click()

    await dialog.getByPlaceholder(/Shown to residents/).fill('Morning Bulletin')
    await dialog.getByRole('button', { name: 'Add to guide' }).click()

    await expect.poll(() => requests.slotCreates.length).toBe(1)
    expect(requests.slotCreates[0]).toMatchObject({
      channel_id: 'public',
      asset_id: 'council-meeting',
      recurrence: 'weekdays',
      title_override: 'Morning Bulletin',
      duration_seconds: null,
    })
    await expect(page.getByText('Added to guide.')).toBeVisible()
  })

  test('escape closes the drawer', async ({ page }) => {
    await mockGuide(page)
    await navigateToGuide(page)
    await page.getByRole('button', { name: 'Add to guide' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add to guide' })
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  test('disable asks for confirmation and reports cancelled airings', async ({ page }) => {
    const requests = await mockGuide(page)
    await navigateToGuide(page)

    await page.getByRole('button', { name: 'Disable' }).click()
    const dialog = page.getByRole('alertdialog', { name: 'Disable "City Council (Replay)"?' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(
      'All future airings from this recurring slot are cancelled from the guide immediately.',
    )
    await dialog.getByRole('button', { name: 'Disable slot' }).click()
    await expect(dialog).toBeHidden()

    await expect.poll(() => requests.disableCalls).toBe(1)
    await expect(page.getByText('Slot disabled.')).toBeVisible()
  })

  test('503 storage error surfaces the setup next-step', async ({ page }) => {
    await mockGuide(page)
    await page.unroute('**/api/staff/programlog/slots?*')
    await page.route('**/api/staff/programlog/slots?*', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.',
        }),
      })
    })
    await navigateToGuide(page)
    await expect(page.getByRole('alert')).toContainText('Durable storage is not ready.')
    await expect(page.getByRole('link', { name: 'Go to Setup' })).toBeVisible()
  })
})
