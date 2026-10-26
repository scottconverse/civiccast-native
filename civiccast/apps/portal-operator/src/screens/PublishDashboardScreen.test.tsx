import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { StaffIdentityResponse } from '../types/api.generated'
import type {
  PublishDashboardResponse,
  PublishPreflightResponse,
  PublishSurfaceState,
  PublishSurfaceStatus,
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
  listChannels: vi.fn(),
  stopYouTubeOutput: vi.fn(),
  retryPublishSurface: vi.fn(),
}))

import {
  ApiError,
  approvePublishAsset,
  getPublishPreflight,
  getStaffIdentity,
  listPublishAssets,
  listChannels,
  stopYouTubeOutput,
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
  it('filters every asset counted as needing action, including a blocked required surface', async () => {
    const response = dashboard('blocked')
    response.summary.needs_operator_action = 1
    response.assets[0].needs_operator_action = true
    vi.mocked(listPublishAssets).mockResolvedValue(response)
    const { findByRole, findByText } = renderScreen()

    const filter = await findByRole('tab', { name: 'Needs action' })
    fireEvent.click(filter)

    expect(await findByText('Sample asset')).toBeTruthy()
    expect(filter.getAttribute('aria-selected')).toBe('true')
  })

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

  function subscriberDashboard(
    surface: Partial<PublishSurfaceStatus> & { state: PublishSurfaceState },
  ): PublishDashboardResponse {
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
          asset_id: 'council-1',
          title: 'Council meeting',
          dashboard_state: 'reach_degraded',
          dashboard_label: 'Reaching fewer places than planned',
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
              url: 'https://records.example-city.gov/#/watch/council-1',
              last_attempt_at: null,
              completed_at: '2026-06-01T12:00:00Z',
              health: 'ok',
              message: 'Published.',
              next_step: 'None.',
            },
            {
              id: 'subscriber-notifications',
              label: 'Subscriber notifications',
              kind: 'audience',
              approval: 'approved',
              required: false,
              url: null,
              last_attempt_at: null,
              completed_at: '2026-06-01T12:00:00Z',
              health: 'warning',
              message: 'Some subscriber notices were not delivered.',
              next_step: 'Open the delivery list, then retry.',
              ...surface,
            },
          ],
        },
      ],
    }
  }

  it('shows a partly-delivered fan-out as needing a look, not as a neutral dot', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberDashboard({
        state: 'partial',
        notification_summary: {
          publication_id: 'pub:council-1',
          intended: 3,
          sent: 2,
          failed: 1,
          queued: 0,
          pending: 0,
          targets: ['channel:government'],
          deliveries: [
            {
              subscription_id: 'sub-abc',
              channel: 'webhook',
              target_type: 'channel',
              target_id: 'government',
              outcome: 'failed',
              attempts: 2,
              error_code: 'HTTPStatusError',
            },
          ],
        },
      }),
    )
    const { findByText } = renderScreen()

    // Plain language, never the raw enum.
    expect(await findByText(/audience \/ Some did not go out/i)).toBeTruthy()
    expect(await findByText('2 of 3 delivered, 1 could not be delivered (channel:government)')).toBeTruthy()
    expect(await findByText(/Could not be delivered — webhook to channel government, 2 tries/i)).toBeTruthy()
  })

  it('offers a way to send and record a run that kept no delivery receipt', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberDashboard({
        state: 'unverified',
        message: 'This publish run recorded subscriber notices as sent, but kept no receipt.',
        next_step: 'Retry the subscriber notifications surface.',
      }),
    )
    const { findByRole, findByText } = renderScreen()

    expect(await findByText(/audience \/ Cannot show it was sent/i)).toBeTruthy()
    expect(await findByRole('button', { name: 'Send and record now' })).toBeTruthy()
  })

  it('lets an operator retry a partly-delivered surface', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberDashboard({
        state: 'partial',
        notification_summary: {
          publication_id: 'pub:council-1',
          intended: 2,
          sent: 1,
          failed: 0,
          queued: 1,
          pending: 0,
          targets: ['channel:government'],
          deliveries: [
            {
              subscription_id: 'sub-abc',
              channel: 'webhook',
              target_type: 'channel',
              target_id: 'government',
              outcome: 'queued',
              attempts: 1,
              retry_id: 'swr_1',
            },
          ],
        },
      }),
    )
    vi.mocked(retryPublishSurface).mockResolvedValue(
      subscriberDashboard({ state: 'succeeded' }).assets[0],
    )
    const { findByRole } = renderScreen()

    const button = await findByRole('button', { name: 'Retry this surface' })
    fireEvent.click(button)

    await waitFor(() =>
      expect(vi.mocked(retryPublishSurface)).toHaveBeenCalledWith(
        'council-1',
        'subscriber-notifications',
        expect.anything(),
      ),
    )
  })

  it('says nobody was contacted when the mail provider is a mock', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberDashboard({
        state: 'succeeded',
        simulated: true,
        health: 'warning',
        message: 'SIMULATED - no subscriber notice actually left this station.',
        notification_summary: {
          publication_id: 'pub:council-1',
          intended: 1,
          sent: 1,
          failed: 0,
          queued: 0,
          pending: 0,
          targets: ['channel:government'],
          deliveries: [
            {
              subscription_id: 'sub-abc',
              channel: 'email',
              target_type: 'channel',
              target_id: 'government',
              outcome: 'sent',
              attempts: 1,
            },
          ],
        },
      }),
    )
    const { findByText } = renderScreen()

    expect(await findByText(/no notice actually left this station/i)).toBeTruthy()
    // The archive wording must not appear on a notifications surface.
    expect(await findByText(/Every notice has a delivery receipt\./i)).toBeTruthy()
  })

  it('says the list is capped rather than implying it is complete', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      subscriberDashboard({
        state: 'partial',
        notification_summary: {
          publication_id: 'pub:council-1',
          intended: 500,
          sent: 499,
          failed: 1,
          queued: 0,
          pending: 0,
          targets: ['channel:government'],
          deliveries_truncated: true,
          deliveries: [
            {
              subscription_id: 'sub-abc',
              channel: 'email',
              target_type: 'channel',
              target_id: 'government',
              outcome: 'failed',
              attempts: 1,
              error_code: 'SMTPDataError',
            },
          ],
        },
      }),
    )
    const { findByText } = renderScreen()

    expect(await findByText(/Showing the first 1 of 500/i)).toBeTruthy()
  })
})

