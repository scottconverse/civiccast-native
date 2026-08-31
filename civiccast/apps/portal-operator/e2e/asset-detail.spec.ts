import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Asset detail + metadata edit accessibility + interaction gate.
 *
 * Backend mocked with page.route() so tests are deterministic. Mocks both
 * GET /api/staff/assets (list) and GET/PATCH /api/staff/assets/<id>
 * (detail + edit) so the round-trip on save can be verified end-to-end.
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
  trim_in_seconds: 30,
  trim_out_seconds: 3000,
  chapters: [
    { t: 60, name: 'Roll call', sub: null },
    { t: 600, name: 'Public comment', sub: null },
  ],
  retention_policy: 'meeting',
  retention_until: null,
  version: 1,
  source_live_session_id: null,
  meeting_body: null,
  content_hash: null,
  thumbnail_path: null,
  file_status: 'ok',
  file_status_checked_at: null,
} as const

async function mockBackend(
  page: import('@playwright/test').Page,
  patchPayloadCapture?: { value?: unknown },
  initialOverrides?: Record<string, unknown>,
) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'asset-editor',
        display_name: 'Asset Editor',
        roles: ['records_clerk'],
      }),
    })
  })
  // The mock backend is stateful: PATCHes mutate the local copy so a
  // subsequent GET reflects the saved state. That's the only way the
  // dirty-tracking UI can converge to "Saved" after a round-trip.
  let current: Record<string, unknown> = { ...MOCK_ASSET, ...initialOverrides }
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([current]),
    })
  })
  await page.route('**/api/staff/assets/council-2026-05-08/unpublish', async (route) => {
    current = { ...current, published_at: null }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(current),
    })
  })
  // AssetDetailScreen mounts OfflineCaptionJobsPanel, which fetches this on
  // load -- mock it so tests that aren't exercising the captions drawer
  // don't pick up a spurious 502 (unmocked route -> the dev proxy's
  // unreachable-backend fallback) and its error alert alongside whatever
  // this test IS asserting on.
  await page.route('**/api/staff/captions/offline-jobs**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.route('**/api/staff/assets/council-2026-05-08', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      if (patchPayloadCapture) patchPayloadCapture.value = body
      current = { ...current, ...body }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(current),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(current),
    })
  })
  // S7 media lifecycle: the asset detail sidebar's MediaLifecyclePanel
  // fetches readiness on mount. Unmocked, that request 502s through the
  // dev-server proxy and the panel's own error alert (role="alert")
  // collides with this file's `getByRole('alert')` assertions on the
  // unpublish-error flow. Mocked here (not per-test) so every test in this
  // file sees a deterministic, ready state regardless of what it's actually
  // testing.
  await page.route('**/api/staff/assets/council-2026-05-08/readiness', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        asset_id: 'council-2026-05-08',
        readiness_state: 'ready',
        readiness_reason: null,
        loudness_status: 'ok',
        measured_lufs: -16.0,
        in_flight_transcode_jobs: [],
        archive_complete: false,
        archive_portal_verified: false,
        archive_ia_verified: false,
        archive_nas_verified: false,
        legal_hold: false,
        updated_at: '2026-05-08T18:00:00Z',
      }),
    })
  })
}

async function openDetail(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Assets' }).click()
  await expect(page.getByRole('heading', { name: 'Assets' })).toBeVisible()
  await page
    .getByRole('button', { name: /Open detail for Council/ })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Council — May 8, 2026' }),
  ).toBeVisible()
}

