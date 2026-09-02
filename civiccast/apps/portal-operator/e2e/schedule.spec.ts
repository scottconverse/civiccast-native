import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Schedule screen accessibility + interaction gate.
 *
 * The preview environment has no backend, so the screen will surface its
 * load-error state. The gate scans both the screen chrome and the open
 * "New scheduled item" drawer for serious or critical axe violations
 * (WCAG 2.0/2.1/2.2 A + AA), and asserts the drawer's keyboard semantics
 * (role=dialog, escape closes, accessible name, single submit button).
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

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

const MOCK_SCHEDULE_ITEM = {
  id: 'ad8f4d91-5d43-4c1f-9ed2-b4e7e2fdd100',
  asset_id: 'council-meeting',
  asset_title: 'Council Meeting',
  channel_id: 'government',
  mode: 'premiere',
  state: 'scheduled',
  scheduled_at: new Date().toISOString(),
  duration_seconds: 3600,
  notes: null,
  created_at: '2026-05-12T12:00:00Z',
}

test.beforeEach(async ({ page }) => {
  // Identity. Without this the screen races an async 401 -> First Setup
  // redirect, and tests in this file fail intermittently on WHICH assertion
  // loses the race — header visibility, drawer visibility, escape handling.
  // They then look like product regressions belonging to whatever change is
  // in flight. Found 2026-08-14 by TESTER3, who was asked to prove that two
  // extra failures were not caused by a schedule-drawer fix: with identity
  // mocked and --workers=1, the same revision pair went 12/12 and 12/12.
  // A flaky suite does not just cost reruns; it launders real regressions.
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'e2e-schedule-operator',
        display_name: 'Schedule E2E',
        roles: ['setup_admin', 'meeting_operator'],
      }),
    })
  })
  // The drawer loads real station channels (F-RC3-6 fix) — every test in this
  // file needs the endpoint mocked or the channel select stays empty and
  // submit stays disabled.
  await page.route('**/api/staff/cable/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          channel_id: 'public',
          slug: 'public',
          kind: 'public',
          branding: {
            display_name: 'Public Channel',
            short_name: 'Public',
            color: '#2458A6',
            logo_text: 'PUBLIC',
          },
          fallback_behavior: 'slate',
        },
        {
          channel_id: 'government',
          slug: 'government',
          kind: 'government',
          branding: {
            display_name: 'Government Channel',
            short_name: 'Government',
            color: '#5A2CA0',
            logo_text: 'GOV',
          },
          fallback_behavior: 'slate',
        },
      ]),
    })
  })
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.route('**/api/staff/schedule?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.route('**/api/staff/schedule', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
})

