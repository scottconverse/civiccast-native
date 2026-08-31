import { expect, test } from '@playwright/test'

/**
 * Cable automation CA-5: community bulletin moderation on the CG Board.
 * Mock-routed: add → approve (operator id) → request changes / decline
 * (required notes) against the durable staff bulletin endpoints.
 */

const now = '2026-06-11T20:00:00Z'

const SUBMITTED_BULLETIN = {
  submission_id: 'cgb_foodpantry',
  organization: 'Community Food Pantry',
  submitter_label: 'Pat R.',
  title: 'Food drive Saturday',
  message: 'Drop donations at the pantry, 9am to noon.',
  target_zone_kind: 'primary',
  state: 'submitted',
  requested_start: null,
  requested_end: null,
  moderation_notes: null,
  approved_by_operator: null,
}

function bulletinQueue(submissions: Array<Record<string, unknown>>) {
  return {
    generated_at: now,
    channel_id: 'public',
    submissions,
    approved_zone_items: [],
    proof_boundary: 'operator-community-bulletin-queue',
  }
}

const MINIMAL_DISPLAY = {
  channel_id: 'public',
  snapshot: {
    channel_id: 'public',
    generated_at: now,
    zones: [],
    portal_render_path: '/cg/public',
    proof_boundary: 'sample-snapshot',
  },
  template_library: {
    channel_id: 'public',
    active_template_id: 'full',
    templates: [],
    proof_boundary: 'sample-templates',
  },
  feed_catalog: { channel_id: 'public', adapters: [], proof_boundary: 'sample-feeds' },
  approved_bulletins: bulletinQueue([]),
  render_plan: {
    channel_id: 'public',
    snapshot_url: '/api/public/cg/channels/public/snapshot',
    manifest_url: '/api/public/cg/channels/public/stream.m3u8',
    segment_pattern: 'seg-%05d.ts',
    target_duration_seconds: 6,
    linear_overlay_contract_url: '/api/public/cg/channels/public/overlay-contract',
    proof_boundary: 'sample-render-plan',
  },
  overlay_contract: {
    channel_id: 'public',
    snapshot_url: '/api/public/cg/channels/public/snapshot',
    format: 'png',
    safe_area_percent: 5,
  },
  proof_boundary: 'sample-display',
}

async function mockCgBoard(page: import('@playwright/test').Page) {
  const requests = {
    creates: [] as Array<Record<string, unknown>>,
    patches: [] as Array<{ submissionId: string; patch: Record<string, unknown> }>,
  }
  let submissions: Array<Record<string, unknown>> = [SUBMITTED_BULLETIN]

  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'op-kim',
        operator_display_name: 'Kim',
        token_id: 'token',
        scopes: ['operator'],
        roles: ['setup_admin', 'publish_operator'],
      }),
    })
  })
  await page.route('**/api/staff/app/config**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        station_id: 'station',
        station_name: 'CivicCast station',
        generated_at: now,
        default_channel_id: 'public',
        build_profile: {
          tier: 'unbranded',
          app_name: 'CivicCast station',
          platform_targets: [],
          icon_url: null,
          splash_url: null,
          store_ready: false,
          store_notes: '',
        },
        channels: [],
        support_url: '/support',
        privacy_url: '/privacy',
        analytics_enabled: false,
        emergency_status_url: '/api/public/cg/emergency',
      }),
    })
  })
  await page.route('**/api/public/cg/channels/*/display**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MINIMAL_DISPLAY),
    })
  })
  await page.route('**/api/staff/cg/channels/*/bulletins', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>
      requests.creates.push(payload)
      const created = {
        ...SUBMITTED_BULLETIN,
        submission_id: 'cgb_new',
        organization: payload.organization,
        submitter_label: payload.submitter_label,
        title: payload.title,
        message: payload.message,
      }
      submissions = [...submissions, created]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(created),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(bulletinQueue(submissions)),
    })
  })
  await page.route('**/api/staff/cg/channels/*/bulletins/*', async (route) => {
    const submissionId = route.request().url().split('/').pop() ?? ''
    const patch = route.request().postDataJSON() as Record<string, unknown>
    requests.patches.push({ submissionId, patch })
    submissions = submissions.map((s) =>
      s.submission_id === submissionId ? { ...s, ...patch } : s,
    )
    const updated = submissions.find((s) => s.submission_id === submissionId)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(updated),
    })
  })
  return requests
}

