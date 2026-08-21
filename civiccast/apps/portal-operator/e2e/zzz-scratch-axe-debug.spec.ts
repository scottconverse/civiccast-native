import { test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

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
  chapters: [],
  retention_policy: 'meeting',
  retention_until: null,
  version: 1,
  source_live_session_id: null,
  meeting_body: null,
}

test('debug axe violation', async ({ page }) => {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ operator_id: 'x', display_name: 'X', roles: ['records_clerk'] }),
    })
  })
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_ASSET]) })
  })
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
  await page.route('**/api/staff/assets/council-2026-05-08', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_ASSET) })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Assets' }).click()
  await page.getByRole('button', { name: /Open detail for Council/ }).click()
  await page.getByRole('heading', { name: 'Council — May 8, 2026' }).waitFor()

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze()

  for (const v of results.violations) {
    if (v.id !== 'color-contrast') continue
    console.log('=== VIOLATION', v.id, v.impact)
    for (const node of v.nodes) {
      console.log('TARGET:', JSON.stringify(node.target))
      console.log('HTML:', node.html)
      console.log('MESSAGE:', node.failureSummary)
      console.log('---')
    }
  }
})
