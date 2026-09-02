import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { StaffIdentityResponse } from '../types/api.generated'
import type { PublishDashboardResponse, PublishSurfaceState } from '../types/publish'

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
  getStaffIdentity: vi.fn(),
  listPublishAssets: vi.fn(),
  retryPublishSurface: vi.fn(),
}))

import {
  ApiError,
  approvePublishAsset,
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

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue({
    operator_id: 'dana',
    operator_display_name: 'Dana',
    roles: ['publish_operator'],
  } as StaffIdentityResponse)
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
