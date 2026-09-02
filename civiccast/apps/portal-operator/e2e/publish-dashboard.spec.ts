import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const PENDING_SURFACES = [
  {
    id: 'portal',
    label: 'Resident Portal',
    kind: 'canonical',
    state: 'pending',
    approval: 'pending',
    required: true,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'Portal publish is waiting for operator approval.',
    next_step: 'Approve this surface to make the canonical portal URL public.',
    override_justification: null,
  },
  {
    id: 'internet-archive',
    label: 'Internet Archive',
    kind: 'archive',
    state: 'pending',
    approval: 'pending',
    required: true,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'Internet Archive upload is waiting for approval.',
    next_step: 'Approve or record a legal override before public-record completion.',
    override_justification: null,
  },
  {
    id: 'local-nas-rsync',
    label: 'Local NAS rsync',
    kind: 'archive',
    state: 'pending',
    approval: 'pending',
    required: true,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'Rsync copy and hash verification are waiting for approval.',
    next_step: 'Approve this data-in-motion archive path or record an override.',
    override_justification: null,
  },
  {
    id: 'local-nas-zfs',
    label: 'Local NAS ZFS',
    kind: 'archive',
    state: 'pending',
    approval: 'pending',
    required: true,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'ZFS storage proof is waiting for approval.',
    next_step: 'Approve this data-at-rest archive path or record an override.',
    override_justification: null,
  },
  {
    id: 'youtube-live',
    label: 'YouTube Live',
    kind: 'reach',
    state: 'pending',
    approval: 'pending',
    required: false,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'Live simulcast is waiting for approval.',
    next_step: 'Approve reach distribution when the platform credentials are healthy.',
    override_justification: null,
  },
  {
    id: 'youtube-vod',
    label: 'YouTube VOD',
    kind: 'reach',
    state: 'pending',
    approval: 'pending',
    required: false,
    url: null,
    path: null,
    verification_hash: null,
    last_attempt_at: null,
    completed_at: null,
    retry_count: 0,
    health: 'unknown',
    message: 'VOD upload is waiting for approval.',
    next_step: 'Approve reach distribution when the platform credentials are healthy.',
    override_justification: null,
  },
] as const

const APPROVED_SURFACES = PENDING_SURFACES.map((surface) => ({
  ...surface,
  state: 'succeeded',
  approval: 'approved',
  health: 'ok',
  completed_at: '2026-05-08T20:15:00Z',
  url:
    surface.id === 'internet-archive'
      ? 'https://archive.org/details/council-2026-05-08'
      : surface.id.startsWith('youtube')
        ? `https://youtube.example/${surface.id}`
        : surface.id === 'portal'
          ? 'https://cdn.example/council/playlist.m3u8'
          : null,
  path: surface.id.startsWith('local-nas') ? `/nas/council/${surface.id}` : null,
  verification_hash: surface.kind === 'archive' ? 'sha256:abc123' : null,
  message: `${surface.label} completed with deterministic mock proof.`,
  next_step: 'No action required.',
}))

const MOCK_DASHBOARD = {
  summary: {
    total_assets: 3,
    draft: 1,
    portal_live: 1,
    archive_verified: 1,
    degraded: 1,
    needs_operator_action: 1,
  },
  assets: [
    {
      asset_id: 'council-2026-05-08',
      title: 'Council - May 8, 2026',
      dashboard_state: 'draft',
      dashboard_label: 'Draft',
      canonical_public: false,
      archive_verified: false,
      reach_degraded: false,
      needs_operator_action: false,
      public_record_required: true,
      published_at: null,
      surfaces: PENDING_SURFACES,
    },
    {
      asset_id: 'board-2026-05-09',
      title: 'Board - May 9, 2026',
      dashboard_state: 'failed_needs_action',
      dashboard_label: 'Failed - needs action',
      canonical_public: true,
      archive_verified: false,
      reach_degraded: true,
      needs_operator_action: true,
      public_record_required: true,
      published_at: '2026-05-09T20:15:00Z',
      surfaces: [
        { ...PENDING_SURFACES[0], state: 'succeeded', approval: 'approved', health: 'ok' },
        { ...PENDING_SURFACES[1], state: 'failed', health: 'error' },
      ],
    },
    {
      asset_id: 'concert-archive',
      title: 'Concert archive',
      dashboard_state: 'complete',
      dashboard_label: 'Complete',
      canonical_public: true,
      archive_verified: true,
      reach_degraded: false,
      needs_operator_action: false,
      public_record_required: false,
      published_at: '2026-05-08T19:00:00Z',
      surfaces: APPROVED_SURFACES.slice(0, 1),
    },
  ],
} as const