describe('PublishDashboardScreen podcast delivery', () => {
  it('shows podcast as an optional selectable surface', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    const { findByText, queryAllByLabelText, queryByText } = renderScreen()

    await findByText('Podcast episode')
    expect(queryAllByLabelText(/Approve this surface/i)).toHaveLength(2)
    expect(queryByText('Coming in a future release')).toBeNull()
  })

  it('shows a failed podcast publication as retryable', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(
      podcastDashboard({ state: 'failed', health: 'error' }),
    )
    const { findByRole } = renderScreen()

    expect(await findByRole('button', { name: 'Retry this surface' })).toBeTruthy()
  })

  it('sends podcast only when the operator selects it', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(podcastDashboard())
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findByRole, findAllByLabelText } = renderScreen()

    const checkboxes = await findAllByLabelText(/Approve this surface/i)
    fireEvent.click(checkboxes[1])

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() =>
      expect(approvePublishAsset).toHaveBeenCalledWith(
        'sample-asset',
        expect.objectContaining({ approved_surface_ids: ['portal', 'podcast'] }),
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

  it('shows a podcast readiness error instead of masking it as a future release', async () => {
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
          message: 'Podcast audio is not configured.',
          next_step: 'Choose a local recording and set the public station URL.',
        },
      ]),
    )
    const { findByText } = renderScreen()
    await findByText('Podcast audio is not configured.')
    const panel = (await findByText('Readiness check')).closest('section')
    expect(panel).toBeTruthy()
    expect(within(panel as HTMLElement).getByText('Not ready')).toBeTruthy()
    expect(
      within(panel as HTMLElement).getByText('Podcast audio is not configured.'),
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

// beta.5 walkthrough F-23 (MAJOR, safety): the default selection used to be
// every approvable surface, so a one-click approval read "7 selected
// surface(s) publish for real" -- Internet Archive, both NAS archives, YouTube
// Live/VOD and the cable package included. Default is Portal only; the rest
// are opt-in per approval, and the confirm dialog names what it publishes.
function sevenSurfaceDashboard(): PublishDashboardResponse {
  const pending = (
    id: string,
    label: string,
    kind: 'canonical' | 'archive' | 'reach' | 'record',
    required: boolean,
  ) => ({
    id,
    label,
    kind,
    state: 'pending' as const,
    approval: 'pending' as const,
    required,
    url: null,
    last_attempt_at: null,
    completed_at: null,
    health: 'unknown' as const,
    message: `${label} is waiting for approval.`,
    next_step: 'Approve publish.',
    simulated: false,
  })
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
          pending('portal', 'Portal', 'canonical', true),
          pending('internet-archive', 'Internet Archive', 'archive', true),
          pending('local-nas-rsync', 'Local NAS rsync', 'archive', true),
          pending('local-nas-zfs', 'Local NAS ZFS', 'archive', true),
          pending('youtube-live', 'YouTube Live', 'reach', false),
          pending('youtube-vod', 'YouTube VOD', 'reach', false),
          pending('cable-file-package', 'Cable file package', 'record', false),
        ],
      },
    ],
  }
}

