import { test, expect } from '@playwright/test'

/**
 * 1.0-hardening: previously asserted only <body> visibility. Now proves the
 * operator shell mounts with rendered content and no boot errors, so the
 * pre-flight surface's host app is genuinely alive in the preview build. The
 * pre-flight evaluator itself is covered by backend tests
 * (tests/live/test_preflight*.py); this guards the shell that hosts it.
 */
test.describe('pre-flight: operator shell mounts', () => {
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
