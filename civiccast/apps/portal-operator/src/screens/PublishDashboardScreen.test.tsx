import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { StaffIdentityResponse } from '../types/api.generated'
import type {
  PublishDashboardResponse,
  PublishPreflightResponse,
  PublishSurfaceState,
} from '../types/publish'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  approvePublishAsset: vi.fn(),
  getPublishPreflight: vi.fn(),
  getStaffIdentity: vi.fn(),
  listPublishAssets: vi.fn(),
  retryPublishSurface: vi.fn(),
}))

import {
  ApiError,
  approvePublishAsset,
  getPublishPreflight,
  getStaffIdentity,
  listPublishAssets,
  retryPublishSurface,
} from '../api/client'
import { PublishDashboardScreen } from './PublishDashboardScreen'

afterEach(cleanup)

function dashboard(
  state: PublishSurfaceState,
  options: { simulated?: boolean } = {},
): PublishDashboardResponse {
  return {
    summary: {
      total_assets: 1,
      draft: 1,
      portal_live: 0,
      archive_verified: 0,
      degraded: 0,
      needs_operator_action: state === 'blocked' ? 1 : 0,
    },
    assets: [
      {
        asset_id: 'sample-asset',
        title: 'Sample asset',
        dashboard_state: state === 'blocked' ? 'preflight_blocked' : 'draft',
        dashboard_label: state === 'blocked' ? 'Preflight blocked' : 'Draft',
        canonical_public: false,
        archive_verified: false,
        reach_degraded: false,
        needs_operator_action: state === 'blocked',
        public_record_required: true,
        published_at: null,
        surfaces: [
          {
            id: 'portal',
            label: 'Portal',
            kind: 'canonical',
            state,
            approval: 'pending',
            required: true,
            url: null,
            last_attempt_at: null,
            completed_at: null,
            health: state === 'blocked' ? 'error' : 'unknown',
            message: state === 'blocked' ? 'The portal cannot publish this asset.' : 'Ready.',
            next_step: state === 'blocked' ? 'Package the recording first.' : 'Approve publish.',
            simulated: options.simulated,
          },
        ],
      },
    ],
  }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PublishDashboardScreen />
    </QueryClientProvider>,
  )
}

// Reused by both the WP-11 item 4 (podcast future card) and item 5
// (readiness panel) suites: an asset with a real approvable Portal surface
// plus the podcast future surface, so preflight tests can exercise a
// "future" check alongside a "real" one on the same asset.
function podcastDashboard(
  podcastOverrides: { state?: PublishSurfaceState; health?: 'ok' | 'warning' | 'error' | 'unknown' } = {},
): PublishDashboardResponse {
  return {
    summary: {
      total_assets: 1,
      draft: 1,
      portal_live: 0,
      archive_verified: 0,
      degraded: 0,
      needs_operator_action: 0,
    },
    assets: [
      {
        asset_id: 'sample-asset',
        title: 'Sample asset',
        dashboard_state: 'draft',
        dashboard_label: 'Draft',
        canonical_public: false,
        archive_verified: false,
        reach_degraded: false,
        needs_operator_action: false,
        public_record_required: true,
        published_at: null,
        surfaces: [
          {
            id: 'portal',
            label: 'Portal',
            kind: 'canonical',
            state: 'pending',
            approval: 'pending',
            required: true,
            url: null,
            last_attempt_at: null,
            completed_at: null,
            health: 'unknown',
            message: 'Ready.',
            next_step: 'Approve publish.',
          },
          {
            id: 'podcast',
            label: 'Podcast episode',
            kind: 'audience',
            state: podcastOverrides.state ?? 'pending',
            approval: 'pending',
            required: false,
            url: null,
            last_attempt_at: null,
            completed_at: null,
            health: podcastOverrides.health ?? 'unknown',
            message: 'Podcast RSS is an audience surface generated after operator approval.',
            next_step: 'Approve podcast generation or leave it pending for later audio review.',
          },
        ],
      },
    ],
  }
}

