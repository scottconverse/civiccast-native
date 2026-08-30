import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync } from 'node:fs'

/**
 * Accessibility gate for the CivicCast operator console.
 *
 * Per CivicCast spec §4.1 (UX non-negotiables) and §16.4 (a11y posture)
 * the operator UI is held to WCAG 2.2 AA. The full WCAG hardening pass
 * happens at Sprint 0.9; this gate is the early floor that blocks any
 * merge from introducing a serious or critical violation against
 * WCAG 2.0/2.1/2.2 A or AA on the shell + asset library surface.
 *
 * The library currently fails to load assets in the preview environment
 * (no backend) and surfaces an error state. The error UI is the rendered
 * surface this gate scans.
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const evidenceDir = process.env.CIVICCAST_EVIDENCE_DIR ?? 'test-results/evidence'
mkdirSync(evidenceDir, { recursive: true })

async function expectNoWcagAxeViolations(page: import('@playwright/test').Page, label: string) {
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
    throw new Error(`axe-core found ${results.violations.length} WCAG violation(s) on ${label}:\n\n${summary}`)
  }
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'accessibility-tester',
        display_name: 'Accessibility Tester',
        roles: ['setup_admin', 'meeting_operator', 'records_clerk', 'publish_operator'],
      }),
    })
  })
  await page.route('**/api/setup/station-state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'not_started',
        setup_complete: false,
        profile: null,
        recovery_kit_created: false,
        recovery_kit_id: null,
        operator_console_url: 'http://127.0.0.1:5173',
        next_step: 'Create the first admin account and save the recovery kit.',
      }),
    })
  })
  await page.route('**/api/setup/storage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ready',
        database_url: 'sqlite:///C:/CivicCast/data/civiccast.sqlite3',
        database_path: 'C:/CivicCast/data/civiccast.sqlite3',
        upload_dir: 'C:/CivicCast/uploads',
        storage_dir: 'C:/CivicCast',
        migrations_applied: true,
        configured_at: '2026-05-22T18:00:00Z',
        operator_message: 'CivicCast local durable storage is ready.',
        next_step: 'Open the operator console and continue setup.',
      }),
    })
  })
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
})

