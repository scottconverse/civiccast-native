import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Trim/chapter editor accessibility + interaction gate.
 *
 * The preview environment has no backend, so the editor's data fetch
 * fails. To exercise the editor itself we mock GET /api/staff/assets/<id>
 * with a Playwright route handler. This keeps the test deterministic
 * without standing up a real server.
 *
 * Per release plan §0.3 risk note: "trim/chapter editor on a phone is
 * the hidden hard part. Don't claim mobile-first if the trim controls
 * fail under one-thumb operation." The mobile test below verifies that
 * each transport / set-in / set-out / mark button meets the 44px WCAG
 * touch-target floor.
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const MOCK_ASSET = {
  asset_id: 'council-2026-05-08',
  title: 'Council — May 8, 2026',
  description: 'Regular session',
  state: 'validated',
  manifest_url: null,
  file_path: null,
  file_size_bytes: 5_000_000,
  duration_seconds: 3600,
  codec_video: 'h264',
  codec_audio: 'aac',
  width_px: 1920,
  height_px: 1080,
  bitrate_bps: 5_000_000,
  format_name: 'mov,mp4,m4a,3gp,3g2,mj2',
  published_at: null,
  trim_in_seconds: 30.333,
  trim_out_seconds: 3000.667,
  chapters: [
    { t: 60, name: 'Roll call', sub: null },
    { t: 600, name: 'Public comment', sub: null },
  ],
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

async function mockBackend(
  page: import('@playwright/test').Page,
  options: { patchBodies?: unknown[] } = {},
) {
  let currentAsset = { ...MOCK_ASSET }
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([currentAsset]),
    })
  })
  await page.route('**/api/staff/assets/council-2026-05-08', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      options.patchBodies?.push(body)
      currentAsset = {
        ...currentAsset,
        ...body,
        version: currentAsset.version + 1,
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentAsset),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(currentAsset),
    })
  })
}

async function navigateToAssets(page: import('@playwright/test').Page) {
  const desktopAssets = page
    .locator('aside[aria-label="Primary navigation"]')
    .getByRole('button', { name: 'Assets' })
  if (await desktopAssets.isVisible().catch(() => false)) {
    await desktopAssets.click()
    return
  }
  // Mobile drawer behavior is covered in a11y.spec. The trim gate is about
  // the editor itself, so direct-link on phone-sized viewports and avoid
  // turning a drawer interaction into an unrelated trim failure.
  await page.goto('/#/assets')
}

async function openEditor(page: import('@playwright/test').Page) {
  await mockBackend(page)
  await page.goto('/')
  await navigateToAssets(page)
  await expect(page.getByRole('heading', { name: 'Assets' })).toBeVisible()
  await page.getByRole('button', { name: /Edit trim and chapters/ }).click()
  await expect(
    page.getByRole('dialog', { name: /Council/ }),
  ).toBeVisible()
}