async function mockDashboard(page: import('@playwright/test').Page, status = 200) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'operator-dashboard',
        operator_display_name: 'Operator dashboard',
        token_id: 'publish-e2e',
        scopes: ['publish_operator'],
        roles: ['publish_operator'],
      }),
    })
  })
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    })
  })
  await page.route('**/api/staff/publish/assets', async (route) => {
    await route.fulfill({
      status,
      contentType: 'application/json',
      body:
        status === 200
          ? JSON.stringify(MOCK_DASHBOARD)
          : JSON.stringify({
              detail: 'Durable storage is not ready. Open Setup and choose Prepare storage.',
            }),
    })
  })
  // WP-11 item 5: every AssetPanel now calls GET .../preflight. Default to a
  // ready portal check so the pre-existing assertions below (which don't
  // care about the readiness panel) see a clean state; the dedicated
  // readiness-panel tests further down override this per-test.
  await page.route('**/api/staff/publish/assets/*/preflight', async (route) => {
    const assetId = decodeURIComponent(
      new URL(route.request().url()).pathname.split('/').at(-2) ?? '',
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        asset_id: assetId,
        ready: true,
        checks: [
          {
            id: 'portal',
            label: 'Resident Portal',
            kind: 'canonical',
            required: true,
            health: 'ok',
            message: 'Portal manifest is packaged and ready.',
            next_step: 'Approve portal publication when review is complete.',
          },
        ],
      }),
    })
  })
}

async function openPublish(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Publish' }).click()
  await expect(page.getByRole('heading', { name: 'Publish dashboard' })).toBeVisible()
}