// Owner decision 2026-09-02 (companion to the podcast future card above):
// an asset with a real approvable Portal surface plus the
// subscriber-notifications future surface, so the same neutral-card /
// no-checkbox / never-red / excluded-from-approval behavior can be tested
// for the surface civiccast/publish/service.py's approve_publish now marks
// state="coming_soon" instead of the old fabricated "succeeded".
function subscriberNotificationsDashboard(
  overrides: { state?: PublishSurfaceState; health?: 'ok' | 'warning' | 'error' | 'unknown' } = {},
): PublishDashboardResponse {
  return {
    summary: {
      total_assets: 1,
      draft: 1,
      portal_live: 0,
      archive_verified: 0,
      degraded: 0,
      needs_operator_action: 0,
    },
    assets: [
      {
        asset_id: 'sample-asset',
        title: 'Sample asset',
        dashboard_state: 'draft',
        dashboard_label: 'Draft',
        canonical_public: false,
        archive_verified: false,
        reach_degraded: false,
        needs_operator_action: false,
        public_record_required: true,
        published_at: null,
        surfaces: [
          {
            id: 'portal',
            label: 'Portal',
            kind: 'canonical',
            state: 'pending',
            approval: 'pending',
            required: true,
            url: null,
            last_attempt_at: null,
            completed_at: null,
            health: 'unknown',
            message: 'Ready.',
            next_step: 'Approve publish.',
          },
          {
            id: 'subscriber-notifications',
            label: 'Subscriber notifications',
            kind: 'audience',
            state: overrides.state ?? 'pending',
            approval: 'pending',
            required: false,
            url: null,
            last_attempt_at: null,
            completed_at: null,
            health: overrides.health ?? 'unknown',
            message:
              'Subscriber notifications are coming in a future release. No emails or webhooks are sent yet.',
            next_step: 'No action needed. This surface is not selectable for real delivery yet.',
          },
        ],
      },
    ],
  }
}

function preflight(
  checks: PublishPreflightResponse['checks'],
  assetId = 'sample-asset',
): PublishPreflightResponse {
  return {
    asset_id: assetId,
    ready: checks.every((check) => check.health === 'ok' || !check.required),
    checks,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue({
    operator_id: 'dana',
    operator_display_name: 'Dana',
    roles: ['publish_operator'],
  } as StaffIdentityResponse)
  // Default: every surface reads ready, so pre-existing tests that don't
  // care about WP-11 item 5's readiness panel see a clean state.
  vi.mocked(getPublishPreflight).mockImplementation(async (assetId: string) =>
    preflight(
      [
        {
          id: 'portal',
          label: 'Portal',
          kind: 'canonical',
          required: true,
          health: 'ok',
          message: 'Portal manifest is packaged and ready.',
          next_step: 'Approve portal publication when review is complete.',
        },
      ],
      assetId,
    ),
  )
})

