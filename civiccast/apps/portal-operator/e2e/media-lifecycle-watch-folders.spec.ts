import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Media Lifecycle Settings -> Watch folders (candidate #17 field evidence):
 *
 *  - Finding 3: "no 'Browse...' picker" -- a non-technical operator had to
 *    type an exact filesystem path from memory.
 *  - Finding 4: "'Last poll: never' with NO 'Poll now'/'Scan' button and no
 *    progress" -- the daemon DID auto-ingest within about a minute, but the
 *    UI gave zero feedback that anything was happening.
 *
 * Backend mocked with page.route() -- same convention as asset-detail.spec.ts.
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

function watchFolderConfig(overrides: Record<string, unknown> = {}) {
  return {
    config_id: 'wf-1',
    monitor_path: 'D:\\incoming',
    import_naming_pattern: null,
    enabled: true,
    settle_window_seconds: 10,
    retention_policy_default: null,
    last_scanned_at: null,
    last_scan_files_found: 0,
    poll_interval_seconds: 5,
    processed_file_mode: 'leave_with_ledger',
    processed_subfolder_name: 'processed',
    health_status: 'unknown',
    degraded_reason: null,
    degraded_since: null,
    last_poll_at: null,
    last_ingest_at: null,
    created_at: '2026-08-21T00:00:00Z',
    updated_at: '2026-08-21T00:00:00Z',
    ...overrides,
  }
}

async function mockBackend(page: import('@playwright/test').Page) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'clerk',
        display_name: 'Records Clerk',
        roles: ['records_clerk'],
      }),
    })
  })
  let configs = [watchFolderConfig()]
  await page.route('**/api/staff/media-lifecycle/watch-folder-configs', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(configs),
      })
      return
    }
    await route.continue()
  })
  await page.route('**/api/staff/media-lifecycle/retention-policies', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/staff/media-lifecycle/storage-budget', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_bytes_used: 0,
        budget_bytes: null,
        percent_used: null,
        by_retention_policy: [],
      }),
    })
  })
  return {
    setConfigs: (rows: ReturnType<typeof watchFolderConfig>[]) => {
      configs = rows
    },
  }
}

async function openWatchFolders(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Media Lifecycle Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Media Lifecycle Settings' })).toBeVisible()
}

test.describe('Watch folders — folder browser (finding 3)', () => {
  test('a non-technical operator can pick a folder instead of typing an exact path', async ({
    page,
  }) => {
    await mockBackend(page)
    await page.route('**/api/staff/media-lifecycle/browse-folders**', async (route) => {
      const url = new URL(route.request().url())
      const path = url.searchParams.get('path')
      if (!path) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            current_path: null,
            parent_path: null,
            separator: '\\',
            entries: [{ name: 'D:\\', path: 'D:\\' }],
            readable: true,
          }),
        })
        return
      }
      if (path === 'D:\\') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            current_path: 'D:\\',
            parent_path: null,
            separator: '\\',
            entries: [{ name: 'incoming', path: 'D:\\incoming' }],
            readable: true,
          }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          current_path: 'D:\\incoming',
          parent_path: 'D:\\',
          separator: '\\',
          entries: [],
          readable: true,
        }),
      })
    })
    await openWatchFolders(page)

    await page.getByRole('button', { name: 'Browse…' }).click()
    const dialog = page.getByRole('dialog', { name: 'Choose a folder' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /D:\\/ }).click()
    await dialog.getByRole('button', { name: /incoming/ }).click()
    await dialog.getByRole('button', { name: 'Use this folder' }).click()

    await expect(page.getByLabel('Watch folder path')).toHaveValue('D:\\incoming')
  })
})

test.describe('Watch folders — Scan now (finding 4)', () => {
  test('a fresh watch folder explains itself instead of a bare "Last poll: never"', async ({
    page,
  }) => {
    await mockBackend(page)
    await openWatchFolders(page)

    await expect(page.getByText('Not scanned yet')).toBeVisible()
    await expect(page.getByText(/next one runs within 5s, or use Scan now/)).toBeVisible()
    await expect(page.getByText('Last poll: never')).toBeHidden()
  })

  test('Scan now forces an immediate check and reports what it found', async ({ page }) => {
    const backend = await mockBackend(page)
    await openWatchFolders(page)

    await page.route(
      '**/api/staff/media-lifecycle/watch-folder-configs/wf-1/scan-now',
      async (route) => {
        const updated = watchFolderConfig({
          health_status: 'ok',
          last_poll_at: new Date().toISOString(),
          last_ingest_at: new Date().toISOString(),
        })
        backend.setConfigs([updated])
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            config: updated,
            healthy: true,
            files_seen: 2,
            files_ingested: 1,
            files_reprocessed: 0,
            files_failed: 0,
            error: null,
          }),
        })
      },
    )

    await page.getByRole('button', { name: 'Scan now' }).click()
    // The daemon's own poll cadence is 5s; a real, immediate feedback loop
    // must not require waiting that out.
    await expect(page.getByText('OK', { exact: true })).toBeVisible()
    await expect(page.getByText(/Last poll: \d+s ago|Last poll: now/)).toBeVisible()
  })

  test('a scan request failure shows a plain-language reason, not silence', async ({ page }) => {
    await mockBackend(page)
    await openWatchFolders(page)

    await page.route(
      '**/api/staff/media-lifecycle/watch-folder-configs/wf-1/scan-now',
      async (route) => {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'The watch-folder daemon is not running in this deployment.',
          }),
        })
      },
    )

    await page.getByRole('button', { name: 'Scan now' }).click()
    await expect(
      page.getByText('The watch-folder daemon is not running in this deployment.'),
    ).toBeVisible()
  })

  test('axe scan: watch folders screen has no serious/critical violations', async ({ page }) => {
    await mockBackend(page)
    await openWatchFolders(page)
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
        `axe-core found ${blockers.length} serious/critical violation(s) on the watch folders screen:\n\n${summary}`,
      )
    }
  })
})
