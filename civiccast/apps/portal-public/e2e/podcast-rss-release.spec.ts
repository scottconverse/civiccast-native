import { test, expect } from '@playwright/test'

/**
 * 1.0-hardening: previously asserted only <body> visibility. Now proves the
 * public portal mounts with rendered content and no boot errors. The podcast
 * RSS feed itself is generated server-side and covered by backend tests; this
 * guards the resident-facing shell that links it.
 */
test.describe('podcast RSS: public portal mounts', () => {
  test('mounts with rendered content and no page errors', async ({ page }) => {
    const pageErrors: Error[] = []
    page.on('pageerror', (err) => pageErrors.push(err))

    await page.goto('/')
    const root = page.locator('#root')
    await expect(root).toBeVisible()
    await expect
      .poll(async () => root.evaluate((el) => el.childElementCount))
      .toBeGreaterThan(0)
    expect(pageErrors, pageErrors.map((e) => e.message).join('\n')).toEqual([])
  })
})
