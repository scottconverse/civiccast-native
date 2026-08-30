import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * Successor to `setup-handoff-recovery.spec.ts` (deleted): the installer
 * "setup nonce" handoff, its "I lost my setup link" in-product recovery
 * flow, and the elevated `--civiccast-restore-setup-handoff` command-line
 * path are all retired (owner decision 2026-08-29). First setup is now
 * admitted purely by the FastAPI backend checking that the request's peer
 * IP is loopback (`civiccast/installer/router.py`'s
 * `_require_local_setup_request`).
 *
 * Route-mocked, like the file this replaces -- no real backend, no
 * `@fullstack` tag, so this runs under the default `test:a11y` project.
 * There is no practical way to make a real Playwright-driven browser
 * request look non-loopback to the real backend (the gate reads
 * `request.client.host` off the ASGI transport itself, not a
 * caller-supplied header -- see `_is_local_client`'s doc comment), so the
 * "denied" scenario below is simulated by mocking the same 403 the real
 * backend returns. The real loopback-vs-remote distinction is proven
 * against the actual backend at the Python unit level in
 * `tests/installer/test_installer_api.py` (using FastAPI's `TestClient(...,
 * client=("203.0.113.20", 4242))`), and the real allowed-from-loopback path
 * is proven end-to-end against a live backend in
 * `setup-real-boundary.spec.ts`.
 */

const LOOPBACK_DENIED_DETAIL = 'First setup can only be done from the station computer itself.'

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
}

test('the plain operator console URL, with no query string, reaches a working First Setup when the request is local', async ({
  page,
}) => {
  await mockCommonRoutes(page)
  await page.route('**/api/setup/station-state**', async (route) => {
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
  })
  await page.route('**/api/setup/storage**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'not_configured', upload_dir: null, database_path: null }),
    })
  })

  // No `?nonce=...` anywhere -- the installer hands the console this exact
  // bare URL now (`InstallerActionResult.operator_console_url` is a plain
  // constant, per `civiccast/installer/service.py`).
  await page.goto('/#/setup')

  await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()
  const prepareButton = page.getByRole('button', { name: 'Prepare storage' })
  await expect(prepareButton).toBeVisible()
  // Always actionable once the panel renders at all -- there is no more
  // nonce-derived `disabled` gate on this control.
  await expect(prepareButton).toBeEnabled()

  // None of the retired nonce/handoff surfaces or advice may appear.
  await expect(page.getByText(/nonce/i)).toHaveCount(0)
  await expect(page.getByText(/i lost my setup link/i)).toHaveCount(0)
})

test('a non-local request gets the honest station-only refusal, never advice to click the button that just failed', async ({
  page,
}) => {
  await mockCommonRoutes(page)
  await page.route('**/api/setup/station-state**', async (route) => {
    await route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: LOOPBACK_DENIED_DETAIL }),
    })
  })

  await page.goto('/#/setup')

  const heading = page.getByRole('heading', {
    name: 'First setup can only be done from the station computer itself',
  })
  await expect(heading).toBeVisible()
  await expect(page.getByText(/opened in a browser running on the station itself/i)).toBeVisible()

  // The old copy told the operator to go back to the installer and click
  // "Open operator console" again -- the exact button that, if they're
  // seeing this screen, already failed to reach loopback. That framing, the
  // command-line recovery instruction, and the in-product recovery panel
  // must all be gone.
  await expect(page.getByText(/open operator console/i)).toHaveCount(0)
  await expect(page.getByText(/i lost my setup link/i)).toHaveCount(0)
  await expect(page.getByText(/--civiccast-restore-setup-handoff/i)).toHaveCount(0)
  await expect(page.getByText(/for it staff/i)).toHaveCount(0)

  // Points to support instead of a dead-end -- and to the in-product manual's
  // no-GitHub-account reporting path, not straight to a GitHub issue form.
  await expect(page.getByRole('link', { name: /report it/i })).toBeVisible()
})