test.describe('publish dashboard', () => {
  test('renders v0.7 summary and per-platform approval controls', async ({ page }) => {
    await mockDashboard(page)
    await openPublish(page)

    await expect(page.getByLabel('Publish summary').getByText('Archive verified')).toBeVisible()
    await expect(page.getByText('Internet Archive', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Local NAS rsync', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Local NAS ZFS', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('YouTube Live', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('YouTube VOD', { exact: true }).first()).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Approve and Publish selected' }).first(),
    ).toBeVisible()
  })

  test('sends approved portal, IA, both NAS paths, and YouTube reach surfaces', async ({ page }) => {
    let postedBody: unknown
    await mockDashboard(page)
    await page.route('**/api/staff/publish/assets/council-2026-05-08/approve', async (route) => {
      postedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK_DASHBOARD.assets[0],
          dashboard_state: 'complete',
          dashboard_label: 'Complete',
          canonical_public: true,
          archive_verified: true,
          published_at: '2026-05-08T20:15:00Z',
          surfaces: APPROVED_SURFACES,
        }),
      })
    })
    await openPublish(page)

    await page.getByRole('button', { name: 'Approve and Publish selected' }).first().click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Approve and Publish' }).click()
    await expect.poll(() => postedBody).toBeTruthy()
    expect(postedBody).toMatchObject({
      approved_surface_ids: [
        'portal',
        'internet-archive',
        'local-nas-rsync',
        'local-nas-zfs',
        'youtube-live',
        'youtube-vod',
      ],
      operator_id: 'operator-dashboard',
      operator_display_name: 'Operator dashboard',
    })
  })

  test('requires a specific override justification before approving an archive override', async ({ page }) => {
    let postedBody: unknown
    await mockDashboard(page)
    await page.route('**/api/staff/publish/assets/council-2026-05-08/approve', async (route) => {
      postedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_DASHBOARD.assets[0]),
      })
    })
    await openPublish(page)

    await page.getByLabel('Use audit-logged archive override for this platform').first().check()
    await expect(page.getByText('Each override needs a specific approval record')).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Approve and Publish selected' }).first(),
    ).toBeDisabled()

    await page
      .getByLabel('Override justification for Internet Archive')
      .fill('Town clerk approval CC-2026-05-08-IA while credentials are repaired.')
    await page.getByRole('button', { name: 'Approve and Publish selected' }).first().click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Approve and Publish' }).click()
    await expect.poll(() => postedBody).toBeTruthy()
    expect(postedBody).toMatchObject({
      overrides: [
        {
          surface_id: 'internet-archive',
          justification: 'Town clerk approval CC-2026-05-08-IA while credentials are repaired.',
        },
      ],
    })
  })

  test('retries a failed surface without approving unrelated targets', async ({ page }) => {
    let postedBody: unknown
    await mockDashboard(page)
    await page.route(
      '**/api/staff/publish/assets/board-2026-05-09/surfaces/internet-archive/retry',
      async (route) => {
        postedBody = route.request().postDataJSON()
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...MOCK_DASHBOARD.assets[1],
            dashboard_state: 'archive_pending',
            dashboard_label: 'Archive pending',
            surfaces: [
              MOCK_DASHBOARD.assets[1].surfaces[0],
              {
                ...MOCK_DASHBOARD.assets[1].surfaces[1],
                state: 'succeeded',
                approval: 'approved',
                health: 'ok',
                retry_count: 1,
              },
            ],
          }),
        })
      },
    )
    await openPublish(page)
    await page.getByRole('tab', { name: 'Needs action' }).click()

    await page.getByRole('button', { name: 'Retry this surface' }).click()
    await expect.poll(() => postedBody).toBeTruthy()
    expect(postedBody).toMatchObject({
      operator_id: 'operator-dashboard',
      operator_display_name: 'Operator dashboard',
    })
  })

  test('filters to assets that need action', async ({ page }) => {
    await mockDashboard(page)
    await openPublish(page)

    await page.getByRole('tab', { name: 'Needs action' }).click()
    await expect(page.getByText('Board - May 9, 2026')).toBeVisible()
    await expect(page.getByText('Council - May 8, 2026')).toBeHidden()
    await expect(page.getByText('Concert archive')).toBeHidden()
  })

  test('error state gives a database fix path', async ({ page }) => {
    await mockDashboard(page, 503)
    await openPublish(page)

    await expect(page.getByRole('alert')).toContainText('Publish dashboard needs a database.')
    await expect(page.getByRole('alert')).toContainText('connect the CivicCast database')
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  })

  // WP-11 item 5: a per-surface readiness panel reads GET .../preflight
  // before approval, and Approve stays disabled while a selected real
  // surface reads not-ready.
  test('readiness panel blocks Approve on a not-ready selected surface, with the API safe next-action text', async ({
    page,
  }) => {
    await mockDashboard(page)
    await page.route(
      '**/api/staff/publish/assets/council-2026-05-08/preflight',
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            asset_id: 'council-2026-05-08',
            ready: false,
            checks: [
              {
                id: 'portal',
                label: 'Resident Portal',
                kind: 'canonical',
                required: true,
                health: 'error',
                credential_reference: 'CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real',
                message: 'Portal cannot publish: DATABASE_URL is not configured.',
                next_step:
                  'Fix the CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real configuration, then rerun preflight.',
              },
            ],
          }),
        })
      },
    )
    await openPublish(page)

    const councilPanel = page
      .locator('article')
      .filter({ hasText: 'Council - May 8, 2026' })
    await expect(councilPanel.getByText('Readiness check')).toBeVisible()
    await expect(councilPanel.getByText('Not ready')).toBeVisible()
    await expect(
      councilPanel.getByText('Portal cannot publish: DATABASE_URL is not configured.'),
    ).toBeVisible()
    await expect(
      councilPanel.getByRole('button', { name: 'Approve and Publish selected' }),
    ).toBeDisabled()
  })

  test('axe scan: publish dashboard has no serious/critical violations', async ({ page }) => {
    await mockDashboard(page)
    await openPublish(page)
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
        `axe-core found ${blockers.length} serious/critical violation(s) on the publish dashboard:\n\n${summary}`,
      )
    }
  })
})
