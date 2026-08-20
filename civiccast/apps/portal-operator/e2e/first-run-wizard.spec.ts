import { test, expect } from '@playwright/test'

/**
 * 1.0-hardening: previously asserted only <body> visibility at two widths.
 * Now proves the app shell genuinely mounts (rendered children, no page
 * errors) at desktop AND mobile viewports — a bundle that crashes at either
 * width fails here. The full wizard journey needs a backend and is covered by
 * the installer's lifecycle proofs, not this preview-served spec.
 */
test.describe('first-run wizard: shell mounts at both widths', () => {
  test('mounts with rendered content at desktop and mobile', async ({ page }) => {
    const pageErrors: Error[] = []
    page.on('pageerror', (err) => pageErrors.push(err))

    await page.goto('/')
    const root = page.locator('#root')
    await expect(root).toBeVisible()
    await expect
      .poll(async () => root.evaluate((el) => el.childElementCount))
      .toBeGreaterThan(0)

    await page.setViewportSize({ width: 375, height: 812 })
    await expect(root).toBeVisible()
    await expect
      .poll(async () => root.evaluate((el) => el.childElementCount))
      .toBeGreaterThan(0)
    expect(pageErrors, pageErrors.map((e) => e.message).join('\n')).toEqual([])
  })
})
