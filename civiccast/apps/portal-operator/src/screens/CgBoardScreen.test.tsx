import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  CgBulletinQueue,
  CgBulletinSubmission,
  CgPortalDisplay,
  CgTemplate,
  StaffIdentityResponse,
} from '../types/api.generated'
import { ToastProvider } from '../components/Toast'

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
  getStaffIdentity: vi.fn(),
  getStaffBulletinQueue: vi.fn(),
  createCgBulletin: vi.fn(),
  moderateCgBulletin: vi.fn(),
}))

import {
  getStaffBulletinQueue,
  getStaffIdentity,
  moderateCgBulletin,
} from '../api/client'
import { BulletinModerationPanel, FeedPanel, LayoutPreview, OutputPanel } from './CgBoardScreen'

// vitest config has no global afterEach, so testing-library's auto-cleanup
// never registers -- unmount each render so body-scoped queries don't see
// elements left behind by the previous test.
afterEach(cleanup)

const TEMPLATE: CgTemplate = {
  template_id: 'tpl-board-v1',
  label: 'Fullscreen board with ticker',
  regions: [{ region: 'main', zone_kind: 'primary', order: 0 }],
}

const FEED_CATALOG = {
  generated_at: '2026-08-06T12:00:00Z',
  channel_id: 'public',
  adapters: [
    {
      adapter_id: 'cgfeed_a1',
      kind: 'rss',
      label: 'City news',
      source_url: 'https://city.example.gov/news.rss',
      trust_tier: 'operator_curated',
      refresh_seconds: 900,
      target_zone_kinds: ['ticker'],
      items: [],
    },
  ],
  proof_boundary: 'configured-feed-adapters-to-approved-cg-zone-items',
}

const DISPLAY = {
  channel_id: 'public',
  snapshot: {
    snapshot_id: 'snap-1',
    generated_at: '2026-08-06T12:00:00Z',
    channel_id: 'public',
    template: TEMPLATE,
    zones: [],
    hls_render_path: '/var/civiccast/hls/public',
    portal_render_path: '/var/civiccast/portal/public/board.json',
    proof_boundary: 'S6 V1',
  },
  feed_catalog: FEED_CATALOG,
  render_plan: {
    channel_id: 'public',
    snapshot_url: 'https://cdn.example.org/public/snapshot.json',
    manifest_url: 'https://cdn.example.org/public/live.m3u8',
    segment_pattern: 'seg-%05d.ts',
    target_duration_seconds: 6,
    linear_overlay_contract_url: 'https://cdn.example.org/public/overlay.json',
    proof_boundary: 'S6 V1',
  },
} as unknown as CgPortalDisplay

describe('LayoutPreview', () => {
  it('shows human-readable loading copy, not raw placeholder tokens, before data arrives', () => {
    // Gate finding m-1: `template?.template_id ?? 'loading-template'` and
    // `display?.snapshot.proof_boundary ?? 'loading'` used to leak technical
    // placeholder tokens straight to the operator during transient states.
    const { getByText, queryByText } = render(
      <LayoutPreview template={undefined} display={undefined} />,
    )
    expect(getByText('Loading template…')).toBeTruthy()
    expect(getByText('Loading…')).toBeTruthy()
    expect(queryByText('loading-template')).toBeNull()
    expect(queryByText('loading')).toBeNull()
  })

  it('shows the real template id and proof boundary once loaded', () => {
    const { getByText } = render(<LayoutPreview template={TEMPLATE} display={DISPLAY} />)
    expect(getByText('tpl-board-v1')).toBeTruthy()
    expect(getByText('S6 V1')).toBeTruthy()
  })
})

describe('OutputPanel', () => {
  it('shows human-readable loading copy before data arrives', () => {
    const { getAllByText, queryByText } = render(<OutputPanel display={undefined} />)
    expect(getAllByText('Loading…')).toHaveLength(3)
    expect(queryByText('loading')).toBeNull()
  })

  it('shows the real output paths once loaded', () => {
    const { getByText } = render(<OutputPanel display={DISPLAY} />)
    expect(getByText('/var/civiccast/portal/public/board.json')).toBeTruthy()
    expect(getByText('https://cdn.example.org/public/live.m3u8')).toBeTruthy()
    expect(getByText('https://cdn.example.org/public/overlay.json')).toBeTruthy()
  })
})

