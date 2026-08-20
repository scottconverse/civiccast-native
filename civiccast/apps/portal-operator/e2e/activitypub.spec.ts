import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const PENDING_FOLLOWER = {
  actor: 'https://neighbor.example/users/alex',
  domain: 'neighbor.example',
  status: 'pending',
  activity_id: 'https://neighbor.example/users/alex/follows/civiccast',
  inbox_url: 'https://neighbor.example/users/alex/inbox',
  shared_inbox_url: 'https://neighbor.example/inbox',
  public_key_id: 'https://neighbor.example/users/alex#main-key',
  public_key_pem: '-----BEGIN PUBLIC KEY-----\\nmock\\n-----END PUBLIC KEY-----',
  created_at: '2026-05-21T18:40:00Z',
} as const

const ACCEPTED_FOLLOWER = {
  ...PENDING_FOLLOWER,
  actor: 'https://press.example/users/morgan',
  domain: 'press.example',
  status: 'accepted',
  activity_id: 'https://press.example/users/morgan/follows/civiccast',
  inbox_url: 'https://press.example/users/morgan/inbox',
  shared_inbox_url: null,
  public_key_id: 'https://press.example/users/morgan#main-key',
  created_at: '2026-05-21T18:30:00Z',
} as const

const ENABLED_STATUS = {
  enabled: true,
  mode: 'approval-only',
  handle: 'council',
  base_url: 'https://station.example.gov',
  actor_url: 'https://station.example.gov/ap/actor',
  authorized_fetch: true,
  blocked_instances: ['spam.example'],
  allowed_instances: ['neighbor.example'],
  followers: {
    pending: 1,
    accepted: 1,
    blocked: 0,
    rejected: 0,
    removed: 0,
  },
  outbox_items: 2,
  delivery_attempts: 2,
} as const

const OUTBOX = {
  outbox: [
    {
      activity_id: 'https://station.example.gov/ap/actor/accepts/abc123',
      activity: { type: 'Accept' },
      created_at: '2026-05-21T18:45:00Z',
    },
    {
      activity_id: 'https://station.example.gov/ap/actor/activities/create-council-2026-05-08',
      activity: { type: 'Create' },
      created_at: '2026-05-21T18:50:00Z',
    },
  ],
} as const

const DELIVERIES = {
  deliveries: [
    {
      delivery_id: 'apd_mock_1',
      activity_id: 'https://station.example.gov/ap/actor/accepts/abc123',
      inbox_url: 'https://neighbor.example/inbox',
      status_code: 202,
      response_body: 'accepted',
      created_at: '2026-05-21T18:45:02Z',
    },
  ],
} as const

async function mockActivityPub(
  page: import('@playwright/test').Page,
  status: Record<string, unknown> = ENABLED_STATUS,
) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'federation-admin',
        display_name: 'Federation Admin',
        roles: ['setup_admin'],
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
  await page.route('**/api/staff/activitypub/status', async (route) => {
    await route.fulfill({
      status: status === null ? 503 : 200,
      contentType: 'application/json',
      body:
        status === null
          ? JSON.stringify({ detail: 'ActivityPub store unavailable.' })
          : JSON.stringify(status),
    })
  })
  await page.route('**/api/staff/activitypub/followers?*', async (route) => {
    const url = new URL(route.request().url())
    const requested = url.searchParams.get('status')
    const followers =
      requested === 'accepted'
        ? [ACCEPTED_FOLLOWER]
        : requested === 'pending'
          ? [PENDING_FOLLOWER]
          : []
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ followers }),
    })
  })
  await page.route('**/api/staff/activitypub/outbox', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(OUTBOX),
    })
  })
  await page.route('**/api/staff/activitypub/deliveries*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DELIVERIES),
    })
  })
  await page.route('**/api/staff/activitypub/delivery-retries', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        delivery_retries: [
          {
            retry_id: 'apr-dead-1',
            activity_id: 'https://station.example/activities/publish-7',
            inbox_url: 'https://town.example/users/resident/inbox',
            activity: { type: 'Create' },
            state: 'dead_letter',
            attempts: 8,
            next_attempt_at: null,
            last_status_code: 503,
            last_error: 'remote error',
            created_at: '2026-06-10T12:00:00Z',
            updated_at: '2026-06-10T13:00:00Z',
          },
        ],
      }),
    })
  })
}

