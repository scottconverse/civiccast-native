import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(cleanup)

import type { CgFeedSource, CgZoneConfig, ResolvedBoard } from '../types/api.generated'
import { BoardCreateForm, BoardPreviewPanel, FeedForm, ZoneForm } from './CgBoardDesignerScreen'

const FEED: CgFeedSource = {
  feed_source_id: 'feed_rss',
  channel_id: 'public',
  kind: 'rss',
  label: 'City news',
  source_url: 'https://x.gov/news.rss',
  trust_tier: 'operator_curated',
  refresh_seconds: 900,
  enabled: true,
  created_by: 'op',
  created_at: '2026-01-01T00:00:00Z',
}

// --- isolated form / panel component tests ---

describe('BoardCreateForm', () => {
  it('submits the chosen template id', () => {
    const onSubmit = vi.fn()
    const { getByText } = render(<BoardCreateForm submitting={false} onSubmit={onSubmit} />)
    fireEvent.click(getByText('Create board'))
    expect(onSubmit).toHaveBeenCalledWith({ template_id: 'standard-community-board' })
  })
})

describe('ZoneForm', () => {
  it('builds a manual zone payload by default', () => {
    const onSubmit = vi.fn()
    const { getByText } = render(<ZoneForm feeds={[]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.click(getByText('Add zone'))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.content_source).toBe('manual')
    expect(payload.zone_kind).toBe('ticker')
    expect(payload.feed_source_id).toBeNull()
  })

  it('blocks a feed zone with no feed and shows the rule', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText, queryByText } = render(
      <ZoneForm feeds={[FEED]} submitting={false} onSubmit={onSubmit} />,
    )
    fireEvent.change(getByLabelText('Content source'), { target: { value: 'feed_adapter' } })
    expect(getByText(/must name a feed/)).toBeTruthy()
    expect((getByText('Add zone') as HTMLButtonElement).disabled).toBe(true)
    // Selecting a feed clears the block.
    fireEvent.change(getByLabelText('Feed source'), { target: { value: 'feed_rss' } })
    expect(queryByText(/must name a feed/)).toBeNull()
    fireEvent.click(getByText('Add zone'))
    expect(onSubmit.mock.calls[0][0].feed_source_id).toBe('feed_rss')
  })

  it('includes parsed allowed_tags in the payload', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(<ZoneForm feeds={[]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Allowed tags'), { target: { value: 'events, alerts, events' } })
    fireEvent.click(getByText('Add zone'))
    expect(onSubmit.mock.calls[0][0].allowed_tags).toEqual(['events', 'alerts'])
  })

  it('edit mode prefills and uses a Save-changes label', () => {
    const zone: CgZoneConfig = {
      zone_id: 'z1',
      board_id: 'b1',
      region: 'lower',
      zone_kind: 'ticker',
      content_source: 'manual',
      approval_required: false,
      manual_text: 'Welcome',
      created_at: '2026-01-01T00:00:00Z',
    }
    const { getByText, getByDisplayValue } = render(
      <ZoneForm feeds={[]} submitting={false} onSubmit={vi.fn()} initial={zone} />,
    )
    expect(getByDisplayValue('Welcome')).toBeTruthy()
    expect(getByText('Save changes')).toBeTruthy()
  })
})