describe('PublishDashboardScreen safety feedback', () => {
  it('disables approval while a selected surface is blocked', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('blocked'))
    const { findByRole, findByText } = renderScreen()

    const publish = await findByRole('button', { name: 'Approve and Publish selected' })

    expect(publish.hasAttribute('disabled')).toBe(true)
    expect(await findByText(/selected surface is blocked/i)).toBeTruthy()
  })

  it('shows the exact safe API detail when publication fails', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('pending'))
    vi.mocked(approvePublishAsset).mockRejectedValue(
      new ApiError(
        'Conflict',
        409,
        'Publish preflight blocked: package the recording before approving Portal.',
      ),
    )
    const { findByRole, findByText } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    // The confirmation dialog stands between the button and the API call.
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() => expect(approvePublishAsset).toHaveBeenCalled())
    expect(
      await findByText(
        /Publish preflight blocked: package the recording before approving Portal/i,
      ),
    ).toBeTruthy()
  })

  it('does not publish until the operator confirms the dialog', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('pending'))
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))

    // The dialog is open, naming the consequence — and nothing has fired yet.
    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain('Publish "Sample asset" to residents?')
    expect(approvePublishAsset).not.toHaveBeenCalled()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))
    await waitFor(() => expect(approvePublishAsset).toHaveBeenCalledTimes(1))
  })

  it('publishes nothing when the operator cancels the dialog', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('pending'))
    const { findByRole, queryByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    fireEvent.click(await findByRole('button', { name: 'Cancel' }))

    expect(queryByRole('alertdialog')).toBeNull()
    expect(approvePublishAsset).not.toHaveBeenCalled()
  })

  it('shows the exact safe API detail when a surface retry fails', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('failed'))
    vi.mocked(retryPublishSurface).mockRejectedValue(
      new ApiError(
        'Conflict',
        409,
        'Internet Archive credentials are not configured.',
      ),
    )
    const { findByRole, findByText } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Retry this surface' }))

    await waitFor(() => expect(retryPublishSurface).toHaveBeenCalled())
    expect(
      await findByText(/Internet Archive credentials are not configured/i),
    ).toBeTruthy()
  })

  it('shows the simulated-archive warning when a surface is simulated', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      dashboard('succeeded', { simulated: true }),
    )
    const { findByText } = renderScreen()

    expect(await findByText(/nothing was actually archived/i)).toBeTruthy()
  })

  it('does not show the simulated-archive warning for a real surface', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('succeeded'))
    const { findByText, queryByText } = renderScreen()

    await findByText('Sample asset')
    expect(queryByText(/nothing was actually archived/i)).toBeNull()
  })

  it('tells the operator, before they click, that approving the portal surface starts caption transcription (candidate #17 finding 5)', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('pending'))
    const { findByText } = renderScreen()

    expect(
      await findByText(/also starts offline caption transcription for this recording automatically/i),
    ).toBeTruthy()
    expect(await findByText(/Offline caption jobs panel/i)).toBeTruthy()
  })

  it('does not show the caption-trigger note once nothing is left to approve', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(dashboard('succeeded'))
    const { findByText, queryByText } = renderScreen()

    await findByText('Sample asset')
    expect(queryByText(/starts offline caption transcription/i)).toBeNull()
  })
})