describe('PublishDashboardScreen default surface selection (F-23)', () => {
  beforeEach(() => {
    vi.mocked(listPublishAssets).mockResolvedValue(sevenSurfaceDashboard())
  })

  it('pre-checks the Portal surface only; archive and reach surfaces start unchecked', async () => {
    const { findAllByLabelText } = renderScreen()

    const boxes = (await findAllByLabelText(/Approve this surface/i)) as HTMLInputElement[]
    expect(boxes).toHaveLength(7)
    const checked = boxes.filter((box) => box.checked)
    expect(checked).toHaveLength(1)
    // The checked box belongs to the Portal row.
    expect(checked[0].closest('[data-surface-id]')?.getAttribute('data-surface-id')).toBe('portal')
  })

  it('warns that required archive surfaces are not selected', async () => {
    const { findByTestId } = renderScreen()

    const warning = await findByTestId('required-surfaces-unselected')
    expect(warning.textContent).toContain('3 required archive surfaces not selected')
    expect(warning.textContent).toContain('Internet Archive, Local NAS rsync, Local NAS ZFS')
    expect(warning.textContent).toContain('stays archive-pending')
  })

  it('confirm dialog count and names match the default selection and the request', async () => {
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findByRole, findByText } = renderScreen()

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    expect(await findByText(/1 selected surface will be attempted: Portal\./)).toBeTruthy()
    expect(
      await findByText(/becomes publicly visible to residents immediately/),
    ).toBeTruthy()
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() =>
      expect(approvePublishAsset).toHaveBeenCalledWith(
        'sample-asset',
        expect.objectContaining({ approved_surface_ids: ['portal'], overrides: [] }),
      ),
    )
  })

  it('an opted-in archive surface is named in the confirm dialog and sent with the request', async () => {
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findAllByLabelText, findByRole, findByText, queryByTestId } = renderScreen()

    const boxes = (await findAllByLabelText(/Approve this surface/i)) as HTMLInputElement[]
    const iaBox = boxes.find(
      (box) => box.closest('[data-surface-id]')?.getAttribute('data-surface-id') === 'internet-archive',
    )
    expect(iaBox).toBeTruthy()
    expect((iaBox as HTMLInputElement).checked).toBe(false)
    fireEvent.click(iaBox as HTMLInputElement)
    await waitFor(() =>
      expect(queryByTestId('required-surfaces-unselected')?.textContent).toContain(
        '2 required archive surfaces not selected (Local NAS rsync, Local NAS ZFS)',
      ),
    )

    fireEvent.click(await findByRole('button', { name: 'Approve and Publish selected' }))
    expect(
      await findByText(/2 selected surfaces will be attempted: Portal, Internet Archive\./),
    ).toBeTruthy()
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))

    await waitFor(() =>
      expect(approvePublishAsset).toHaveBeenCalledWith(
        'sample-asset',
        expect.objectContaining({ approved_surface_ids: ['portal', 'internet-archive'] }),
      ),
    )
  })
})


describe('YouTube selected-channel output', () => {
  it('sends the chosen source channel with approval', async () => {
    vi.mocked(listPublishAssets).mockResolvedValue(sevenSurfaceDashboard())
    vi.mocked(listChannels).mockResolvedValue([{ channel_id: 'government', slug: 'Government' }] as never)
    vi.mocked(approvePublishAsset).mockResolvedValue({} as never)
    const { findAllByLabelText, findByLabelText, findByRole } = renderScreen()
    const boxes = await findAllByLabelText(/Approve this surface/i)
    fireEvent.click(boxes.find((box) => box.closest('[data-surface-id]')?.getAttribute('data-surface-id') === 'youtube-live')!)
    const approve = await findByRole('button', { name: 'Approve and Publish selected' })
    expect((approve as HTMLButtonElement).disabled).toBe(true)
    const select = await findByLabelText('Channel sent to YouTube Live')
    await findByRole('option', { name: 'Government' })
    fireEvent.change(select, { target: { value: 'government' } })
    fireEvent.click(approve)
    fireEvent.click(await findByRole('button', { name: 'Approve and Publish' }))
    await waitFor(() => expect(approvePublishAsset).toHaveBeenCalledWith('sample-asset', expect.objectContaining({ youtube_channel_id: 'government', approved_surface_ids: ['portal', 'youtube-live'] })))
  })

  it('stops only the YouTube output from a running surface', async () => {
    const response = sevenSurfaceDashboard()
    const surface = response.assets[0].surfaces.find((item) => item.id === 'youtube-live')!
    surface.state = 'running'
    surface.delivery_state = 'starting'
    surface.channel_id = 'government'
    vi.mocked(listPublishAssets).mockResolvedValue(response)
    vi.mocked(stopYouTubeOutput).mockResolvedValue({ delivery_state: 'stopped' } as never)
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: 'Stop YouTube output' }))
    await waitFor(() => expect(stopYouTubeOutput).toHaveBeenCalledWith('sample-asset'))
  })
})
