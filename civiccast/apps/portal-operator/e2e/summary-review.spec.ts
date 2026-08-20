import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync } from 'node:fs'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const evidenceDir = process.env.CIVICCAST_EVIDENCE_DIR ?? 'test-results/evidence'
mkdirSync(evidenceDir, { recursive: true })

const summary = {
  summary_id: 'summary-1',
  meeting_id: 'council-2026-05-14',
  status: 'pending_review',
  narrative: 'The council approved the paving contract 4-1.',
  sourced_claims: [
    {
      claim_id: 'claim-1',
      text: 'The paving contract passed 4-1.',
      claim_type: 'quantitative',
      transcript_ranges: [{ cue_id: 'cue-42', start_seconds: 188.2, end_seconds: 205.9 }],
    },
  ],
  provenance: {
    model_tag: 'gemma3:latest',
    model_digest: 'sha256:abc123',
    ollama_version: '0.9.0',
    prompt_version: 'summary-v0.6',
    extraction_version: 'summary-extract-v0.6',
    runtime_parameters: { temperature: 0 },
    generated_at: '2026-05-14T12:00:00Z',
  },
  audit_fingerprint: `sha256:${'b'.repeat(64)}`,
  operator_message: null,
}

const refusedSummary = {
  ...summary,
  summary_id: 'summary-refused',
  status: 'refused',
  narrative: 'The model could not support a vote count from transcript evidence.',
  sourced_claims: [],
  operator_message: 'No timestamp evidence supports the quantitative claim.',
}

async function mockSummaryBackend(
  page: import('@playwright/test').Page,
  options: { items?: typeof summary[]; failList?: boolean; delayList?: boolean; roles?: string[] } = {},
) {
  let items = options.items ?? [summary]
  const roles = options.roles ?? ['records_clerk']
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'test-operator',
        operator_display_name: 'Test Operator',
        token_id: 'env-test',
        scopes: roles,
        roles,
      }),
    })
  })
  await page.route('**/api/version', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: '2.1.0' }),
    })
  })
  await page.route('**/api/setup/station-state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'complete',
        setup_complete: true,
        profile: null,
        recovery_kit_created: true,
        recovery_kit_id: 'rk-test',
        operator_console_url: 'http://127.0.0.1:5173',
        next_step: 'Open System Health.',
      }),
    })
  })
  await page.route('**/api/setup/storage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ready',
        database_path: 'C:\\CivicCastTester\\data\\civiccast.db',
        backup_path: 'C:\\CivicCastTester\\backups',
        next_step: 'Open Summary review.',
      }),
    })
  })
  await page.route('**/api/staff/installer/backup', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-05-22T18:05:00Z',
        status: 'ready',
        destination: 'C:/CivicCastBackups',
        message: 'Backup destination accepted a write/read/delete proof.',
        next_step: 'Keep this backup drive available before public meetings.',
      }),
    })
  })
  await page.route('**/api/staff/installer/provider-readiness', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-05-22T18:05:00Z',
        next_step: 'Set up only the providers the station needs.',
        items: [],
      }),
    })
  })
  await page.route('**/api/staff/installer/source-setup', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: '2026-05-22T18:05:00Z',
        status: 'ready',
        configured_source_count: 1,
        options: [],
        message: 'A test source is ready.',
        next_step: 'Run preflight before the meeting.',
      }),
    })
  })
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route('**/api/staff/summaries/review-items', async (route) => {
    if (options.delayList) await new Promise((resolve) => setTimeout(resolve, 500))
    if (options.failList) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.' }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items, next_cursor: null }),
    })
  })
  await page.route('**/api/staff/summaries/*/approve', async (route) => {
    const id = route.request().url().split('/summaries/')[1].split('/')[0]
    items = items.map((item) => (item.summary_id === id ? { ...item, status: 'approved' } : item))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(items.find((item) => item.summary_id === id)),
    })
  })
  await page.route('**/api/staff/records', async (route) => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        record_id: 'record-1',
        summary_id: 'summary-1',
        status: 'verified',
        audit_fingerprint: `sha256:${'b'.repeat(64)}:${'c'.repeat(64)}`,
        pdfa: {
          conformance: 'PDF/A-3B',
          file_name: 'council-2026-05-14-record.pdf',
          media_type: 'application/pdf',
          byte_size: 4096,
          embedded_metadata_names: [
            'sourced-claims.json',
            'provenance.json',
            'approval.json',
            'timestamp-token.der',
          ],
        },
        timestamp_proof: {
          algorithm: 'sha256',
          artifact_digest: `sha256:${'d'.repeat(64)}`,
          token_der_b64: 'MII=',
          timestamped_at: '2026-05-14T12:30:00Z',
        },
        artifact_digest: `sha256:${'d'.repeat(64)}`,
      }),
    })
  })
}

