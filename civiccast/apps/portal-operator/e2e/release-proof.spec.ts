import { test, expect } from '@playwright/test'

/**
 * 1.0-hardening: this spec previously asserted only that <body> was visible —
 * a fully broken bundle still passed it ("release-proof" proved nothing).
 * It now proves the operator app actually MOUNTS: the React root has rendered
 * children, the document identifies itself, and no page error fired during
 * boot. A deeper release-proof journey (login → dashboard) is tracked as
 * follow-on e2e work; this is the honest floor, not the ceiling.
 */
test.describe('release proof: operator app boots', () => {
  test('mounts the app shell with no page errors', async ({ page }) => {
    const pageErrors: Error[] = []
    page.on('pageerror', (err) => pageErrors.push(err))

    await page.goto('/')
    const root = page.locator('#root')
    await expect(root).toBeVisible()
    // A mounted React app has rendered children; an empty #root means the
    // bundle crashed before first paint.
    await expect
      .poll(async () => root.evaluate((el) => el.childElementCount))
      .toBeGreaterThan(0)
    await expect(page).toHaveTitle(/CivicCast/i)
    expect(pageErrors, pageErrors.map((e) => e.message).join('\n')).toEqual([])
  })
})