async function navigateToSchedule(page: import('@playwright/test').Page) {
  await page.goto('/')
  // Layout renders the desktop sidebar at >= 768px (Playwright Desktop Chrome
  // is 1280x720). The mobile drawer is exercised by the existing a11y suite.
  await page
    .locator('aside[aria-label="Primary navigation"]')
    .getByRole('button', { name: 'Schedule', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Schedule' })).toBeVisible()
}

function newScheduleButton(page: import('@playwright/test').Page) {
  return page.getByRole('main').getByRole('button', {
    name: 'New scheduled item',
  }).first()
}

async function replaceScheduleRoutes(page: import('@playwright/test').Page) {
  await page.unroute('**/api/staff/schedule?*').catch(() => undefined)
  await page.unroute('**/api/staff/schedule').catch(() => undefined)
}

async function replaceAssetRoutes(page: import('@playwright/test').Page) {
  await page.unroute('**/api/staff/assets').catch(() => undefined)
}

test.describe('schedule screen', () => {
  test('renders header, view toggle, and week navigation', async ({ page }) => {
    await navigateToSchedule(page)
    await expect(page.getByRole('tab', { name: /^week$/i })).toBeVisible()
    await expect(page.getByRole('tab', { name: /^list$/i })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Previous week' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Next week' })).toBeVisible()
    await expect(newScheduleButton(page)).toBeVisible()
  })

  test('list view toggles aria-selected', async ({ page }) => {
    await navigateToSchedule(page)
    const list = page.getByRole('tab', { name: /^list$/i })
    await list.click()
    await expect(list).toHaveAttribute('aria-selected', 'true')
  })

  test('drawer opens with role=dialog, named heading, and disabled submit', async ({
    page,
  }) => {
    await navigateToSchedule(page)
    await newScheduleButton(page).click()

    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await expect(dialog).toBeVisible()

    // Mode picker — both modes are radios with accessible names.
    await expect(dialog.getByRole('radio', { name: /Premiere/ })).toBeVisible()
    await expect(dialog.getByRole('radio', { name: /Embargo/ })).toBeVisible()

    // No validated assets in the preview env → submit must be disabled.
    await expect(
      dialog.getByRole('button', { name: /^Schedule (premiere|embargo)/ }),
    ).toBeDisabled()
  })

  test('schedule mode cards support arrow-key selection', async ({ page }) => {
    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await expect(dialog).toBeVisible()

    await dialog.getByRole('radio', { name: /Premiere/ }).press('ArrowRight')
    await expect(dialog.getByRole('radio', { name: /Embargo/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  test('escape key closes the drawer', async ({ page }) => {
    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  test('UX-004 focus trap keeps Tab inside the drawer', async ({ page }) => {
    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await expect(dialog).toBeVisible()
    await expect(
      dialog.locator('aside').getByRole('button', { name: 'Close drawer' }),
    ).toBeFocused()

    await page.keyboard.press('Shift+Tab')
    await expect.poll(async () =>
      page.evaluate(() => {
        const active = document.activeElement
        const dialogEl = document.querySelector('[role="dialog"]')
        return Boolean(active && dialogEl?.contains(active))
      }),
    ).toBe(true)

    for (let i = 0; i < 12; i += 1) await page.keyboard.press('Tab')
    await expect.poll(async () =>
      page.evaluate(() => {
        const active = document.activeElement
        const dialogEl = document.querySelector('[role="dialog"]')
        return Boolean(active && dialogEl?.contains(active))
      }),
    ).toBe(true)
  })

  test('TEST-005 cancel flow requires and accepts confirmation via ConfirmDialog', async ({
    page,
  }) => {
    await replaceScheduleRoutes(page)
    await page.route('**/api/staff/schedule?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SCHEDULE_ITEM]),
      })
    })
    await page.route('**/api/staff/schedule', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SCHEDULE_ITEM]),
      })
    })
    await page.route(`**/api/staff/schedule/${MOCK_SCHEDULE_ITEM.id}/cancel`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_SCHEDULE_ITEM, state: 'cancelled' }),
      })
    })

    await navigateToSchedule(page)
    await page.getByRole('tab', { name: /^list$/i }).click()

    await page.getByRole('button', { name: 'Cancel' }).click()
    const dialog = page.getByRole('alertdialog', {
      name: 'Cancel scheduled item for "Council Meeting"?',
    })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel scheduled item' }).click()
    await expect(dialog).toBeHidden()

    await expect(page.getByText('Cancelled.')).toBeVisible()
  })

  test('TEST-007 recovery flow retries a 503 schedule load', async ({ page }) => {
    await replaceScheduleRoutes(page)
    let calls = 0
    await page.route('**/api/staff/schedule?*', async (route) => {
      calls += 1
      if (calls === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.',
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SCHEDULE_ITEM]),
      })
    })
    await page.route('**/api/staff/schedule', async (route) => {
      calls += 1
      if (calls === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.',
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SCHEDULE_ITEM]),
      })
    })

    await navigateToSchedule(page)
    await expect(page.getByRole('alert')).toContainText(
      'Durable storage is not ready.',
    )
    await page.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByText('Council Meeting')).toBeVisible()
  })

  test('TEST-007 recovery flow handles 409 conflict then succeeds after operator fix', async ({
    page,
  }) => {
    await replaceAssetRoutes(page)
    await replaceScheduleRoutes(page)
    await page.route('**/api/staff/assets', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_ASSET]),
      })
    })
    await page.route('**/api/staff/schedule?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })
    let createCalls = 0
    await page.route('**/api/staff/schedule', async (route) => {
      if (route.request().method() === 'POST') {
        createCalls += 1
        if (createCalls === 1) {
          await route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: {
                message: "Schedule conflict on channel 'government'.",
                conflicting_item: MOCK_SCHEDULE_ITEM,
              },
            }),
          })
          return
        }
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            ...MOCK_SCHEDULE_ITEM,
            id: 'bd8f4d91-5d43-4c1f-9ed2-b4e7e2fdd101',
            channel_id: 'education',
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await dialog.getByRole('button', { name: 'Schedule premiere' }).click()

    await expect(dialog.getByRole('alert')).toContainText('Time slot conflicts.')
    await expect(dialog.getByRole('alert')).toContainText(
      'Pick a different time, channel, or cancel the conflicting item.',
    )

    await dialog.getByLabel('Channel').selectOption('government')
    await dialog.getByRole('button', { name: 'Schedule premiere' }).click()

    await expect(page.getByText('Scheduled.')).toBeVisible()
  })

  test('TEST-007 recovery flow surfaces 422 field errors with retry path', async ({
    page,
  }) => {
    await replaceAssetRoutes(page)
    await replaceScheduleRoutes(page)
    await page.route('**/api/staff/assets', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_ASSET]),
      })
    })
    await page.route('**/api/staff/schedule?*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })
    await page.route('**/api/staff/schedule', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'duration_seconds must be a positive whole number.',
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })

    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    const dialog = page.getByRole('dialog', { name: 'New scheduled item' })
    await dialog.getByRole('button', { name: 'Schedule premiere' }).click()

    await expect(dialog.getByRole('alert')).toContainText('Could not schedule.')
    await expect(dialog.getByRole('alert')).toContainText(
      'duration_seconds must be a positive whole number.',
    )
  })

  test('axe scan: schedule screen has no serious/critical violations', async ({
    page,
  }) => {
    await navigateToSchedule(page)
    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
    const blockers = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    )
    if (blockers.length > 0) {
      const summary = blockers
        .map(
          (v) =>
            `[${v.impact}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n    nodes: ${v.nodes
              .map((n) => n.target.join(' '))
              .join('; ')}`,
        )
        .join('\n\n')
      throw new Error(
        `axe-core found ${blockers.length} serious/critical violation(s) on the schedule screen:\n\n${summary}`,
      )
    }
  })

  test('axe scan: open drawer has no serious/critical violations', async ({
    page,
  }) => {
    await navigateToSchedule(page)
    await newScheduleButton(page).click()
    await expect(
      page.getByRole('dialog', { name: 'New scheduled item' }),
    ).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
    const blockers = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    )
    if (blockers.length > 0) {
      const summary = blockers
        .map(
          (v) =>
            `[${v.impact}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n    nodes: ${v.nodes
              .map((n) => n.target.join(' '))
              .join('; ')}`,
        )
        .join('\n\n')
      throw new Error(
        `axe-core found ${blockers.length} serious/critical violation(s) in the new-item drawer:\n\n${summary}`,
      )
    }
  })
})
