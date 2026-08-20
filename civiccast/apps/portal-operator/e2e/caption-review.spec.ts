import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const reviewA = {
  review_item_id: 'review-1',
  asset_id: 'council-2026-05-13',
  cue: {
    cue_id: 'cue-000001',
    start_seconds: 65.1,
    end_seconds: 68.9,
    text: 'motion carries',
    confidence: 0.62,
    low_confidence: true,
  },
  status: 'pending',
  original_text: 'motion carries',
  reviewed_text: null,
  low_confidence: true,
  reviewer_note: null,
  audio_evidence_available: true,
  created_at: '2026-05-13T18:00:00Z',
  updated_at: '2026-05-13T18:00:00Z',
}

const reviewB = {
  ...reviewA,
  review_item_id: 'review-2',
  asset_id: 'parks-2026-05-13',
  cue: { ...reviewA.cue, cue_id: 'cue-000002', text: 'parks board adjourned' },
  status: 'approved',
  original_text: 'parks board adjourned',
  reviewed_text: 'parks board adjourned',
  low_confidence: false,
}

type ReviewItem = typeof reviewA

// One mono 16-bit PCM sample at 16 kHz. The route below serves the bytes to
// Chromium; no media element methods are mocked.
const retainedWav = Buffer.from([
  0x52, 0x49, 0x46, 0x46, 0x26, 0x00, 0x00, 0x00, 0x57, 0x41, 0x56, 0x45,
  0x66, 0x6d, 0x74, 0x20, 0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
  0x80, 0x3e, 0x00, 0x00, 0x00, 0x7d, 0x00, 0x00, 0x02, 0x00, 0x10, 0x00,
  0x64, 0x61, 0x74, 0x61, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
])

async function mockReviewBackend(
  page: import('@playwright/test').Page,
  options: {
    items?: ReviewItem[]
    failList?: boolean
    delayList?: boolean
    approvalFailures?: number
    roles?: string[]
  } = {},
) {
  let items = options.items ?? [reviewA, reviewB]
  const roles = options.roles ?? ['records_clerk']
  let approvalFailuresRemaining = options.approvalFailures ?? 0
  const approvalBodies: unknown[] = []
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
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route('**/api/staff/captions/review-items', async (route) => {
    if (options.delayList) await new Promise((resolve) => setTimeout(resolve, 500))
    if (options.failList) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.' }),
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items) })
  })
  await page.route('**/api/staff/captions/review-items/*/approve', async (route) => {
    approvalBodies.push(route.request().postDataJSON())
    if (approvalFailuresRemaining > 0) {
      approvalFailuresRemaining -= 1
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Review write failed.' }),
      })
      return
    }
    const id = route.request().url().split('/review-items/')[1].split('/')[0]
    items = items.map((item) =>
      item.review_item_id === id
        ? { ...item, status: 'approved', reviewed_text: item.reviewed_text ?? item.original_text }
        : item,
    )
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items.find((item) => item.review_item_id === id)) })
  })
  await page.route('**/api/staff/captions/review-items/*/edit', async (route) => {
    const id = route.request().url().split('/review-items/')[1].split('/')[0]
    const body = route.request().postDataJSON() as { text: string }
    items = items.map((item) =>
      item.review_item_id === id
        ? { ...item, status: 'edited', reviewed_text: body.text, reviewer_note: 'Edited in operator console.' }
        : item,
    )
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items.find((item) => item.review_item_id === id)) })
  })
  await page.route('**/api/staff/captions/review-items/*/reject', async (route) => {
    const id = route.request().url().split('/review-items/')[1].split('/')[0]
    items = items.map((item) =>
      item.review_item_id === id ? { ...item, status: 'rejected', reviewed_text: null } : item,
    )
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(items.find((item) => item.review_item_id === id)) })
  })
  await page.route('**/api/staff/captions/review-items/*/clip', async (route) => {
    await route.fulfill({ status: 200, contentType: 'audio/wav', body: retainedWav })
  })

  return { approvalBodies }
}

async function openReview(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Review queue' }).click()
  await expect(page.getByRole('heading', { name: 'Review queue' })).toBeVisible()
}

async function playAndAcknowledgeEvidence(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Load review audio' }).click()
  const audio = page.getByLabel('Review audio for review-1')
  await expect.poll(() => audio.evaluate((element) => element.readyState)).toBeGreaterThanOrEqual(3)
  await page.getByLabel('I compared review-1 with its audio evidence').check()
}