describe('PublishDashboardScreen state vocabulary', () => {
  function reachDegradedDashboard(): PublishDashboardResponse {
    return {
      summary: {
        total_assets: 1,
        draft: 0,
        portal_live: 1,
        archive_verified: 0,
        degraded: 1,
        needs_operator_action: 0,
      },
      assets: [
        {
          asset_id: 'reach-degraded-asset',
          title: 'Council - degraded reach',
          // Underscore-bearing dashboard_state, per TEST-2: no existing
          // fixture in this file ever set a state with an underscore, so the
          // stateLabel(surface.state) render at line 62 had no regression
          // coverage. dashboard_label is the backend's OLD hand-written
          // copy -- the guide's own forbidden word -- kept here to prove the
          // screen no longer reads it.
          dashboard_state: 'reach_degraded',
          dashboard_label: 'Reach degraded',
          canonical_public: true,
          archive_verified: false,
          reach_degraded: true,
          needs_operator_action: false,
          public_record_required: true,
          published_at: '2026-06-01T12:00:00Z',
          surfaces: [
            {
              id: 'portal',
              label: 'Portal',
              kind: 'canonical',
              state: 'succeeded',
              approval: 'approved',
              required: true,
              url: 'https://portal.example/c',
              last_attempt_at: null,
              completed_at: '2026-06-01T12:00:00Z',
              health: 'ok',
              message: 'Published.',
              next_step: 'None.',
            },
          ],
        },
      ],
    }
  }

  it('shows the shared vocabulary phrase for a reach-degraded asset, never the raw label or the guide\'s forbidden word', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(reachDegradedDashboard())
    const { findByText, queryByText } = renderScreen()

    expect(await findByText('Reaching fewer places than planned')).toBeTruthy()
    expect(queryByText('Reach degraded')).toBeNull()
    expect(queryByText(/degraded/i)).toBeNull()
  })

  it('derives the "Reach degraded" filter chip label from the same shared vocabulary as the pill', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(reachDegradedDashboard())
    const { findByRole } = renderScreen()

    // Same phrase, same source: if the chip label ever drifts back to its
    // own hardcoded string, this stops matching even though the pill (tested
    // above) still passes.
    expect(
      await findByRole('tab', { name: 'Reaching fewer places than planned' }),
    ).toBeTruthy()
  })

  function neverConfiguredCableDashboard(): PublishDashboardResponse {
    return {
      summary: {
        total_assets: 1,
        draft: 0,
        portal_live: 1,
        archive_verified: 0,
        degraded: 0,
        needs_operator_action: 0,
      },
      assets: [
        {
          asset_id: 'portal-only-asset',
          title: 'Council - portal only',
          dashboard_state: 'portal_live',
          dashboard_label: 'Live on the portal',
          canonical_public: true,
          archive_verified: false,
          reach_degraded: false,
          needs_operator_action: false,
          public_record_required: true,
          published_at: '2026-06-01T12:00:00Z',
          surfaces: [
            {
              id: 'portal',
              label: 'Portal',
              kind: 'canonical',
              state: 'succeeded',
              approval: 'approved',
              required: true,
              url: 'https://portal.example/c',
              last_attempt_at: null,
              completed_at: '2026-06-01T12:00:00Z',
              health: 'ok',
              message: 'Published.',
              next_step: 'None.',
            },
            {
              id: 'cable-file-package',
              label: 'Cable file package',
              kind: 'record',
              // Field evidence (candidate #17): this surface used to be
              // "failed" (red) even when it was simply never configured.
              state: 'not_configured',
              approval: 'approved',
              required: false,
              url: null,
              last_attempt_at: null,
              completed_at: '2026-06-01T12:00:00Z',
              health: 'unknown',
              message: 'Cable file package is not set up (optional).',
              next_step: 'Cable file package was never set up for this station.',
            },
          ],
        },
      ],
    }
  }

  it('shows a never-configured optional surface as "Not set up yet", never "Failed"', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(neverConfiguredCableDashboard())
    const { findByText, queryByText } = renderScreen()

    expect(await findByText(/record.*Not set up yet/i)).toBeTruthy()
    expect(queryByText(/record.*Failed/i)).toBeNull()
    expect(await findByText('Cable file package is not set up (optional).')).toBeTruthy()
  })
})

// WP-11 item 4 (owner decision 2026-09-02). The dashboard listing's own
// build_initial_surfaces() gives the podcast row state="pending",
// health="unknown" -- exactly what a normal, selectable, approvable surface
// looks like. Left alone that renders a checked "Approve this surface" box
// the operator's "Approve and Publish selected" click would submit, which
// the backend's real approve_publish() podcast branch currently answers
// with a fabricated https://portal.example/... "success" URL. The frontend
// fix is to always special-case this surface into a neutral, non-selectable
// card, regardless of what state/health this particular listing row
// happens to carry.
describe('PublishDashboardScreen podcast future-release card (WP-11 item 4)', () => {
  it('shows the podcast surface as a neutral future-release card with the API-aligned message', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    const { findByText } = renderScreen()

    expect(await findByText('Coming in a future release')).toBeTruthy()
    expect(
      await findByText('Podcast is not available yet; it is coming in a future release.'),
    ).toBeTruthy()
  })

  it('never renders an "Approve this surface" checkbox for podcast', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    const { findByText, queryAllByLabelText } = renderScreen()

    await findByText('Podcast episode')
    // Only the Portal surface's checkbox should exist -- podcast never gets
    // one, so approving the asset can never silently include it.
    expect(queryAllByLabelText(/Approve this surface/i)).toHaveLength(1)
  })

  it('never renders podcast in error red, even if a future backend change reports it as failed/error', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      podcastDashboard({ state: 'failed', health: 'error' }),
    )
    const { findByText, queryByText } = renderScreen()

    // Still the neutral future-release framing, not a red "Failed" state or
    // a "Retry this surface" button.
    expect(await findByText('Coming in a future release')).toBeTruthy()
    expect(
      await findByText('Podcast is not available yet; it is coming in a future release.'),
    ).toBeTruthy()
    expect(queryByText('Retry this surface')).toBeNull()
  })

  it('excludes podcast from the pre-checked/submittable surface set so approval can never report a fake podcast success', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() =>
      expect(approvePublishAsset).toHaveBeenCalledWith(
        'sample-asset',
        expect.objectContaining({ approved_surface_ids: ['portal'] }),
      ),
    )
  })
})

