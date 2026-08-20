import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * W-2: the operator console's first-run dead-end (a lost or expired
 * installer setup link) now has an in-product recovery path instead of
 * only a command-line instruction. Route-mocked, like `auth-redirect.spec.ts`
 * -- no real backend, no `@fullstack` tag -- so this runs under the default
 * `test:a11y` project. The full backend proof (real ACL'd challenge file on
 * disk) is covered by `tests/installer/test_handoff_recovery_api.py`.
 */

const MOCK_NONCE = 'e2e-recovered-setup-nonce'
const MOCK_CODE_FILE = 'C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt'

async function mockCommonRoutes(page: Page) {
  await page.route('**/api/version', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0-rc18' }) })
  })
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Missing Authorization header. Use Bearer <staff-token>.' }),
    })
  })
  // Resolved BEFORE the nonce-bearing storage route below, so `not.toBe`
  // header presence naturally distinguishes cold vs. post-recovery calls
  // the same way `civiccast.installer.router`'s own nonce header check does.
  await page.route('**/api/setup/storage**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'not_configured', upload_dir: null, database_path: null }),
    })
  })
}

test('cold operator console shows the in-product setup-recovery action, not only a command line', async ({
  page,
}) => {
  await mockCommonRoutes(page)
  await page.route('**/api/setup/station-state**', async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({
        detail:
          'First-admin setup was reached through a non-local host name. Set CIVICCAST_SETUP_NONCE and launch the installer handoff URL with that nonce before exposing setup through a reverse proxy.',
      }),
    })
  })

  await page.goto('/#/setup')

  await expect(page.getByRole('heading', { name: 'Restore the setup handoff on the station' })).toBeVisible()
  // The pre-existing command-line instruction stays -- this is an ADDITIONAL
  // recovery path, not a replacement.
  await expect(page.getByText('--civiccast-restore-setup-handoff')).toBeVisible()
  const recoveryButton = page.getByRole('button', { name: 'I lost my setup link' })
  await expect(recoveryButton).toBeVisible()
  await expect(recoveryButton).toBeEnabled()
})

test('a mocked valid recovery code resumes setup and the dead-end is gone', async ({ page }) => {
  await mockCommonRoutes(page)
  await page.route('**/api/setup/station-state**', async (route) => {
    const nonceHeader = await route.request().headerValue('x-civiccast-setup-nonce')
    const hasRecoveredNonce = nonceHeader === MOCK_NONCE
    if (hasRecoveredNonce) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'not_started',
          setup_complete: false,
          recovery_kit_created: false,
          recovery_kit_acknowledged: false,
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: 'Prepare storage, then create the first admin.',
        }),
      })
      return
    }
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({
        detail:
          'First-admin setup was reached through a non-local host name. Set CIVICCAST_SETUP_NONCE and launch the installer handoff URL with that nonce before exposing setup through a reverse proxy.',
      }),
    })
  })
  let startCalls = 0
  await page.route('**/api/setup/handoff-recovery/start', async (route) => {
    startCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code_file: MOCK_CODE_FILE, expires_in: 900 }),
    })
  })
  let completeRequestBody: unknown
  await page.route('**/api/setup/handoff-recovery/complete', async (route) => {
    completeRequestBody = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'recovered',
        setup_nonce: MOCK_NONCE,
        next_step: 'Setup will resume automatically.',
      }),
    })
  })

  await page.goto('/#/setup')
  await expect(page.getByRole('heading', { name: 'Restore the setup handoff on the station' })).toBeVisible()

  await page.getByRole('button', { name: 'I lost my setup link' }).click()
  expect(startCalls).toBe(1)

  // Clerk-readable copy: never "nonce"/"handoff"/"elevated" in this panel.
  await expect(page.getByText(MOCK_CODE_FILE)).toBeVisible()
  const panelText = await page.locator('form').filter({ hasText: 'Recovery code' }).innerText()
  expect(panelText.toLowerCase()).not.toContain('nonce')
  expect(panelText.toLowerCase()).not.toContain('elevated')
  expect(panelText).toContain('administrator permission')

  await page.getByLabel('Recovery code').fill('abcdefgh')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page.getByRole('heading', { name: 'Restore the setup handoff on the station' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Durable storage' })).toBeVisible()
  expect(completeRequestBody).toEqual({ code: 'ABCDEFGH' })
  await expect
    .poll(() => page.evaluate(() => window.sessionStorage.getItem('civiccast.setupNonce')))
    .toBe(MOCK_NONCE)
})

test('a wrong recovery code shows an error and keeps the panel open for another try', async ({ page }) => {
  await mockCommonRoutes(page)
  await page.route('**/api/setup/station-state**', async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid or missing setup nonce.' }),
    })
  })
  await page.route('**/api/setup/handoff-recovery/start', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code_file: MOCK_CODE_FILE, expires_in: 900 }),
    })
  })
  await page.route('**/api/setup/handoff-recovery/complete', async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid or expired setup recovery code.' }),
    })
  })

  await page.goto('/#/setup')
  await page.getByRole('button', { name: 'I lost my setup link' }).click()
  await page.getByLabel('Recovery code').fill('zzzzzzzz')
  await page.getByRole('button', { name: 'Continue' }).click()

  const alert = page.getByRole('alert').filter({ hasText: 'did not work' })
  await expect(alert).toBeVisible()
  await expect(page.getByLabel('Recovery code')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Continue' })).toBeVisible()
})