async function openFederation(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByLabel('Show System Health navigation').click()
  await page.getByRole('button', { name: 'Federation' }).click()
  await expect(page.getByRole('heading', { name: 'ActivityPub federation' })).toBeVisible()
}

test.describe('activitypub federation dashboard', () => {
  test('renders policy, follower moderation, outbox, and delivery evidence', async ({ page }) => {
    await mockActivityPub(page)
    await openFederation(page)

    await expect(page.getByLabel('Federation summary')).toContainText('approval-only')
    await expect(page.getByLabel('Federation policy')).toContainText('Signed fetch required')
    await expect(page.getByText('https://neighbor.example/users/alex', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Block' })).toBeVisible()
    await expect(page.getByText('Outbox evidence')).toBeVisible()
    await expect(page.getByText('Delivery attempts')).toBeVisible()
  })

  test('sends approve, reject, and block actions to the staff API', async ({ page }) => {
    const posted: Record<string, unknown>[] = []
    await mockActivityPub(page)
    for (const action of ['approve', 'reject', 'block']) {
      await page.route(`**/api/staff/activitypub/followers/${action}`, async (route) => {
        posted.push({ action, body: route.request().postDataJSON() })
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            follower: {
              ...PENDING_FOLLOWER,
              status:
                action === 'approve'
                  ? 'accepted'
                  : action === 'reject'
                    ? 'rejected'
                    : 'blocked',
            },
          }),
        })
      })
    }
    await openFederation(page)

    await page.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('button', { name: 'Reject' }).click()
    await page.getByRole('button', { name: 'Block' }).click()

    await expect.poll(() => posted.length).toBe(3)
    expect(posted.map((item) => item.action)).toEqual(['approve', 'reject', 'block'])
    expect(posted[0].body).toMatchObject({ actor: 'https://neighbor.example/users/alex' })
  })

  test('disabled state gives the operator a safe enablement path', async ({ page }) => {
    await mockActivityPub(page, {
      enabled: false,
      mode: 'disabled',
      handle: 'council',
      base_url: '',
      actor_url: null,
      authorized_fetch: false,
      blocked_instances: [],
      allowed_instances: [],
      followers: { pending: 0, accepted: 0, blocked: 0, rejected: 0, removed: 0 },
      outbox_items: 0,
      delivery_attempts: 0,
    })
    await openFederation(page)

    await expect(page.getByRole('heading', { name: 'Federation is off' })).toBeVisible()
    await expect(page.getByText('Default-safe')).toBeVisible()
    await expect(page.getByText('civiccast activitypub keygen')).toBeVisible()
  })

  test('error state gives a retry path', async ({ page }) => {
    await mockActivityPub(page, null as unknown as Record<string, unknown>)
    await openFederation(page)

    await expect(page.getByRole('alert')).toContainText('Could not load federation status.')
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  })

  test('axe scan: ActivityPub dashboard has no serious/critical violations', async ({ page }) => {
    await mockActivityPub(page)
    await openFederation(page)
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
        `axe-core found ${blockers.length} serious/critical violation(s) on the ActivityPub dashboard:\n\n${summary}`,
      )
    }
  })

  test('Beta B2: dead-lettered delivery can be replayed from the dashboard', async ({
    page,
  }) => {
    await mockActivityPub(page)
    let replayed: string | undefined
    await page.route('**/api/staff/activitypub/delivery-retries/*/replay', async (route) => {
      const url = new URL(route.request().url())
      replayed = url.pathname.split('/').at(-2)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          retry_id: 'apr-dead-1',
          activity_id: 'https://station.example/activities/publish-7',
          inbox_url: 'https://town.example/users/resident/inbox',
          activity: { type: 'Create' },
          state: 'pending',
          attempts: 0,
          next_attempt_at: '2026-06-10T14:00:00Z',
          last_status_code: 503,
          last_error: 'remote error',
          created_at: '2026-06-10T12:00:00Z',
          updated_at: '2026-06-10T14:00:00Z',
        }),
      })
    })
    await openFederation(page)

    const panel = page.getByRole('region', { name: 'Delivery retry queue' })
    await expect(panel.getByText('Dead letter', { exact: true })).toBeVisible()
    await expect(panel.getByText('attempt 8 · HTTP 503')).toBeVisible()

    await panel.getByRole('button', { name: 'Replay delivery' }).click()
    await expect.poll(() => replayed).toBe('apr-dead-1')
  })
})