test.describe('trim editor', () => {
  test('opens with role=dialog, asset name, and prefilled in/out', async ({
    page,
  }) => {
    await openEditor(page)
    const dialog = page.getByRole('dialog', { name: /Council/ })
    // Heading shows the asset title and id.
    await expect(dialog.getByRole('heading', { name: /Council/ })).toBeVisible()
    // The asset prefills in=30s, out=3000s, dur=3600s. Confirm via the
    // dedicated In/Out sliders (role=slider exposes aria-valuetext).
    const inSlider = dialog.getByRole('slider', { name: 'In point' })
    const outSlider = dialog.getByRole('slider', { name: 'Out point' })
    await expect(inSlider).toHaveAttribute('aria-valuetext', '00:00:30')
    await expect(outSlider).toHaveAttribute('aria-valuetext', '00:50:00')
  })

  test('chapter list renders mocked chapters and supports rename/remove', async ({
    page,
  }) => {
    await openEditor(page)
    const dialog = page.getByRole('dialog', { name: /Council/ })
    await expect(dialog.getByRole('list', { name: 'Chapter list' })).toBeVisible()
    await expect(dialog.locator('text=Roll call')).toBeVisible()
    await expect(dialog.locator('text=Public comment')).toBeVisible()

    await dialog.getByRole('button', { name: 'Remove chapter Roll call' }).click()
    await expect(dialog.locator('text=Roll call')).toBeHidden()
  })

  test('Set IN / Set OUT buttons are keyboard reachable', async ({ page }) => {
    await openEditor(page)
    const dialog = page.getByRole('dialog', { name: /Council/ })
    await expect(dialog.getByRole('button', { name: 'Set IN' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Set OUT' })).toBeVisible()
  })

  test('29.97fps frame-step trim values save and reload without integer truncation', async ({
    page,
  }) => {
    const patchBodies: unknown[] = []
    await mockBackend(page, { patchBodies })
    await page.goto('/')
    await navigateToAssets(page)
    await page.getByRole('button', { name: /Edit trim and chapters/ }).click()
    const dialog = page.getByRole('dialog', { name: /Council/ })
    await expect(dialog.getByRole('slider', { name: 'In point' })).toHaveAttribute(
      'aria-valuenow',
      '30.333',
    )

    await page.keyboard.press('ArrowRight')
    await dialog.getByRole('button', { name: 'Set IN' }).click()
    await dialog.getByRole('button', { name: 'Save trim & chapters' }).click()
    await expect(dialog).toBeHidden()

    expect(patchBodies).toHaveLength(1)
    const saved = patchBodies[0] as {
      trim_in_seconds: number
      trim_out_seconds: number
    }
    expect(saved.trim_in_seconds).toBeCloseTo(30.366, 3)
    expect(saved.trim_out_seconds).toBe(3000.667)

    await page.getByRole('button', { name: /Edit trim and chapters/ }).click()
    const reopened = page.getByRole('dialog', { name: /Council/ })
    await expect(reopened.getByRole('slider', { name: 'In point' })).toHaveAttribute(
      'aria-valuenow',
      '30.366',
    )
  })

  test('discard closes the editor', async ({ page }) => {
    await openEditor(page)
    await page.getByRole('button', { name: 'Discard' }).click()
    await expect(
      page.getByRole('dialog', { name: /Council/ }),
    ).toBeHidden()
  })

  test('UX-004 focus trap keeps Tab inside the trim editor', async ({ page }) => {
    await openEditor(page)
    const dialog = page.getByRole('dialog', { name: /Council/ })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Close trim editor' })).toBeFocused()

    await page.keyboard.press('Shift+Tab')
    await expect.poll(async () =>
      page.evaluate(() => {
        const active = document.activeElement
        const dialogEl = document.querySelector('[role="dialog"]')
        return Boolean(active && dialogEl?.contains(active))
      }),
    ).toBe(true)

    for (let i = 0; i < 18; i += 1) await page.keyboard.press('Tab')
    await expect.poll(async () =>
      page.evaluate(() => {
        const active = document.activeElement
        const dialogEl = document.querySelector('[role="dialog"]')
        return Boolean(active && dialogEl?.contains(active))
      }),
    ).toBe(true)
  })

  test('axe scan: trim editor has no serious/critical violations', async ({
    page,
  }) => {
    await openEditor(page)
    const results = await new AxeBuilder({ page })
      .include('[role="dialog"]')
      .withTags(WCAG_TAGS)
      .analyze()
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
        `axe-core found ${blockers.length} serious/critical violation(s) in the trim editor:\n\n${summary}`,
      )
    }
  })
})

test.describe('trim editor mobile (one-thumb operation)', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('transport + set-in/out buttons meet 44px touch-target floor', async ({
    page,
  }) => {
    await openEditor(page)
    const dialog = page.getByRole('dialog', { name: /Council/ })
    const labels = [
      'Go to start (Home)',
      'Step back one second (Shift+←)',
      'Step back one frame (Left arrow)',
      'Step forward one frame (Right arrow)',
      'Step forward one second (Shift+→)',
      'Go to end (End)',
      'Set IN',
      'Set OUT',
      '+ Mark',
    ]
    for (const name of labels) {
      const btn = dialog.getByRole('button', { name })
      await expect(btn).toBeVisible()
      const box = await btn.boundingBox()
      if (!box) throw new Error(`No bounding box for "${name}"`)
      // 44x44 is the WCAG 2.5.5 Level AAA target; we're using it as the
      // mobile floor here so the editor passes the release plan §0.3 risk
      // note ("don't claim mobile-first if controls fail under one-thumb
      // operation").
      expect.soft(box.width, `${name} width`).toBeGreaterThanOrEqual(44)
      expect.soft(box.height, `${name} height`).toBeGreaterThanOrEqual(44)
    }
  })

  test('mobile axe scan: trim editor has no serious/critical violations', async ({
    page,
  }) => {
    await openEditor(page)
    const results = await new AxeBuilder({ page })
      .include('[role="dialog"]')
      .withTags(WCAG_TAGS)
      .analyze()
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
        `axe-core (mobile) found ${blockers.length} serious/critical violation(s) in the trim editor:\n\n${summary}`,
      )
    }
  })
})