test.describe('caption review queue', () => {
  test('renders pending caption review and supports approve/edit/reject', async ({ page }) => {
    await mockReviewBackend(page)
    await openReview(page)

    await expect(page.getByText('1 low-confidence cue needs reviewer attention.')).toBeVisible()
    await expect(page.getByLabel('Reviewed text for review-1')).toHaveValue('motion carries')

    await page.getByLabel('Reviewed text for review-1').fill('motion carries unanimously')
    await page.getByRole('button', { name: 'Save edit' }).click()
    await expect(page.getByText('Edited')).toBeVisible()

    await page.getByRole('tab', { name: 'Edited' }).click()
    await expect(page.getByText('motion carries unanimously')).toBeVisible()

    await playAndAcknowledgeEvidence(page)
    await page.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('tab', { name: 'Approved' }).click()
    await expect(page.getByLabel('Reviewed text for review-1')).toHaveValue('motion carries unanimously')

    await page
      .locator('article')
      .filter({ has: page.getByLabel('Reviewed text for review-1') })
      .getByRole('button', { name: 'Reject' })
      .click()
    await page.getByRole('tab', { name: 'Rejected' }).click()
    await expect(page.getByLabel('Reviewed text for review-1')).toHaveValue('motion carries')
  })

  test('loading state is visible', async ({ page }) => {
    await mockReviewBackend(page, { delayList: true })
    await page.goto('/')
    await page.getByRole('button', { name: 'Review queue' }).click()
    await expect(page.locator('.animate-pulse').first()).toBeVisible()
  })

  test('empty state is actionable', async ({ page }) => {
    await mockReviewBackend(page, { items: [] })
    await openReview(page)
    await expect(page.getByText('No caption cues need review.')).toBeVisible()
    await expect(page.getByText(/Next step: run a captioned recording/)).toBeVisible()
  })

  test('error state is actionable', async ({ page }) => {
    await mockReviewBackend(page, { failList: true })
    await openReview(page)
    await expect(page.getByText('Caption review backend unavailable.')).toBeVisible()
    await expect(page.getByText(/connected database/)).toBeVisible()
  })

  test('unavailable retained evidence blocks acknowledgement and approval', async ({ page }) => {
    await mockReviewBackend(page, { items: [{ ...reviewA, audio_evidence_available: false }] })
    await openReview(page)

    await expect(page.getByText('Audio evidence is unavailable. Approval of this low-confidence cue is blocked.')).toBeVisible()
    await expect(page.getByLabel('I compared review-1 with its audio evidence')).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  test('real WAV canplay sends acknowledgement and recovers from repeated failed approvals without stale evidence state', async ({ page }) => {
    const backend = await mockReviewBackend(page, { approvalFailures: 2 })
    await openReview(page)
    await playAndAcknowledgeEvidence(page)
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText('Review write failed.')).toBeVisible()

    // A failed mutation must not leave a checked acknowledgement or an enabled
    // approval action backed by audio state from the failed attempt.
    await expect(page.getByLabel('I compared review-1 with its audio evidence')).not.toBeChecked()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()

    // A repeat failure for this same row must create a fresh recovery state,
    // rather than reusing the acknowledgement from the first failed request.
    await playAndAcknowledgeEvidence(page)
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect.poll(() => backend.approvalBodies).toHaveLength(2)
    await expect(page.getByLabel('I compared review-1 with its audio evidence')).not.toBeChecked()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()

    await page.reload()
    await openReview(page)
    await playAndAcknowledgeEvidence(page)
    await page.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('tab', { name: 'Approved' }).click()
    await expect(page.getByLabel('Reviewed text for review-1')).toHaveValue('motion carries')
    expect(backend.approvalBodies).toEqual([
      expect.objectContaining({ low_confidence_acknowledged: true }),
      expect.objectContaining({ low_confidence_acknowledged: true }),
      expect.objectContaining({ low_confidence_acknowledged: true }),
    ])
  })

  test('search and keyboard tabs filter results', async ({ page }) => {
    await mockReviewBackend(page)
    await openReview(page)
    await page.getByRole('tab', { name: 'All' }).press('Enter')
    await page.getByLabel('Search caption review').fill('parks')
    await expect(page.getByLabel('Reviewed text for review-2')).toHaveValue('parks board adjourned')
    await expect(page.getByLabel('Reviewed text for review-1')).toBeHidden()
  })

  test('keeps caption review read-only without records clerk role', async ({ page }) => {
    await mockReviewBackend(page, { roles: ['meeting_operator'] })
    await openReview(page)

    await expect(page.getByText(/Caption review actions require the records clerk role/)).toBeVisible()
    await expect(page.getByLabel('Reviewed text for review-1')).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Approve' }).first()).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Reject' }).first()).toBeDisabled()
  })

  test('axe scan has no serious or critical violations', async ({ page }) => {
    await mockReviewBackend(page)
    await openReview(page)
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
        `axe-core found ${blockers.length} serious/critical violation(s) in caption review:\n\n${summary}`,
      )
    }
  })
})