test.describe('operator portal accessibility (desktop)', () => {
  test('default landing has zero WCAG axe violations', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('link', { name: 'Report a beta issue' })).toBeVisible()
    // Wait for the shell to render before scanning.
    await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()

    await expectNoWcagAxeViolations(page, 'operator desktop')
    await page.screenshot({ path: `${evidenceDir}/v0.10-operator-a11y-desktop.png`, fullPage: true })
  })

  test('landmarks are present and unique', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('header[role="banner"]')).toHaveCount(1)
    await expect(page.locator('main')).toHaveCount(1)
    await expect(page.locator('aside[aria-label="Primary navigation"]')).toHaveCount(1)
    // Single h1: the asset library heading.
    await expect(page.locator('h1')).toHaveCount(1)
  })

  test('skip link is the first focusable element and jumps to main content (W-3)', async ({ page }) => {
    // The default First-Setup form (station-state: not_started) autofocuses
    // its Station Name field once storage is ready (SetupScreen.tsx: a
    // pre-existing, deliberate "land the operator in the first empty field
    // of a fresh install" UX decision, unrelated to this fix) -- that
    // legitimately claims the very first Tab before this test's own
    // scope. Test against the "Admin sign-in" card instead (station
    // already set up, this browser's session missing), which has no
    // competing autofocus, mirroring auth-redirect.spec.ts's mocks.
    await page.route('**/api/staff/auth/me', async (route) => {
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Missing Authorization header. Use Bearer <staff-token>.' }) })
    })
    await page.route('**/api/setup/station-state**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          setup_complete: true,
          recovery_kit_acknowledged: true,
          profile: { station_name: 'CivicCast Lab', admin_display_name: 'Admin' },
        }),
      })
    })

    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Admin sign-in' })).toBeVisible()

    const skipLink = page.getByRole('link', { name: 'Skip to main content' })
    // Hidden until focused (Tailwind's sr-only / focus:not-sr-only pair, the
    // same visually-hidden convention already used elsewhere in the console,
    // e.g. AssetsScreen's `sr-only` table header cell).
    await expect(skipLink).toHaveCSS('position', 'absolute')

    // The very first Tab press on a fresh page must land on the skip link,
    // before the top bar, before the ~20-entry primary navigation.
    await page.keyboard.press('Tab')
    await expect(skipLink).toBeFocused()
    await expect(skipLink).toBeVisible()

    // Activating it moves focus straight to the main landmark.
    await page.keyboard.press('Enter')
    await expect(page.locator('main#main-content')).toBeFocused()
  })

  test('focus moves to the main landmark on route change (UX-MAJOR-2)', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()
    const main = page.locator('main#main-content')

    // Mirrors the public portal's route-change focus pattern
    // (apps/portal-public/src/App.tsx): moving focus keyboard users would
    // otherwise lose track of, from a sidebar click, to the newly routed
    // screen.
    await page.getByRole('button', { name: 'Assets' }).click()
    await expect(page.getByLabel('Search assets')).toBeVisible()
    await expect(main).toBeFocused()

    await page.getByRole('button', { name: 'Schedule', exact: true }).click()
    await expect(main).toBeFocused()
  })

  test('theme toggle has an accessible name', async ({ page }) => {
    await page.goto('/')
    // The label flips with the theme; either form is acceptable.
    const toggle = page.getByRole('button', {
      name: /Switch to (dark|light) theme/,
    })
    await expect(toggle).toBeVisible()
  })

  test('search input has a label', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Assets' }).click()
    await expect(page.getByLabel('Search assets')).toBeVisible()
  })

  test('current nav items do not expose stale disabled placeholders', async ({ page }) => {
    await page.goto('/')
    // The public-beta shell no longer renders future-sprint placeholder
    // routes. Guard against stale disabled rows reappearing in the primary
    // navigation after route cleanup.
    await expect(page.locator('aside[aria-label="Primary navigation"] button[aria-disabled="true"]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Schedule', exact: true })).toBeVisible()
  })
})

test.describe('operator portal accessibility (mobile)', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('mobile layout has zero WCAG axe violations', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()

    await expectNoWcagAxeViolations(page, 'operator mobile')
    await page.screenshot({ path: `${evidenceDir}/v0.10-operator-a11y-mobile.png`, fullPage: true })
  })

  test('hamburger button has an accessible name and opens the drawer', async ({
    page,
  }) => {
    await page.goto('/')
    const hamburger = page.getByRole('button', { name: 'Open navigation' })
    await expect(hamburger).toBeVisible()
    await hamburger.click()

    const drawer = page.getByRole('dialog', { name: 'Primary navigation' })
    await expect(drawer).toBeVisible()
    // Scrim must have an accessible name so screen-reader users know how to dismiss.
    await expect(page.getByRole('button', { name: 'Close navigation' })).toBeVisible()
  })

  test('drawer closes on Escape', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await expect(page.getByRole('dialog', { name: 'Primary navigation' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(
      page.getByRole('dialog', { name: 'Primary navigation' }),
    ).toBeHidden()
  })

  test('keyboard reaches and expands both collapsed navigation groups', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('button', { name: 'Live', exact: true }).click()

    await page.getByRole('button', { name: 'Open navigation' }).click()
    // Help (the in-product manual) is now the first nav section, collapsed
    // by default -- same focus-trap shape this test exercises, new label.
    const help = page.getByLabel('Show Help navigation')
    await expect(help).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByLabel('Hide Help navigation')).toBeFocused()

    await page.keyboard.press('Shift+Tab')
    await expect(page.getByRole('link', { name: 'Report a beta issue' })).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    const systemHealth = page.getByLabel('Show System Health navigation')
    await expect(systemHealth).toBeFocused()
    await page.keyboard.press('Space')
    await expect(page.getByLabel('Hide System Health navigation')).toBeFocused()
  })
})