describe('FeedForm', () => {
  it('converts refresh minutes to seconds on submit', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(
      <FeedForm submitting={false} onSubmit={onSubmit} />,
    )
    fireEvent.change(getByLabelText('Feed label'), { target: { value: 'News' } })
    fireEvent.change(getByLabelText('Source URL'), {
      target: { value: 'https://x.gov/n.rss' },
    })
    fireEvent.change(getByLabelText('Refresh (minutes)'), { target: { value: '15' } })
    fireEvent.change(getByLabelText('Feed tags'), { target: { value: 'events, community' } })
    fireEvent.click(getByText('Register feed'))
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.refresh_seconds).toBe(900)
    expect(payload.tags).toEqual(['events', 'community'])
  })

  it('blocks a public-permitted weather feed', () => {
    const { getByText, getByLabelText } = render(
      <FeedForm submitting={false} onSubmit={vi.fn()} />,
    )
    fireEvent.change(getByLabelText('Feed label'), { target: { value: 'WX' } })
    fireEvent.change(getByLabelText('Source URL'), {
      target: { value: 'https://x.gov/wx.json' },
    })
    fireEvent.change(getByLabelText('Feed kind'), { target: { value: 'weather' } })
    fireEvent.change(getByLabelText('Trust tier'), { target: { value: 'public_permitted' } })
    expect(getByText(/must be operator or partner curated/)).toBeTruthy()
    expect((getByText('Register feed') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('BoardPreviewPanel', () => {
  it('shows zones, the back-filled note, and a degraded zone warning', () => {
    const resolved: ResolvedBoard = {
      board_id: 'b1',
      backfilled_kinds: ['logo'],
      degraded_zone_ids: ['z_feed'],
      snapshot: {
        snapshot_id: 'public-community-board',
        generated_at: '2026-06-01T18:00:00Z',
        channel_id: 'public',
        template: { template_id: 'standard-community-board', label: 'Standard', aspect_ratio: '16:9', regions: [] },
        zones: [
          { zone_id: 'z_feed', kind: 'ticker', title: 'City news', source: 'feed_adapter', content: {}, approved: true },
          { zone_id: 'z_manual', kind: 'primary', title: 'Now showing', source: 'manual', content: {}, approved: true },
        ],
        hls_render_path: '/x.m3u8',
        portal_render_path: '/snap',
        proof_boundary: 'pb',
      },
    }
    const { container, getByText } = render(<BoardPreviewPanel resolved={resolved} />)
    expect(getByText(/Using defaults for unconfigured zones: logo/)).toBeTruthy()
    expect(container.textContent).toContain('City news')
    expect(getByText(/Feed unavailable/)).toBeTruthy()
  })
})

// --- container role gate (mocked client) ---

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  },
  getStaffIdentity: vi.fn(),
  getAppPlatformConfig: vi.fn(),
  getCgBoard: vi.fn(),
  previewCgBoard: vi.fn(),
  listCgBoardAudit: vi.fn(),
  createCgBoard: vi.fn(),
  updateCgBoard: vi.fn(),
  addCgZone: vi.fn(),
  updateCgZone: vi.fn(),
  deleteCgZone: vi.fn(),
  addCgFeed: vi.fn(),
  updateCgFeed: vi.fn(),
  deleteCgFeed: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import { getAppPlatformConfig, getCgBoard, getStaffIdentity, listCgBoardAudit } from '../api/client'
import { CgBoardDesignerScreen } from './CgBoardDesignerScreen'

function identity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op', operator_display_name: 'Op', roles }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CgBoardDesignerScreen />
    </QueryClientProvider>,
  )
}

describe('CgBoardDesignerScreen container role gate', () => {
  it('shows an access note for an operator without a CG role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue({ channels: [] } as never)
    const { findByText } = renderScreen()
    expect(await findByText(/requires the publish operator, setup admin, or support admin role/)).toBeTruthy()
  })

  it('offers the create-board form to a publish operator with no board', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue({ channels: [] } as never)
    vi.mocked(getCgBoard).mockResolvedValue(null)
    const { findByText } = renderScreen()
    expect(await findByText('Create a CG board for this channel')).toBeTruthy()
  })

  it('is read-only for a support admin (no create affordance)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue({ channels: [] } as never)
    vi.mocked(getCgBoard).mockResolvedValue(null)
    vi.mocked(listCgBoardAudit).mockResolvedValue([])
    const { findByText, queryByText } = renderScreen()
    expect(await findByText('No board configured for this channel yet.')).toBeTruthy()
    expect(queryByText('Create a CG board for this channel')).toBeNull()
  })
})