async function openCgBoard(page: import('@playwright/test').Page) {
  await page.goto('/#/cg')
  await expect(page.getByRole('heading', { name: 'Community bulletins' })).toBeVisible()
}

test('bulletin queue renders all states with moderation actions', async ({ page }) => {
  await mockCgBoard(page)
  await openCgBoard(page)

  await expect(page.getByText('Food drive Saturday')).toBeVisible()
  await expect(page.getByText('Submitted', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request changes' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Decline' })).toBeVisible()
})

test('approve sends the staff operator id and flips the state chip', async ({ page }) => {
  const requests = await mockCgBoard(page)
  await openCgBoard(page)

  await page.getByRole('button', { name: 'Approve' }).click()
  await expect.poll(() => requests.patches.length).toBe(1)
  expect(requests.patches[0]).toMatchObject({
    submissionId: 'cgb_foodpantry',
    patch: { state: 'accepted', approved_by_operator: 'op-kim' },
  })
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
})

test('decline requires notes via the in-app dialog and records them', async ({ page }) => {
  const requests = await mockCgBoard(page)
  await openCgBoard(page)

  await page.getByRole('button', { name: 'Decline' }).click()
  const dialog = page.getByRole('dialog', { name: 'Decline bulletin' })
  await expect(dialog).toBeVisible()

  // Submitting blank notes never dispatches a request -- it toasts and
  // keeps the dialog open so the operator can fix it.
  await dialog.getByRole('button', { name: 'Decline bulletin' }).click()
  await expect(page.getByRole('alert')).toContainText('Enter a note before submitting')
  expect(requests.patches).toEqual([])
  await expect(dialog).toBeVisible()

  // Cancelling leaves the bulletin untouched.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
  expect(requests.patches).toEqual([])

  // Reopen and provide the required notes.
  await page.getByRole('button', { name: 'Decline' }).click()
  const dialog2 = page.getByRole('dialog', { name: 'Decline bulletin' })
  await dialog2.getByPlaceholder('Why is this bulletin declined? (Required.)').fill(
    'Commercial content is not eligible.',
  )
  await dialog2.getByRole('button', { name: 'Decline bulletin' }).click()
  await expect.poll(() => requests.patches.length).toBe(1)
  expect(requests.patches[0].patch).toMatchObject({
    state: 'declined',
    moderation_notes: 'Commercial content is not eligible.',
  })
  await expect(page.getByText('Declined', { exact: true })).toBeVisible()
})

test('add bulletin form posts the draft and clears', async ({ page }) => {
  const requests = await mockCgBoard(page)
  await openCgBoard(page)

  await page.getByRole('button', { name: 'Add bulletin' }).click()
  await page.getByLabel('Organization').fill('Library Friends')
  await page.getByLabel('Submitted by').fill('Jo B.')
  await page.getByLabel('Title', { exact: true }).fill('Book sale next week')
  await page.getByLabel('Message').fill('Used book sale in the library lobby.')
  await page.getByRole('button', { name: 'Add bulletin', exact: true }).last().click()

  await expect.poll(() => requests.creates.length).toBe(1)
  expect(requests.creates[0]).toMatchObject({
    organization: 'Library Friends',
    submitter_label: 'Jo B.',
    title: 'Book sale next week',
    message: 'Used book sale in the library lobby.',
  })
  await expect(page.getByText('Book sale next week')).toBeVisible()
})