// WP-06: the Dynamic feeds panel used to always render a deterministic
// sample catalog (four example.invalid adapters) with no loading, empty, or
// failed state of its own. It now reads the durable feed catalog and must
// design each of those states honestly.
describe('FeedPanel', () => {
  it('shows loading copy while the catalog is loading', () => {
    const { getByText } = render(
      <FeedPanel display={undefined} isLoading isError={false} error={undefined} />,
    )
    expect(getByText('Loading configured feeds…')).toBeTruthy()
  })

  it('shows an actionable empty state when the station has configured no feeds', () => {
    const { getByText } = render(
      <FeedPanel
        display={{ ...DISPLAY, feed_catalog: { ...FEED_CATALOG, adapters: [] } }}
        isLoading={false}
        isError={false}
        error={undefined}
      />,
    )
    expect(getByText('No dynamic feeds are configured.')).toBeTruthy()
    expect(
      getByText(
        'Add an approved RSS, calendar, weather, or permitted social source before using feed-driven CG zones.',
      ),
    ).toBeTruthy()
  })

  it('lists each configured adapter once the catalog has loaded', () => {
    const { getByText } = render(
      <FeedPanel display={DISPLAY} isLoading={false} isError={false} error={undefined} />,
    )
    expect(getByText('City news')).toBeTruthy()
    expect(getByText('https://city.example.gov/news.rss')).toBeTruthy()
    expect(getByText('rss')).toBeTruthy()
  })

  it('shows an error message and never the sample catalog when the fetch fails', () => {
    const { getByRole, queryByText } = render(
      <FeedPanel
        display={undefined}
        isLoading={false}
        isError
        error={new Error('Network error')}
      />,
    )
    expect(getByRole('alert').textContent).toContain('Network error')
    expect(queryByText('example.invalid', { exact: false })).toBeNull()
  })
})

function submission(overrides: Partial<CgBulletinSubmission> = {}): CgBulletinSubmission {
  return {
    submission_id: 'sub-1',
    organization: 'Friends of the Library',
    submitter_label: 'Jamie R.',
    title: 'Book sale this Saturday',
    message: 'Come by the library annex 9am-2pm.',
    target_zone_kind: 'ticker',
    state: 'submitted',
    ...overrides,
  }
}

function queue(submissions: CgBulletinSubmission[]): CgBulletinQueue {
  return {
    generated_at: '2026-08-06T12:00:00Z',
    channel_id: 'public',
    submissions,
    approved_zone_items: [],
    proof_boundary: 'S6 V1',
  }
}

function identity(): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles: ['records_clerk'] } as StaffIdentityResponse
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <BulletinModerationPanel channelId="public" />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

// Gate finding: "Request changes" and "Decline" used window.prompt, which
// breaks the native webview theme, and a cancelled/blank prompt silently
// did nothing. The in-app dialog must replace both actions and never
// no-op silently.
describe('BulletinModerationPanel moderation dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue(identity())
    vi.mocked(getStaffBulletinQueue).mockResolvedValue(queue([submission()]))
    vi.mocked(moderateCgBulletin).mockResolvedValue(submission({ state: 'needs_changes' }))
  })
  afterEach(cleanup)

  it('opens an in-app dialog for Request changes instead of window.prompt', async () => {
    const promptSpy = vi.spyOn(window, 'prompt')
    const { findByRole } = renderPanel()
    fireEvent.click(await findByRole('button', { name: 'Request changes' }))
    expect(await findByRole('dialog')).toBeTruthy()
    expect(promptSpy).not.toHaveBeenCalled()
    promptSpy.mockRestore()
  })

  it('submits the typed note and calls moderateCgBulletin with needs_changes', async () => {
    const { findByRole, findByPlaceholderText } = renderPanel()
    fireEvent.click(await findByRole('button', { name: 'Request changes' }))
    const textarea = await findByPlaceholderText('What needs to change before this bulletin can air?')
    fireEvent.change(textarea, { target: { value: 'Fix the date, it says Saturday but the event is Sunday.' } })
    fireEvent.click(await findByRole('button', { name: 'Send request' }))
    await waitFor(() =>
      expect(vi.mocked(moderateCgBulletin)).toHaveBeenCalledWith('public', 'sub-1', {
        state: 'needs_changes',
        moderation_notes: 'Fix the date, it says Saturday but the event is Sunday.',
      }),
    )
  })

  it('toasts and keeps the dialog open on a blank submission instead of silently no-op-ing', async () => {
    const { findByRole, queryByRole, findByText } = renderPanel()
    fireEvent.click(await findByRole('button', { name: 'Decline' }))
    fireEvent.click(await findByRole('button', { name: 'Decline bulletin' }))
    expect(await findByText(/Enter a note before submitting/i)).toBeTruthy()
    expect(queryByRole('dialog')).toBeTruthy()
    expect(vi.mocked(moderateCgBulletin)).not.toHaveBeenCalled()
  })

  it('toasts on cancel instead of silently no-op-ing', async () => {
    const { findByRole, queryByRole, findByText } = renderPanel()
    fireEvent.click(await findByRole('button', { name: 'Decline' }))
    fireEvent.click(await findByRole('button', { name: 'Cancel' }))
    expect(await findByText(/Decline cancelled/i)).toBeTruthy()
    expect(queryByRole('dialog')).toBeNull()
    expect(vi.mocked(moderateCgBulletin)).not.toHaveBeenCalled()
  })
})