// Owner decision 2026-09-02: real subscriber notification sends (mail/
// webhook fan-out on publish) are deferred to a future release. Modeled
// exactly on the podcast future-release card above -- this surface must
// never render as a green "succeeded" checkbox an operator could select and
// submit, since civiccast/publish/service.py's approve_publish no longer
// sends anything for it (it used to build a NotificationPayload nobody ever
// dispatched and still mark the row "succeeded").
describe('PublishDashboardScreen subscriber-notifications future-release card', () => {
  it('shows the subscriber-notifications surface as a neutral future-release card with the honest message', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(subscriberNotificationsDashboard())
    const { findByText } = renderScreen()

    expect(await findByText('Coming in a future release')).toBeTruthy()
    expect(
      await findByText(
        'Subscriber notifications are coming in a future release. No emails or webhooks are sent yet.',
      ),
    ).toBeTruthy()
  })

  it('never renders an "Approve this surface" checkbox for subscriber notifications', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(subscriberNotificationsDashboard())
    const { findByText, queryAllByLabelText } = renderScreen()

    await findByText('Subscriber notifications')
    // Only the Portal surface's checkbox should exist -- subscriber
    // notifications never gets one, so approving the asset can never
    // silently include it.
    expect(queryAllByLabelText(/Approve this surface/i)).toHaveLength(1)
  })

  it('never renders subscriber notifications as succeeded/green, even if a future backend change reports it that way', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberNotificationsDashboard({ state: 'succeeded', health: 'ok' }),
    )
    const { findByText, queryByText } = renderScreen()

    // Still the neutral future-release framing, never the state pinned by
    // the old bug this replaces.
    expect(await findByText('Coming in a future release')).toBeTruthy()
    expect(
      await findByText(
        'Subscriber notifications are coming in a future release. No emails or webhooks are sent yet.',
      ),
    ).toBeTruthy()
    expect(queryByText('Retry this surface')).toBeNull()
  })

  it('excludes subscriber notifications from the pre-checked/submittable surface set so approval can never report a fake send', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(subscriberNotificationsDashboard())
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findByRole } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() =>
      expect(approvePublishAsset).toHaveBeenCalledWith(
        'sample-asset',
        expect.objectContaining({ approved_surface_ids: ['portal'] }),
      ),
    )
  })
})

