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
  // Every review-items URL the screen asked for, so a test can prove the
  // language filter is applied by the SERVER rather than in the browser.
  const listRequestUrls: string[] = []
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
  // Trailing * so the route still matches once the screen appends the
  // server-side language filter (?language=es). A single * does not cross a
  // '/', so this stays distinct from the /*/approve|edit|reject routes below.
  await page.route('**/api/staff/captions/review-items*', async (route) => {
    listRequestUrls.push(route.request().url())
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

  return { approvalBodies, listRequestUrls }
}

// The review queue has two tablists -- status and language -- so an unscoped
// getByRole('tab', { name }) is ambiguous ('All' also matches 'All languages').
// Scope every tab click to the tablist it belongs to, which both fixes the
// ambiguity and makes each step say which filter it means.
function statusTab(page: import('@playwright/test').Page, name: string) {
  return page
    .getByRole('tablist', { name: 'Caption review filter' })
    .getByRole('tab', { name })
}

function languageTab(page: import('@playwright/test').Page, name: string) {
  return page
    .getByRole('tablist', { name: 'Caption review language filter' })
    .getByRole('tab', { name })
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

    await statusTab(page, 'Edited').click()
    await expect(page.getByText('motion carries unanimously')).toBeVisible()

    await playAndAcknowledgeEvidence(page)
    await page.getByRole('button', { name: 'Approve' }).click()
    await statusTab(page, 'Approved').click()
    await expect(page.getByLabel('Reviewed text for review-1')).toHaveValue('motion carries unanimously')

    await page
      .locator('article')
      .filter({ has: page.getByLabel('Reviewed text for review-1') })
      .getByRole('button', { name: 'Reject' })
      .click()
    await statusTab(page, 'Rejected').click()
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
    await statusTab(page, 'Approved').click()
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
    await statusTab(page, 'All').press('Enter')
    await page.getByLabel('Search caption review').fill('parks')
    await expect(page.getByLabel('Reviewed text for review-2')).toHaveValue('parks board adjourned')
    await expect(page.getByLabel('Reviewed text for review-1')).toBeHidden()
  })

  test('the language filter is applied by the server, not the browser', async ({ page }) => {
    // A meeting's caption queue is one row per cue in TWO languages, so a long
    // session is thousands of rows; fetching them all to show one language was
    // work the API already knows how to avoid. This pins that clicking a
    // language tab actually narrows the REQUEST.
    const backend = await mockReviewBackend(page)
    await openReview(page)
    expect(backend.listRequestUrls.at(-1)).not.toContain('language=')

    await languageTab(page, 'Spanish').click()
    await expect
      .poll(() => backend.listRequestUrls.at(-1))
      .toContain('language=es')

    await languageTab(page, 'English').click()
    await expect
      .poll(() => backend.listRequestUrls.at(-1))
      .toContain('language=en')

    // Back to All: the language is part of the query key, so this is a cache
    // hit -- both rows return with NO new request at all. That is the point of
    // keying it rather than re-filtering a payload we should not have fetched.
    const requestsBeforeReturn = backend.listRequestUrls.length
    await languageTab(page, 'All languages').click()
    // review-1 is the pending row, which the default status filter shows.
    await expect(page.getByLabel('Reviewed text for review-1')).toBeVisible()
    expect(backend.listRequestUrls).toHaveLength(requestsBeforeReturn)
    // And the very first request -- the unfiltered one -- never sent the param.
    expect(backend.listRequestUrls[0]).not.toContain('language=')
  })

  test('the two filter tablists are distinguishable to assistive tech', async ({ page }) => {
    // Two tablists on one screen: an axe/screen-reader user must be able to
    // tell "All" (status) from "All languages" apart, and the active language
    // tab's count must not run into its name ("All languages2").
    await mockReviewBackend(page)
    await openReview(page)

    await expect(statusTab(page, 'All')).toHaveCount(1)
    await expect(languageTab(page, 'All languages')).toHaveCount(1)
    await expect(languageTab(page, 'All languages')).toHaveAccessibleName(
      'All languages, 2 shown',
    )
    await languageTab(page, 'Spanish').click()
    // Inactive tabs carry the bare label, with no count glued on.
    await expect(languageTab(page, 'All languages')).toHaveAccessibleName('All languages')
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