test.describe('asset detail + metadata edit', () => {
  test('renders metadata editor with prefilled fields', async ({ page }) => {
    await mockBackend(page)
    await openDetail(page)
    await expect(page.getByLabel('Title')).toHaveValue('Council — May 8, 2026')
    await expect(page.getByLabel('Description (optional)')).toHaveValue(
      'Regular session',
    )
    // Radio for the meeting policy is pre-checked.
    const meetingRadio = page.getByRole('radio', { name: /Meeting/ })
    await expect(meetingRadio).toHaveAttribute('aria-checked', 'true')
  })

  test('save button is disabled until form is dirty', async ({ page }) => {
    await mockBackend(page)
    await openDetail(page)
    const save = page.getByRole('button', { name: /^Saved$/ })
    await expect(save).toBeDisabled()

    await page.getByLabel('Title').fill('Council — May 8, 2026 (revised)')
    await expect(
      page.getByRole('button', { name: 'Save metadata' }),
    ).toBeEnabled()
  })

  test('save round-trip dispatches PATCH and converges to clean', async ({
    page,
  }) => {
    const captured: { value?: unknown } = {}
    await mockBackend(page, captured)
    await openDetail(page)
    await page.getByLabel('Title').fill('Council — May 8, 2026 (revised)')
    await page.getByRole('button', { name: 'Save metadata' }).click()
    // After save, the button text returns to "Saved" (clean).
    await expect(page.getByRole('button', { name: /^Saved$/ })).toBeVisible()
    // PATCH body carries only the changed field.
    expect(captured.value).toEqual({
      expected_version: 1,
      title: 'Council — May 8, 2026 (revised)',
    })
  })

  test('meeting-body set and clear send the right PATCH bodies', async ({
    page,
  }) => {
    // Audit TEST-006: the operator input that CREATES facet data was never
    // driven - a mutation sending "" instead of null (which the backend
    // 422s) would ship green while operators silently could not untag.
    const captured: { value?: unknown } = {}
    await mockBackend(page, captured)
    await openDetail(page)

    await page.getByLabel(/Meeting body/).fill('City Council')
    await page.getByRole('button', { name: 'Save metadata' }).click()
    await expect(page.getByRole('button', { name: /^Saved$/ })).toBeVisible()
    expect(captured.value).toEqual({
      expected_version: 1,
      meeting_body: 'City Council',
    })

    // Blank the field: the PATCH must carry an explicit null (clear).
    // (The stateful mock does not bump `version`, so expected_version
    // stays 1 here; the real backend's bump is pinned in pytest.)
    await page.getByLabel(/Meeting body/).fill('')
    await page.getByRole('button', { name: 'Save metadata' }).click()
    await expect(page.getByRole('button', { name: /^Saved$/ })).toBeVisible()
    expect(captured.value).toEqual({
      expected_version: 1,
      meeting_body: null,
    })
  })

  test('edit-trim button routes to the trim editor', async ({ page }) => {
    await mockBackend(page)
    await openDetail(page)
    await page.getByRole('button', { name: 'Edit trim & chapters' }).click()
    await expect(
      page.getByRole('dialog', { name: /Council/ }),
    ).toBeVisible()
  })

  test('retention policy cards support arrow-key selection', async ({ page }) => {
    await mockBackend(page)
    await openDetail(page)
    await page.getByRole('radio', { name: /Meeting/ }).press('ArrowRight')
    await expect(page.getByRole('radio', { name: /Short/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  test('back button returns to the assets list', async ({ page }) => {
    await mockBackend(page)
    await openDetail(page)
    await page.getByRole('button', { name: 'Back to assets' }).click()
    await expect(page.getByRole('heading', { name: 'Assets' })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Council — May 8, 2026' }),
    ).toBeHidden()
  })

  test('published asset can be removed from the portal (Codex PR #419 P1)', async ({
    page,
  }) => {
    // The A-1 first-run seeded sample's own description tells the operator
    // to "Delete it like any other asset once real content is ready" -- no
    // removal path existed anywhere in the console before this fix.
    await mockBackend(page, undefined, { published_at: '2026-05-08T18:00:00Z' })
    await openDetail(page)

    const removeButton = page.getByRole('button', { name: 'Remove from portal' })
    await expect(removeButton).toBeVisible()

    await removeButton.click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Remove from portal' }).click()

    // Once unpublished, the confirmed date disappears and so does the action.
    await expect(page.getByRole('button', { name: 'Remove from portal' })).toBeHidden()
    await expect(page.getByText('—', { exact: true })).toBeVisible()
  })

  test('a failed unpublish shows the error without leaving the screen', async ({
    page,
  }) => {
    await mockBackend(page, undefined, { published_at: '2026-05-08T18:00:00Z' })
    await page.route('**/api/staff/assets/council-2026-05-08/unpublish', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Durable storage is not ready.' }),
      })
    })
    await openDetail(page)

    await page.getByRole('button', { name: 'Remove from portal' }).click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Remove from portal' }).click()

    await expect(page.getByRole('alert')).toContainText('Durable storage is not ready.')
    // The button is still there -- the operator can retry.
    await expect(page.getByRole('button', { name: 'Remove from portal' })).toBeVisible()
  })

  test('declining the confirmation leaves the asset published', async ({ page }) => {
    await mockBackend(page, undefined, { published_at: '2026-05-08T18:00:00Z' })
    await openDetail(page)

    await page.getByRole('button', { name: 'Remove from portal' }).click()
    const dialog = page.getByRole('alertdialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()

    // Still published -- the cancelled ConfirmDialog never dispatched the call.
    await expect(page.getByRole('button', { name: 'Remove from portal' })).toBeVisible()
  })

  // Candidate #17 tester finding 5: "nothing tells the volunteer that
  // publishing is what starts transcription" and no progress beyond a bare
  // Retry-only panel. Two things to prove end-to-end: the trigger is
  // discoverable on the panel itself, and a running job reads as running.
  test('offline caption panel states plainly that publish approval starts it', async ({
    page,
  }) => {
    await mockBackend(page)
    await openDetail(page)
    await expect(
      page.getByText(
        "Approving this recording's portal surface on the Publish dashboard is what starts it",
      ),
    ).toBeVisible()
  })

  test('a running caption job reads as "Transcribing..." with elapsed time, not a bare Pending label', async ({
    page,
  }) => {
    await mockBackend(page)
    // Registered after mockBackend() -- Playwright matches the
    // most-recently-registered route first, so this overrides
    // mockBackend()'s own "no jobs" default for this test only.
    await page.route('**/api/staff/captions/offline-jobs**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            job_id: 'job-running-1',
            asset_id: 'council-2026-05-08',
            source_path: 'C:/media/council.mp4',
            package_dir: 'C:/media/council-captions',
            state: 'pending',
            attempts: 1,
            cue_count: 0,
            published_cue_count: 0,
            last_error: '',
            created_at: new Date(Date.now() - 60_000).toISOString(),
            updated_at: new Date(Date.now() - 60_000).toISOString(),
          },
        ]),
      })
    })
    await openDetail(page)

    await expect(page.getByText(/Transcribing…/)).toBeVisible()
    await expect(
      page.getByText(/several minutes for a full meeting recording, not seconds/),
    ).toBeVisible()
  })

  test('axe scan: detail screen has no serious/critical violations', async ({
    page,
  }) => {
    await mockBackend(page)
    await openDetail(page)
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
        `axe-core found ${blockers.length} serious/critical violation(s) on the detail screen:\n\n${summary}`,
      )
    }
  })
})
