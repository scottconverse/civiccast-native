import { expect, test } from '@playwright/test'

test('missing staff credentials redirect protected routes to First Setup sign-in', async ({ page }) => {
  await page.route('**/api/version', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0-rc16' }) })
  })
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
  await page.route('**/api/setup/storage**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ready' }) })
  })

  await page.goto('/#/channels')

  await expect(page).toHaveURL(/#\/setup/)
  await expect(page.getByRole('heading', { name: 'Admin sign-in' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Channels' })).toHaveCount(0)
})
