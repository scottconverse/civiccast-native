import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const evidenceDir = process.env.CIVICCAST_EVIDENCE_DIR ?? 'test-results/evidence'
mkdirSync(evidenceDir, { recursive: true })

const approvedSummary = {
  summary_id: 'summary-approved',
  meeting_id: 'council-2026-05-14',
  status: 'approved',
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

async function openWithRecordBackend(
  page: import('@playwright/test').Page,
  options: { failExport?: boolean } = {},
) {
  const roles = ['records_clerk']
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: 'records-clerk',
        display_name: 'Records Clerk',
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
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [approvedSummary], next_cursor: null }),
    })
  })
  await page.route('**/api/staff/records', async (route) => {
    if (options.failExport) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Approve the sourced summary before exporting a signed PDF/A record.',
        }),
      })
      return
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        record_id: 'record-approved',
        summary_id: 'summary-approved',
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
  await page.goto('/#/summary')
}

test.describe('signed record export', () => {
  test('exports approved summary and records PDF/A status on desktop', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    await page.setViewportSize({ width: 1280, height: 900 })
    await openWithRecordBackend(page)
    await expect(page.getByRole('button', { name: 'Approve summary' })).toBeDisabled()
    await page.getByRole('button', { name: 'Export signed record' }).click()
    await expect(page.getByText(/Signed record exported: record-approved/)).toBeVisible()
    await expect(page.getByText(/server validates the\s+PDF\/A-3B artifact/i)).toBeVisible()
    await expect(page.getByText(/sha256:dddd/)).toBeVisible()
    await expect(errors).toEqual([])
    await page.screenshot({ path: `${evidenceDir}/v0.6-signed-record-export-desktop.png`, fullPage: true })
  })

  test('export error gives a concrete recovery step', async ({ page }) => {
    await openWithRecordBackend(page, { failExport: true })
    await page.getByRole('button', { name: 'Export signed record' }).click()
    await expect(page.getByText('Could not load summary review.')).toBeVisible()
    await expect(page.getByText(/Approve the sourced summary before exporting/)).toBeVisible()
    await expect(page.getByText(/Retry this request/)).toBeVisible()
  })
})