async function openSummaryReview(page: import('@playwright/test').Page) {
  await page.goto('/#/summary')
  await expect(page.getByRole('heading', { name: 'Summary review' })).toBeVisible()
}

test.describe('summary review', () => {
  test('desktop success preserves focus while sourced claim seeks transcript', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    await page.setViewportSize({ width: 1440, height: 950 })
    await mockSummaryBackend(page)
    await openSummaryReview(page)

    const approve = page.getByRole('button', { name: 'Approve summary' })
    await approve.focus()
    await page.getByRole('button', { name: /cue-42/ }).click()
    await expect(approve).toBeFocused()
    await expect(page.getByText('cue-42 / 3:08-3:25')).toBeVisible()

    await approve.click()
    await page.getByRole('button', { name: 'Export signed record' }).click()
    await expect(page.getByText(/Signed record exported: record-1/)).toBeVisible()
    await expect(page.getByText(/server validates the\s+PDF\/A-3B artifact/i)).toBeVisible()
    await expect(errors).toEqual([])
    await page.screenshot({ path: `${evidenceDir}/v0.6-summary-review-success-desktop.png`, fullPage: true })
  })

  test('mobile partial/refusal state is actionable', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mockSummaryBackend(page, { items: [refusedSummary] })
    await openSummaryReview(page)
    await expect(page.getByText(/summary .*need.*more evidence/i)).toBeVisible()
    await expect(page.getByText(/regenerate after adding transcript evidence/i)).toBeVisible()
    await page.screenshot({ path: `${evidenceDir}/v0.6-summary-review-partial-mobile.png`, fullPage: true })
  })

  test('mobile success can seek sourced transcript claim', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mockSummaryBackend(page)
    await openSummaryReview(page)
    await page.getByRole('button', { name: /cue-42/ }).click()
    await expect(page.getByText('cue-42 / 3:08-3:25')).toBeVisible()
    await page.screenshot({ path: `${evidenceDir}/v0.6-summary-review-success-mobile.png`, fullPage: true })
  })

  test('loading state renders before summary data returns', async ({ page }) => {
    await mockSummaryBackend(page, { delayList: true })
    await page.goto('/')
    if (await page.getByRole('button', { name: 'Open navigation' }).isVisible()) {
      await page.getByRole('button', { name: 'Open navigation' }).click()
    }
    await page.getByRole('button', { name: 'Summary review' }).click()
    await expect(page.locator('.animate-pulse').first()).toBeVisible()
  })

  test('empty state gives the operator a next step', async ({ page }) => {
    await mockSummaryBackend(page, { items: [] })
    await openSummaryReview(page)
    await expect(page.getByText('No summaries need review.')).toBeVisible()
  })

  test('error state gives a recovery path', async ({ page }) => {
    await mockSummaryBackend(page, { failList: true })
    await openSummaryReview(page)
    await expect(page.getByText('Could not load summary review.')).toBeVisible()
    await expect(page.getByText(/CivicCast database is connected/)).toBeVisible()
  })

  test('keeps summary review read-only without records clerk role', async ({ page }) => {
    await mockSummaryBackend(page, { roles: ['meeting_operator'] })
    await openSummaryReview(page)

    await expect(page.getByText(/Summary approval and signed-record export require the records clerk role/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve summary' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Export signed record' })).toBeDisabled()
    await expect(page.getByText('The paving contract passed 4-1.')).toBeVisible()
  })

  test('axe scan has no serious or critical violations', async ({ page }) => {
    await mockSummaryBackend(page)
    await openSummaryReview(page)
    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
    const blockers = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    )
    expect(blockers).toEqual([])
  })
})
