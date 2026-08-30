import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

/**
 * Assets/Library screen upload control (candidate #17 field evidence,
 * findings 1-2): "the obvious 'add a video' screen has NO upload button and
 * no file input at all" -- the only operator-side upload lived inside a
 * First Setup rehearsal picker, never labeled "Upload files." This spec
 * proves the control this repo added to fix that: every state (idle,
 * choosing, unsupported type, uploading with progress, success, failure),
 * driven end-to-end against a mocked `/api/staff/assets/upload`.
 *
 * Backend mocked with page.route() -- same convention as asset-detail.spec.ts.
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

async function mockBackend(
  page: import('@playwright/test').Page,
  options: { roles?: string[] } = {},
) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'meeting-op',
        display_name: 'Meeting Operator',
        roles: options.roles ?? ['meeting_operator'],
      }),
    })
  })
  let assets: Record<string, unknown>[] = []
  await page.route('**/api/staff/assets', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(assets),
      })
      return
    }
    await route.continue()
  })
  await page.route('**/api/staff/assets/readiness-dashboard', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_assets: 0,
        ready_count: 0,
        transcoding_count: 0,
        missing_count: 0,
        rejected_count: 0,
        by_asset: [],
      }),
    })
  })
  return {
    setAssets: (rows: Record<string, unknown>[]) => {
      assets = rows
    },
  }
}

async function openAssets(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Assets' }).click()
  await expect(page.getByRole('heading', { name: 'Assets' })).toBeVisible()
}

test.describe('Assets/Library upload control', () => {
  test('the screen offers a visible Upload video control -- no more "no way to add media"', async ({
    page,
  }) => {
    await mockBackend(page)
    await openAssets(page)
    await expect(page.getByRole('button', { name: 'Upload video' })).toBeVisible()
  })

  test('names accepted file types and rejects an unsupported one before any network call', async ({
    page,
  }) => {
    await mockBackend(page)
    await openAssets(page)
    await page.getByRole('button', { name: 'Upload video' }).click()
    await expect(page.getByText(/MP4, MOV, MKV, WebM, AVI, or MPEG-TS/)).toBeVisible()

    let uploadCalled = false
    await page.route('**/api/staff/assets/upload', async (route) => {
      uploadCalled = true
      await route.continue()
    })

    await page.getByLabel('Video file').setInputFiles({
      name: 'agenda.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('not a video'),
    })
    await expect(
      page.getByText(/is not a supported video file\. Accepted types:/),
    ).toBeVisible()
    expect(uploadCalled).toBe(false)
  })

  test('walks choosing -> uploading -> success, and the new asset appears in the table', async ({
    page,
  }) => {
    const backend = await mockBackend(page)
    await openAssets(page)

    await page.route('**/api/staff/assets/upload', async (route) => {
      backend.setAssets([
        {
          asset_id: 'city-council-abc123',
          title: 'City Council',
          description: null,
          meeting_body: null,
          state: 'pending_ingest',
          manifest_url: null,
          published_at: null,
          file_path: '/uploads/city-council-abc123/council.mp4',
          file_size_bytes: 12,
          duration_seconds: null,
          codec_video: null,
          codec_audio: null,
          width_px: null,
          height_px: null,
          bitrate_bps: null,
          format_name: null,
          trim_in_seconds: null,
          trim_out_seconds: null,
          chapters: [],
          retention_policy: 'default',
          retention_until: null,
          version: 1,
          source_live_session_id: null,
        },
      ])
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          asset_id: 'city-council-abc123',
          title: 'City Council',
          state: 'pending_ingest',
          file_path: '/uploads/city-council-abc123/council.mp4',
          file_size_bytes: 12,
        }),
      })
    })

    await page.getByRole('button', { name: 'Upload video' }).click()
    await page.getByLabel('Title').fill('City Council')
    await page.getByLabel('Video file').setInputFiles({
      name: 'council.mp4',
      mimeType: 'video/mp4',
      buffer: Buffer.from('fake-video-bytes'),
    })
    await page.getByRole('button', { name: 'Upload', exact: true }).click()

    await expect(page.getByText('Uploaded: City Council')).toBeVisible()
    await expect(page.getByRole('button', { name: /Open detail for City Council/ })).toBeVisible()
  })

  test('shows the plain-language server reason on a rejected upload', async ({ page }) => {
    await mockBackend(page)
    await openAssets(page)

    await page.route('**/api/staff/assets/upload', async (route) => {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail:
            "Video codec 'mpeg2video' is not supported. Supported codecs: av1, h264, hevc, prores, vp8, vp9.",
        }),
      })
    })

    await page.getByRole('button', { name: 'Upload video' }).click()
    await page.getByLabel('Title').fill('Bad file')
    await page.getByLabel('Video file').setInputFiles({
      name: 'old.mp4',
      mimeType: 'video/mp4',
      buffer: Buffer.from('fake-video-bytes'),
    })
    await page.getByRole('button', { name: 'Upload', exact: true }).click()

    await expect(page.getByText(/Video codec 'mpeg2video' is not supported/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  })

  test('never hides the control for a role without upload rights -- stays visible, disabled, with a reason', async ({
    page,
  }) => {
    await mockBackend(page, { roles: ['publish_operator'] })
    await openAssets(page)
    await page.getByRole('button', { name: 'Upload video' }).click()
    await expect(
      page.getByText(
        'A records clerk, meeting operator, or support administrator role is required to upload video.',
      ),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Upload', exact: true })).toBeDisabled()
  })

  test('axe scan: assets screen with the upload panel open has no serious/critical violations', async ({
    page,
  }) => {
    await mockBackend(page)
    await openAssets(page)
    await page.getByRole('button', { name: 'Upload video' }).click()
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
        `axe-core found ${blockers.length} serious/critical violation(s) with the upload panel open:\n\n${summary}`,
      )
    }
  })
})