// WP-11 item 5 (gap found in review of #129): the operator Publish screen
// never called GET .../preflight before this. These tests cover the four
// states a real preflight fetch can produce: ready, not-ready (with the
// API's own safe next-action text), future (podcast, never red), and a load
// error with retry -- plus that "Approve and Publish selected" stays
// disabled while a SELECTED real surface reads not-ready.
describe('PublishDashboardScreen publish preflight panel', () => {
  it('shows a ready surface with its API message', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(getPublishPreflight).mockResolvedValue(
      preflight([
        {
          id: 'portal',
          label: 'Portal',
          kind: 'canonical',
          required: true,
          health: 'ok',
          message: 'Portal manifest is packaged and ready.',
          next_step: 'Approve portal publication when review is complete.',
        },
      ]),
    )
    const { findByText, findByRole } = renderScreen()

    expect(await findByText('Readiness check')).toBeTruthy()
    expect(await findByText('Ready')).toBeTruthy()
    expect(await findByText('Portal manifest is packaged and ready.')).toBeTruthy()
    expect(
      await findByText('Approve portal publication when review is complete.'),
    ).toBeTruthy()

    const publish = await findByRole('button', { name: 'Approve and Publish selected' })
    expect(publish.hasAttribute('disabled')).toBe(false)
  })

  it('shows a not-ready surface with the API safe next-action text and disables Approve', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(getPublishPreflight).mockResolvedValue(
      preflight([
        {
          id: 'portal',
          label: 'Portal',
          kind: 'canonical',
          required: true,
          health: 'error',
          credential_reference: 'CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real',
          message: 'Portal cannot publish: DATABASE_URL is not configured.',
          next_step: 'Fix the CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real configuration, then rerun preflight.',
        },
      ]),
    )
    const { findByText, findByRole } = renderScreen()

    expect(await findByText('Not ready')).toBeTruthy()
    expect(
      await findByText('Portal cannot publish: DATABASE_URL is not configured.'),
    ).toBeTruthy()
    expect(
      await findByText(
        'Fix the CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real configuration, then rerun preflight.',
      ),
    ).toBeTruthy()

    const publish = await findByRole('button', { name: 'Approve and Publish selected' })
    await waitFor(() => expect(publish.hasAttribute('disabled')).toBe(true))
    expect(
      await findByText(/failed its readiness check.*DATABASE_URL is not configured/i),
    ).toBeTruthy()
  })

  it('shows the podcast surface as "Future release", never "Not ready", even if its check reports error', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(getPublishPreflight).mockResolvedValue(
      preflight([
        {
          id: 'portal',
          label: 'Portal',
          kind: 'canonical',
          required: true,
          health: 'ok',
          message: 'Portal manifest is packaged and ready.',
          next_step: 'Approve portal publication when review is complete.',
        },
        {
          id: 'podcast',
          label: 'Podcast episode',
          kind: 'audience',
          required: false,
          health: 'error',
          message: 'Podcast is not available yet; it is coming in a future release.',
          next_step: 'No action required.',
        },
      ]),
    )
    const { findByText, findAllByText } = renderScreen()

    // Both the surface card (item 4) and the readiness panel (item 5) show
    // the same neutral message for podcast -- confirm at least the
    // readiness panel's copy, scoped to that section.
    expect(await findByText('Future release')).toBeTruthy()
    const matches = await findAllByText(
      'Podcast is not available yet; it is coming in a future release.',
    )
    expect(matches.length).toBeGreaterThanOrEqual(1)

    // The readiness panel never labels podcast "Not ready", regardless of
    // the health value its own check carries.
    const panel = (await findByText('Readiness check')).closest('section')
    expect(panel).toBeTruthy()
    expect(within(panel as HTMLElement).queryByText('Not ready')).toBeNull()
    expect(
      within(panel as HTMLElement).getByText(
        'Podcast is not available yet; it is coming in a future release.',
      ),
    ).toBeTruthy()
  })

  it('shows a load error with a retry action, and does not itself block Approve', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(getPublishPreflight).mockRejectedValue(
      new ApiError('Request failed: 503', 503, 'Durable storage is not ready.'),
    )
    const { findByText, findByRole } = renderScreen()

    expect(await findByText('Durable storage is not ready.')).toBeTruthy()
    const retry = await findByRole('button', { name: 'Retry readiness check' })
    expect(retry).toBeTruthy()

    // Loading/errored readiness adds no NEW block: approval's own 409 is
    // still the real backstop, so a slow/broken readiness fetch alone can't
    // prevent an otherwise-valid publish.
    const publish = await findByRole('button', { name: 'Approve and Publish selected' })
    expect(publish.hasAttribute('disabled')).toBe(false)

    vi.mocked(getPublishPreflight).mockResolvedValue(
      preflight([
        {
          id: 'portal',
          label: 'Portal',
          kind: 'canonical',
          required: true,
          health: 'ok',
          message: 'Portal manifest is packaged and ready.',
          next_step: 'Approve portal publication when review is complete.',
        },
      ]),
    )
    fireEvent.click(retry)
    expect(await findByText('Ready')).toBeTruthy()
  })
})
